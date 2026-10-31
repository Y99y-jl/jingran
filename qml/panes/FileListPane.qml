import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import ".."
import "../components"

// 中栏文件列表（B 组全功能；M29 按 UI 规格 V3 §4.3 / §5 重绘）。
// 事件：单 MouseArea 原始事件全部转发 controller.fileEvent → 状态机；
// QML 只应用返回的 intents。
// ⚠️ 列宽「相邻让位」+ lw() 再分配算法（cw/setCW/setCWRaw/lw/colX 与
//    hdrMA 的 press/move/release）**逐字保留**，只改列初值与绘制。
Rectangle {
    id: pane
    color: Theme.cPanel
    radius: Theme.rPanel
    clip: true
    antialiasing: true

    signal requestExpandRight()
    signal clearSearchRequested()

    property var colW: ({})
    property string sortCol: "latest"
    property bool sortDesc: true
    property var selectedFids: []
    property int anchorIndex: -1
    property var viewInfo: ({})

    property var treePane: null
    property string overTreeCid: ""

    // ---- M92：页脚状态位（承接已删除的底部状态条）----
    // dim = 无消息 → 显示极淡「就绪」；ok / err 着色并带圆点；info 用中性色。
    // 右对齐绝对定位，出现与消失都不推动任何布局。
    property string statusMsg: ""
    property string statusKind: "dim"

    function showStatus(text, kind) {
        if (kind === "dim" || !text) {
            statusMsg = ""
            statusKind = "dim"
            statusReset.stop()
            return
        }
        statusMsg = String(text).trim()
        statusKind = kind
        statusReset.restart()
    }

    // M39：外部文件拖入时命中的文件行（高亮用；空串=没指到行）
    property string dropHoverFid: ""

    // M31：界面内拖拽的自绘跟随图标（null=隐藏；坐标为窗口系）
    property var dragGhost: null

    // M85：版本卡片拖入界面时的落点（"none" / "cid" / "list"）
    property string verDropKind: "none"
    property string verDropCid: ""

    // M88：切换分类 / 清空搜索时列表淡入（换内容要有交代）
    property string lastViewKey: ""

    NumberAnimation {
        id: listFade
        target: list
        property: "opacity"
        from: 0.45
        to: 1.0
        duration: Theme.durBase
        easing.bezierCurve: Theme.easeDecel
    }

    function updateVersionDrop(gx, gy) {
        var cid = hitTreeRow(gx, gy)
        if (cid !== "") {
            pane.verDropKind = "cid"
            pane.verDropCid = cid
            if (treePane) treePane.setFileDrop(cid)
            return
        }
        if (treePane) treePane.setFileDrop("")
        var w = pane.Window.window
        if (!w) { pane.verDropKind = "none"; return }
        var pos = pane.mapFromItem(w.contentItem, gx - w.x, gy - w.y)
        pane.verDropKind = (pos.x >= 0 && pos.x <= pane.width
                            && pos.y >= 0 && pos.y <= pane.height)
                           ? "list" : "none"
        pane.verDropCid = ""
    }

    function takeVersionDrop() {
        var r = { kind: pane.verDropKind, cid: pane.verDropCid }
        pane.verDropKind = "none"
        pane.verDropCid = ""
        if (treePane) treePane.setFileDrop("")
        return r
    }

    // M85：版本拖到文件区的落点提示（只描一圈，不遮挡内容）
    Rectangle {
        anchors.fill: parent
        anchors.margins: Theme.sp2
        radius: Math.max(4, Theme.rPanel - 4)
        color: "transparent"
        border.width: 2
        border.color: Qt.rgba(Theme.cAccent.r, Theme.cAccent.g,
                              Theme.cAccent.b, 0.5)
        visible: pane.verDropKind === "list"
        z: 900
    }

    // M76：拖文件悬停到「有子分级」的分类上 500ms → 自动展开，这样才能
    // 继续往下拖进子分类。只开不合（controller.expandCollection 幂等），
    // 且延时启动，避免拖过一串分类时整棵树被全部展开。
    Timer {
        id: hoverExpandTimer
        // M84：500 → 400。用户实测觉得 500ms 要"停一下等它"，
        // 400ms 既够区分"拖过去"和"停在这"，又不至于让人等。
        interval: 400
        repeat: false
        onTriggered: {
            if (pane.overTreeCid !== "")
                controller.expandCollection(pane.overTreeCid)
        }
    }

    function hitTreeRow(gx, gy) {
        var t = treePane
        if (!t) return ""
        var w = pane.Window.window
        if (!w) return ""
        var pos = t.mapFromItem(w.contentItem, gx - w.x, gy - w.y)
        // M75-4：必须先判水平边界。旧实现只按 y 找行（lv.indexAt(10, …)），
        // x 完全不参与——鼠标在文件区上方拖动时，只要 y 撞上分类树某一行
        // 就被判成"落在分类区"，松手后文件被改名归到该分类。用户看到的
        // 「在软件内随便拖一下分类就变了」就是这里。
        if (pos.x < 0 || pos.x > t.width) return ""
        if (pos.y < 0 || pos.y > t.height) return ""
        var lv = t.listViewRef
        if (!lv) return ""
        var idx = lv.indexAt(10, pos.y - lv.y + lv.contentY)
        if (idx < 0) return ""
        var row = categoriesModel.row_at(idx)
        if (!row || row.isBuiltin === true) return ""
        return row.cid
    }

    // M39：外部文件拖入的行命中（x/y 为**本 pane** 坐标系；调用方先
    // mapFromItem 转过来——避免窗口/场景坐标换算歧义与 id 作用域问题）。
    // 回收站伪行不接收落点。
    function hitFileRowAt(x, y) {
        var pos = list.mapFromItem(pane, x, y)
        if (pos.x < 0 || pos.y < 0
                || pos.x >= list.width || pos.y >= list.height)
            return ""
        // M62：indexAt 吃的是 contentItem 坐标，滚动后必须补 contentY
        var idx = list.indexAt(pos.x, pos.y + list.contentY)
        if (idx < 0) return ""
        var row = filesModel.row_at(idx)
        if (!row || row.isTrash === true) return ""
        return row.fid || ""
    }

    function loadCols() {
        colW = JSON.parse(controller.fileColWidths())
    }

    function applySelected(fids) {
        selectedFids = fids
    }

    function refreshViewInfo() {
        viewInfo = JSON.parse(controller.lastView())
        // 视图标识 = 标题 + 搜索词；变了才淡入，刷新数据时不闪
        var vk = String(viewInfo.title || "") + "|" + String(viewInfo.searchInfo || "")
        if (lastViewKey !== "" && vk !== lastViewKey) listFade.restart()
        lastViewKey = vk
        var st = viewInfo.emptyState || "none"
        emptyBox.visible = (st !== "none")
        if (emptyBox.visible) {
            emptyTitle.text = viewInfo.emptyTitle || ""
            emptySub.text = viewInfo.emptySub || ""
            commitBtn.visible = viewInfo.showCommitBtn === true
            clearBtn.visible = viewInfo.showClearSearchBtn === true
        }
        searchInfo.text = viewInfo.searchInfo || ""
        searchInfo.visible = searchInfo.text !== ""
    }

    Component.onCompleted: {
        loadCols()
        loadColsVisible()
        refreshViewInfo()
    }

    Connections {
        target: controller
        function onFilesChanged() {
            refreshViewInfo()
            pane.applySelected(JSON.parse(controller.getSelection()))
        }
        function onFileColsChanged() { pane.loadColsVisible() }
    }

    // ---- §3 列宽初值：名称 280 / 类型 70 / 分类 110 / 最近版本 120 /
    //      版本数 60（右对齐）+ 星标 40。顺序 = 生产 5 列 + 末尾星标格。
    //      stretch/min 语义与 M25 定稿一致（星标非拉伸，恒 40）。
    // M35 §3.2：生产列原样改名 baseColDefs（内容逐字不动）；回收站视图
    // （viewInfo.inTrash === true）换用 trashColDefs 单独列头。
    property var baseColDefs: [
        // min 值按「内容必须容得下」给：类型至少 4 个字母(DOCX)、分类至少能显示
        // 末级名、时间至少 11 字符(10-24 23:54)、版本数至少 2 位。
        // 原来一律 min:20，拖窄后会出现 "DO…" / "222/…" 这种废信息。
        {key: "name",       title: "文件名",   def: 260, min: 120, stretch: true},
        {key: "kind",       title: "文件类型", def: 70,  min: 56,  stretch: true},
        {key: "collection", title: "分类",     def: 132, min: 72,  stretch: true},
        {key: "latest",     title: "最近版本", def: 120, min: 92,  stretch: true},
        {key: "count",      title: "版本数",   def: 60,  min: 56,  stretch: true},
        {key: "star",       title: "",         def: 40,  min: 28, stretch: false}
    ]
    // 回收站列（M35 §3.2；M40 加「清除」）：文件名 / 原分类 / 删除时间 /
    // 版本数 / 还原·清除。末列 112 = 12 内距 + 46 还原 + 6 间距 + 46 清除
    // + 2 余量；配合 lw() 在回收站视图预留 16px 滚动条槽，胶囊不再压线。
    property var trashColDefs: [
        {key: "t_name", title: "文件名",   def: 280, min: 20,  stretch: true},
        {key: "t_orig", title: "原分类",   def: 110, min: 20,  stretch: true},
        {key: "t_del",  title: "删除时间", def: 120, min: 20,  stretch: true},
        {key: "t_cnt",  title: "版本数",   def: 60,  min: 20,  stretch: true},
        {key: "t_rst",  title: "还原/清除", def: 112, min: 112, stretch: false}
    ]
    property var colDefs: (viewInfo.inTrash === true) ? trashColDefs : baseColDefs
    // ---- M56：列显隐（配置存后端 ui.cols_hidden）----
    property var colsHidden: []
    function colVisible(key) {
        if (viewInfo.inTrash === true) return true   // 回收站列固定
        return colsHidden.indexOf(key) < 0
    }
    function loadColsVisible() {
        var spec = JSON.parse(controller.fileColumnsSpec())
        var hid = [], ord = []
        for (var i = 0; i < spec.length; i++) {
            ord.push(spec[i].key)
            if (spec[i].visible !== true) hid.push(spec[i].key)
        }
        colsHidden = hid
        colsOrder = ord
    }

    // ---- M62：列顺序（正常视图可自定义；回收站保持固定）----
    property var colsOrder: []

    function cols() {
        if (viewInfo.inTrash === true) return colDefs
        var byKey = ({})
        for (var i = 0; i < colDefs.length; i++)
            byKey[colDefs[i].key] = colDefs[i]
        var out = []
        for (var j = 0; j < colsOrder.length; j++)
            if (byKey[colsOrder[j]]) out.push(byKey[colsOrder[j]])
        for (var k = 0; k < colDefs.length; k++)     // 兜底：未列出的追加
            if (colsOrder.indexOf(colDefs[k].key) < 0) out.push(colDefs[k])
        return out
    }
    function colIndexByKey(key) {
        var cs = cols()
        for (var i = 0; i < cs.length; i++)
            if (cs[i].key === key) return i
        return -1
    }
    // 按 key 取 x / 宽（行内单元格用；回收站视图退回索引法）
    function colXk(key) {
        // M72：回收站视图的列是 t_name/t_orig/t_del/t_cnt，按 key 查不到；
        // 原来直接 return 0 → 文件名格宽度 0，回收站整列名字消失。
        // 这里给 name 退回索引 0（t_name），其余普通列在回收站本来就不显示。
        if (viewInfo.inTrash === true) return key === "name" ? colX(0) : 0
        var i = colIndexByKey(key)
        return i < 0 ? 0 : colX(i)
    }
    function colWk(key) {
        if (viewInfo.inTrash === true) return key === "name" ? lw(0) : 0
        var i = colIndexByKey(key)
        return i < 0 ? 0 : lw(i)
    }

    function cw(i) { return pane.colW[cols()[i].key] || cols()[i].def }
    function setCW(i, w) {
        var cs = cols()
        var c = Object.assign({}, pane.colW)
        var cap = pane.width - 20 * (cs.length - 1)
        if (cap < cs[i].min) cap = cs[i].min
        c[cs[i].key] = Math.min(Math.max(cs[i].min, Math.round(w)), cap)
        pane.colW = c
    }
    function setCWRaw(i, w) {
        var cs = cols()
        var c = Object.assign({}, pane.colW)
        c[cs[i].key] = Math.round(w)
        pane.colW = c
    }

    function lw(i) {
        var cs = cols()
        // M40：回收站视图右侧预留 16px 给滚动条
        var avail = pane.width - (viewInfo.inTrash === true ? 16 : 0)
        var bases = [], st = []
        var total = 0
        for (var k = 0; k < cs.length; k++) {
            bases[k] = pane.colVisible(cs[k].key) ? cw(k) : 0
            total += bases[k]
            if (cs[k].stretch && pane.colVisible(cs[k].key)) st.push(k)
        }
        var extra = avail - total
        if (extra > 0 && st.length > 0) {
            var wts = {name: 3, kind: 1, collection: 1.5, latest: 1.5,
                       count: 1, t_name: 3, t_orig: 1.5, t_del: 1.5,
                       t_cnt: 1}
            var sumW = 0
            for (k = 0; k < st.length; k++)
                sumW += (wts[cs[st[k]].key] || 1)
            var acc = 0
            for (k = 0; k < st.length; k++) {
                var w = (wts[cs[st[k]].key] || 1) / sumW
                var add = (k === st.length - 1) ? extra - acc
                                                : Math.floor(extra * w)
                bases[st[k]] += add
                acc += add
            }
        } else if (extra < 0) {
            var d = []
            var sumD = 0
            for (k = 0; k < cs.length; k++) {
                d[k] = Math.max(bases[k], cs[k].min)
                sumD += d[k]
            }
            var deficit = sumD - avail
            var guard = 0
            while (deficit > 0.01 && guard < 10) {
                guard++
                var act = []
                for (k = 0; k < cs.length; k++)
                    if (cs[k].stretch && d[k] - cs[k].min > 0.01)
                        act.push(k)
                if (act.length === 0) break
                var each = deficit / act.length
                for (k = 0; k < act.length; k++) {
                    var dec = Math.min(each, d[k] - cs[k].min)
                    d[k] -= dec
                    deficit -= dec
                }
            }
            if (deficit > 0.01) {
                var sum2 = 0
                for (k = 0; k < cs.length; k++) sum2 += d[k]
                if (sum2 > 0.01) {
                    var ratio = (sum2 - deficit) / sum2
                    for (k = 0; k < cs.length; k++)
                        d[k] = Math.max(8, d[k] * ratio)
                }
            }
            for (k = 0; k < cs.length; k++) bases[k] = d[k]
        }
        // M62：隐藏列必须返回 0——旧实现 Math.max(8, …) 会让每隐藏一列
        // 就把后面的列边界右推 8px，表头拖拽/排序都会落到错列
        if (bases[i] <= 0.5) return 0
        return Math.round(Math.max(8, bases[i]))
    }

    function colX(i) {
        var a = 0
        for (var k = 0; k < i; k++) a += lw(k)
        return a
    }

    // 页脚文案（§4.3）
    function totalText() {
        var n = viewInfo.total || 0
        var m = selectedFids.length
        return n + " 个文件 · 已选 " + m + " 项"
    }

    Column {
        anchors.fill: parent
        spacing: 0

        Text {
            id: searchInfo
            visible: false
            height: visible ? 24 : 0
            leftPadding: 16
            verticalAlignment: Text.AlignVCenter
            font.family: Theme.fontFamily
            font.pointSize: Theme.pt(Theme.fsMeta)
            color: Theme.cTextDim
        }

        // ---- 页面标题区（规格 §2.5 / 图 00）：20/SemiBold + 统计行 ----
        // ⚠️ 纯展示：标题与计数全部来自既有只读投影（viewInfo / treePane.selectedCid），
        //    不新增业务状态，不碰列宽算法。
        Item {
            id: pageTitle
            width: parent.width
            height: 64
            // M53：空态也保留标题行，顶部结构与有内容的分类一致
            visible: true

            function viewTitle() {
                if (viewInfo.inTrash === true) return "回收站"
                if (viewInfo.collection) return viewInfo.collection
                var cid = treePane ? treePane.selectedCid : "__all__"
                if (!cid || cid === "__all__") return "全部文件"
                if (cid === "__unfiled__") return "未分类"
                if (cid === "__trash__") return "回收站"
                var r = treePane ? treePane.rowOf(cid) : null
                return (r && r.label) ? r.label : "全部文件"
            }

            Text {
                id: pageTitleText
                x: 20
                y: 12
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsPage)
                font.weight: Font.DemiBold
                color: Theme.cText
                text: pageTitle.viewTitle()
            }
            Text {
                x: 20
                y: 40
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsMeta)
                color: Theme.cTextDim
                text: (viewInfo.total || 0) + " 个文件"
                      + ((viewInfo.kw && viewInfo.searchInfo)
                         ? " · " + viewInfo.searchInfo : "")
            }
        }

        // ---- 表头 36：无底色、无竖线、10.5/SemiBold/字距 .5、与数据同侧 ----
        Rectangle {
            id: header
            width: parent.width
            height: 36
            color: "transparent"
            z: 2

            Row {
                id: headerRow
                anchors.fill: parent

                Repeater {
                    model: pane.cols()

                    Item {
                        id: hcol
                        required property int index
                        visible: pane.colVisible(modelData.key)
                        required property var modelData
                        readonly property bool isLast:
                            pane.lastVisibleIndex() === index
                        readonly property bool numCol: modelData.key === "count" || modelData.key === "t_cnt"
                        width: pane.lw(index)
                        height: parent.height

                        Text {
                            // §5：表头与数据同侧——文本列左、数值列右
                            anchors.left: hcol.numCol ? undefined : parent.left
                            anchors.right: hcol.numCol ? parent.right : undefined
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            // 右侧只留 2px：70px 的类型列还要放得下「文件类型」
                            // 四个字（10.5/SemiBold/字距 .5），-24 会提前省略
                            width: parent.width - 14
                            horizontalAlignment: hcol.numCol ? Text.AlignRight
                                                             : Text.AlignLeft
                            elide: Text.ElideRight
                            text: hcol.modelData.title
                                  + (pane.sortCol === hcol.modelData.key
                                     ? (pane.sortDesc ? " ▼" : " ▲") : "")
                            // M36→M37：两轮反馈「还是有些小」——
                            // 表头 10.5→11.5→12.5（12.5 为字面量，与版本卡
                            // vNo/弹窗路径同号，注释里的旧规格口径作废）
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(12.5)
                            font.weight: Font.DemiBold
                            font.letterSpacing: Theme.lsLabel
                            color: pane.sortCol === hcol.modelData.key
                                   ? Theme.cAccent : Theme.cTextDim
                        }

                        // M46：列间分隔线——平时完全隐藏，鼠标进入表头区
                        // 才淡入（与栏间发丝线同一交互口径）；末列不画。
                        Rectangle {
                            objectName: "hdrDivider"
                            visible: !hcol.isLast
                            width: 1 / Screen.devicePixelRatio
                            height: 14
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.cHairline
                            opacity: (hcol.isLast || !hdrMA.containsMouse)
                                     ? 0 : 0.7
                            Behavior on opacity {
                                NumberAnimation { duration: Theme.durHover; easing.bezierCurve: Theme.easeStandard }
                            }
                        }
                    }
                }
            }

            // ---- 表头统一 MouseArea：拖动 = 相邻让位；点击列内 = 排序 ----
            // （M17/M21/M25 定稿逻辑，逐字保留）
            MouseArea {
                id: hdrMA
                objectName: "fileHeaderMA"
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton

                property int edgeIdx: -1
                property real px0: 0
                property real w0: 0
                property real dLeftPress: 0
                property real w0Right: 0
                property real dRightPress: 0
                property bool resizing: false
                property int pressCol: -1
                property int dragFrom: -1     // M62：列拖动换序
                property int dragTo: -1
                property real docX0: 0

                function edgeAt(x) {
                    var cs = pane.cols()
                    var acc = 0
                    for (var i = 0; i < cs.length - 1; i++) {
                        acc += pane.lw(i)
                        if (pane.lw(i) > 0 && Math.abs(x - acc) <= 4) return i
                    }
                    return -1
                }
                function colAt(x) {
                    var cs = pane.cols()
                    var acc = 0
                    for (var i = 0; i < cs.length; i++) {
                        acc += pane.lw(i)
                        if (x < acc && pane.lw(i) > 0) return i
                    }
                    for (var j = cs.length - 1; j >= 0; j--)
                        if (pane.lw(j) > 0) return j
                    return 0
                }

                cursorShape: (resizing || edgeAt(mouseX) >= 0)
                             ? Qt.SplitHCursor : Qt.ArrowCursor

                onPressed: function(mouse) {
                    if (mouse.button === Qt.RightButton) {
                        pane.openColsMenu(mouse.x, height + 4)
                        return
                    }
                    hdrMA.docX0 = mouse.x
                    hdrMA.dragFrom = -1
                    hdrMA.dragTo = -1
                    var i = hdrMA.edgeAt(mouse.x)
                    if (i < 0) {
                        hdrMA.pressCol = hdrMA.colAt(mouse.x)
                        return
                    }
                    hdrMA.resizing = true
                    hdrMA.edgeIdx = i
                    hdrMA.px0 = mouse.x
                    // M75 修复：拖动前把各可见列的 base 对齐到当前渲染值。
                    // 原实现 w0 取 cw()（不含富余空间分配）、钳制取 lw()（含分配），
                    // 两个基准不一致 -> 拖动量与渲染变化对不上，手感发飘/回弹。
                    // 窗口富余越多偏差越大（100% 缩放比 125% 更明显）。
                    var csD = pane.cols()
                    for (var kD = 0; kD < csD.length; kD++) {
                        var rwD = pane.lw(kD)
                        if (rwD > 0) pane.setCWRaw(kD, rwD)
                    }
                    hdrMA.w0 = pane.lw(i)
                    hdrMA.dLeftPress = pane.lw(i)
                    hdrMA.w0Right = pane.lw(i + 1)
                    hdrMA.dRightPress = pane.lw(i + 1)
                }
                onPositionChanged: function(mouse) {
                    if (!hdrMA.resizing && pressed && hdrMA.pressCol >= 0
                            && viewInfo.inTrash !== true) {
                        if (hdrMA.dragFrom < 0
                                && Math.abs(mouse.x - hdrMA.docX0) > 8)
                            hdrMA.dragFrom = hdrMA.pressCol
                        if (hdrMA.dragFrom >= 0)
                            hdrMA.dragTo = hdrMA.colAt(mouse.x)
                    }
                    if (!hdrMA.resizing) return
                    var dx = mouse.x - hdrMA.px0
                    var lo = -(hdrMA.dLeftPress
                               - pane.colDefs[hdrMA.edgeIdx].min)
                    var hi = hdrMA.dRightPress
                             - pane.colDefs[hdrMA.edgeIdx + 1].min
                    if (hi < lo) hi = lo
                    if (dx < lo) dx = lo
                    if (dx > hi) dx = hi
                    pane.setCWRaw(hdrMA.edgeIdx, hdrMA.w0 + dx)
                    pane.setCWRaw(hdrMA.edgeIdx + 1, hdrMA.w0Right - dx)
                }
                onReleased: function(mouse) {
                    if (!hdrMA.resizing) {
                        if (hdrMA.dragFrom >= 0 && hdrMA.dragTo >= 0
                                && hdrMA.dragFrom !== hdrMA.dragTo) {
                            pane.moveColumn(hdrMA.dragFrom, hdrMA.dragTo)
                            hdrMA.dragFrom = -1
                            hdrMA.dragTo = -1
                            hdrMA.pressCol = -1
                            return
                        }
                        hdrMA.dragFrom = -1
                        hdrMA.dragTo = -1
                        if (hdrMA.pressCol >= 0
                                && pane.cols()[hdrMA.pressCol].key !== "star"
                                && pane.cols()[hdrMA.pressCol].key !== "t_rst") {
                            var r = JSON.parse(
                                controller.sortFiles(pane.cols()[hdrMA.pressCol].key))
                            pane.sortCol = r.col
                            pane.sortDesc = r.desc
                        }
                        hdrMA.pressCol = -1
                        return
                    }
                    controller.resizeColumn(pane.colDefs[hdrMA.edgeIdx].key,
                                            pane.cw(hdrMA.edgeIdx))
                    controller.resizeColumn(
                        pane.colDefs[hdrMA.edgeIdx + 1].key,
                        pane.cw(hdrMA.edgeIdx + 1))
                    hdrMA.resizing = false
                    hdrMA.pressCol = -1
                }
                onCanceled: {
                    hdrMA.resizing = false
                    hdrMA.pressCol = -1
                }
            }
        }

        // ---- 列表本体：行高 48，胶囊选中 + 左条 ----
        ListView {
            id: list
            objectName: "fileList"
            width: parent.width
            // M51：必须同时减掉顶部标题区（pageTitle 64）——之前漏了这一项，
            // 列表比面板高 64px，既把页脚挤出面板（有文件时看不到计数栏），
            // 又让滚动条戳出面板底部圆角。
            // M96：底部那 6px 内缩去掉 —— 它让页脚底边停在离面板底 6px 处，
            // 于是「横线到底边」看起来是 28+6=34，而文字只在 28 里居中，
            // 观感就是文字偏上 3px、底栏偏宽。去掉后页脚直接贴底，
            // 视觉高度 = 页脚高度，文字自然落在中间。
            height: parent.height - pageTitle.height - header.height
                    - footer.height - searchInfo.height
            clip: true
            model: filesModel
            boundsBehavior: Flickable.StopAtBounds
            focus: true

            Keys.onUpPressed: pane.moveBy(-1)
            Keys.onDownPressed: pane.moveBy(1)
            Keys.onPressed: function(e) {
                if (e.key === Qt.Key_Home) { pane.jumpTo(0); e.accepted = true }
                else if (e.key === Qt.Key_End) {
                    pane.jumpTo(filesModel.rowCount() - 1); e.accepted = true
                }
                // M73：↑↓ 原本根本没接线（只处理了 Home/End），
                // 冒烟测试一按 ↓ 就露馅
                else if (e.key === Qt.Key_Down) { pane.moveBy(1); e.accepted = true }
                else if (e.key === Qt.Key_Up) { pane.moveBy(-1); e.accepted = true }
            }
            Keys.onReturnPressed: {
                if (currentIndex >= 0)
                    controller.fileDoubleClicked(filesModel.row_at(currentIndex).fid)
            }

            // M51：上下各留出空间，滑块不再戳进面板底部圆角
            ScrollBar.vertical: ThinScrollBar {
                topPadding: 4
                bottomPadding: 24
            }

            function applyIntents(res) {
                if (res.selected !== undefined) pane.applySelected(res.selected)
            }

            delegate: Item {
                id: rowItem
                width: list.width
                height: 48
                readonly property bool rowSelected:
                    pane.selectedFids.indexOf(model.fid) >= 0

                // hover 底（140ms 淡入）
                Rectangle {
                    x: 8
                    y: 4
                    width: parent.width - 16
                    height: 40
                    radius: 13
                    color: Theme.cRowHover
                    opacity: rowMa.containsMouse && !rowItem.rowSelected
                             && !model.isTrash ? 1 : 0
                    Behavior on opacity {
                        NumberAnimation { duration: Theme.durHover; easing.bezierCurve: Theme.easeStandard }
                    }
                }

                // 选中 = 胶囊（不铺满整行）+ 3×18 左条（§4.3）
                Rectangle {
                    visible: rowItem.rowSelected
                    x: 8
                    y: 4
                    width: parent.width - 16
                    height: 40
                    radius: 13
                    color: Theme.cSelPill
                }
                Rectangle {
                    visible: rowItem.rowSelected
                    x: 8
                    y: 15
                    width: 3
                    height: 18
                    radius: 1.5
                    color: Theme.cSelBar
                }

                // M39：外部文件拖到本行 → 续版本落点高亮（同左树拖入口径：
                // 淡主色底 + 1.5px 主色描边）
                Rectangle {
                    objectName: "fileDropHover"
                    visible: pane.dropHoverFid !== ""
                             && pane.dropHoverFid === model.fid
                    x: 8
                    y: 4
                    width: parent.width - 16
                    height: 40
                    radius: 13
                    color: Theme.cSelPill
                    border.width: 1.5
                    border.color: Theme.cAccent
                }

                // M62：改为绝对定位容器——列顺序可自定义时，
                // Row 的固定声明顺序做不到换列，必须按 key 取 x/宽
                Item {
                    anchors.fill: parent

                    // 文件名（行首 22px 类型图标 + 名称）
                    Item {
                        x: pane.colXk("name")

                        width: pane.colWk("name")
                        height: parent.height
                        FileTypeIcon {
                            x: 12
                            anchors.verticalCenter: parent.verticalCenter
                            kind: model.kind
                            size: 22
                        }
                        Text {
                            x: 44
                            width: parent.width - 44 - 8
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: model.name
                            elide: Text.ElideMiddle
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fsBody
                            font.weight: rowItem.rowSelected ? Font.Medium
                                                             : Font.Normal
                            color: model.isTrash ? Theme.cDanger : Theme.cText
                        }
                    }

                    // ---- M35 §3.2 回收站独立列：原分类 / 删除时间 /
                    //      版本数 / 行内还原胶囊（仅 isTrash 行可见）----
                    // 原分类（行字段 origCat，无分类时"未分类"）
                    Item {
                        x: pane.colX(1)

                        width: pane.lw(1)
                        height: parent.height
                        visible: model.isTrash
                        Text {
                            x: 12
                            width: parent.width - 20
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: model.origCat || "未分类"
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(Theme.fsMeta)
                            color: Theme.cTextDim
                        }
                    }
                    // 删除时间（行字段 delTime + tabular-nums）
                    Item {
                        x: pane.colX(2)

                        width: pane.lw(2)
                        height: parent.height
                        visible: model.isTrash
                        Text {
                            x: 12
                            width: parent.width - 20
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: model.delTime || ""
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(Theme.fsMeta)
                            font.features: { "tnum": 1 }
                            color: Theme.cTextDim
                        }
                    }
                    // 版本数（右对齐 + tabular-nums，对齐方式仿既有 count 格）
                    Item {
                        x: pane.colX(3)

                        width: pane.lw(3)
                        height: parent.height
                        visible: model.isTrash
                        Text {
                            x: 0
                            width: parent.width - 12
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignRight
                            text: model.count
                            elide: Text.ElideRight
                            font.family: Theme.numFamily      // 数字用 Inter
                            font.pointSize: Theme.pt(Theme.fsMeta)
                            font.features: { "tnum": 1 }
                            color: Theme.cText2
                        }
                    }
                    // 文件类型（M35 §3.1：11px 全大写、字距 0.6，
                    // 浅 #475467 / 深 #8C99B4；回收站视图该列让位给原分类）
                    Item {
                        x: pane.colXk("kind")

                        width: pane.colWk("kind")
                        height: parent.height
                        visible: !model.isTrash && pane.colVisible("kind")
                        Text {
                            x: 12
                            width: parent.width - 20
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: String(model.kind || "").toUpperCase()
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                            font.letterSpacing: 0.6
                            color: model.isTrash ? Theme.cDanger : Theme.cTextType
                        }
                    }

                    // 分类 chip
                    // M79：只显示末级分类，前缀「…/」提示还有上级。
                    // 原来直接铺全路径（222/222/222），列宽不够时截成
                    // "222/…" —— 既占地方又什么都没说清。完整路径仍在
                    // 行的悬浮提示里。
                    Item {
                        x: pane.colXk("collection")

                        width: pane.colWk("collection")
                        height: parent.height
                        visible: !model.isTrash && pane.colVisible("collection")
                        // 只取末级名。加「…/」前缀试过——列宽不够时它会
                        // 被截成「…/…」，比不显示还糟。层级关系交给悬浮
                        // 提示里的完整路径。
                        readonly property string catLeaf: {
                            var c = model.category
                            if (!c || c === "—") return "未分类"
                            var parts = String(c).split("/")
                            return parts[parts.length - 1] || c
                        }
                        Rectangle {
                            x: 12
                            anchors.verticalCenter: parent.verticalCenter
                            height: 20
                            radius: Theme.rChip
                            width: Math.min(parent.width - 20, chipTxt.implicitWidth + 20)
                            color: rowItem.rowSelected ? Theme.cChipBgSel
                                                       : Theme.cChipBg
                            Text {
                                id: chipTxt
                                anchors.centerIn: parent
                                text: parent.parent.catLeaf
                                elide: Text.ElideRight
                                width: Math.min(implicitWidth, parent.width - 8)
                                horizontalAlignment: Text.AlignHCenter
                                font.family: Theme.fontFamily
                                font.pointSize: Theme.pt(Theme.fsLabel)
                                color: rowItem.rowSelected ? Theme.cAccent
                                                           : Theme.cText3
                            }
                        }
                    }

                    // 最近版本
                    Item {
                        x: pane.colXk("latest")

                        width: pane.colWk("latest")
                        height: parent.height
                        visible: !model.isTrash && pane.colVisible("latest")
                        Text {
                            x: 12
                            width: parent.width - 20
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: model.latest
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(Theme.fsMeta)
                            font.features: { "tnum": 1 }
                            color: model.isTrash ? Theme.cDanger : Theme.cTextDim
                        }
                    }

                    // 版本数（数值列右对齐 + tabular-nums）
                    Item {
                        x: pane.colXk("count")

                        width: pane.colWk("count")
                        height: parent.height
                        visible: !model.isTrash && pane.colVisible("count")
                        Text {
                            x: 0
                            width: parent.width - 12
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignRight
                            text: model.count
                            elide: Text.ElideRight
                            font.family: Theme.numFamily      // 数字用 Inter
                            font.pointSize: Theme.pt(Theme.fsMeta)
                            font.features: { "tnum": 1 }
                            color: model.isTrash ? Theme.cDanger : Theme.cText2
                        }
                    }

                    // 星标 14×14（仅星标文件显示；M35 §5.1 字符图标→GlyphIcon）
                    Item {
                        x: pane.colXk("star")

                        width: pane.colWk("star")
                        height: parent.height
                        visible: !model.isTrash
                        GlyphIcon {
                            anchors.centerIn: parent
                            name: "star"
                            size: 14
                            iconColor: Theme.cStar
                            visible: model.star === true
                        }
                    }
                }

                // ---- M35 §3.2 行内还原胶囊 46×24（主色浅底）----
                // ⚠️ 层叠实证（QQuickWidget + QTest 真鼠点击 2026-10-18）：
                // QML 的 z 只对同级兄弟生效——胶囊若留在 Row 内，后声明的
                // 整行 rowMa 会盖住整个 Row 子树，点击被吃（规格预见的故障
                // 模式）。故按规格「z:10 必须」的意图提为 rowItem 直接子项
                // （与 rowMa 同级 + z:10），横向仍取 colX(4)+12 的列几何，
                // lw/cw/colX 算法与 Row 泛型列布局均不受影响。
                Rectangle {
                    objectName: "trashRestoreBtn"
                    x: pane.colX(4) + 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 46
                    height: 24
                    radius: 8
                    color: Theme.cAccentBg
                    visible: model.isTrash
                    z: 10
                    Text {
                        anchors.centerIn: parent
                        text: "还原"
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        color: Theme.cAccent
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: controller.collectionMenuAction(
                                       "restore_trash", "",
                                       JSON.stringify([model.fid]))
                    }
                }

                // ---- M40 行内「清除」胶囊 46×24（琥珀底 + 琥珀描边）----
                // 永久删除单条记录（store.purge_trash_item），点击走二次确认；
                // 位置紧贴「还原」右侧，与还原同为 rowItem 直接子项 + z:10
                Rectangle {
                    objectName: "trashPurgeBtn"
                    x: pane.colX(4) + 64
                    anchors.verticalCenter: parent.verticalCenter
                    width: 46
                    height: 24
                    radius: 8
                    color: Theme.cChangeBg
                    border.width: 1
                    border.color: Theme.cChange
                    visible: model.isTrash
                    z: 10
                    Text {
                        anchors.centerIn: parent
                        text: "清除"
                        font.family: Theme.fontFamily
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        color: Theme.cChange
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: controller.purgeTrashItem(model.fid,
                                                            model.name)
                    }
                }

                // B9：行 tooltip（M35 §4.11：换 BubbleTip 深底气泡；
                // 600ms 延迟仍由 tooltipTimer 把关，Timer/tipFlag 逐字保留）
                property bool tipFlag: false
                BubbleTip {
                    show: tipFlag && model.tooltip !== ""
                          && rowMa.containsMouse
                    tip: model.tooltip || ""
                }
                Timer {
                    id: tooltipTimer
                    interval: 600
                    running: rowMa.containsMouse && !rowMa.pressed
                    onTriggered: tipFlag = true
                    onRunningChanged: if (!running && !rowMa.containsMouse)
                                          tipFlag = false
                }

                // ---- 单 MouseArea → controller.fileEvent（B1 口径，逐字保留）----
                MouseArea {
                    id: rowMa
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    property bool dragging: false
                    property bool dragArmed: false
                    property point pressPos

                    onPressed: function(mouse) {
                        list.forceActiveFocus()
                        if (mouse.button === Qt.RightButton) {
                            pane.openMenu(index, model.fid)
                            return
                        }
                        pressPos = Qt.point(mouse.x, mouse.y)
                        dragging = false
                        dragArmed = false
                        // M65：与右栏、与 Windows 习惯一致——
                        // Shift+点击 = 从锚点整段选中；Ctrl+点击 = 单个加/减选
                        var ctrl = (mouse.modifiers & Qt.ControlModifier) !== 0
                        var shift = (mouse.modifiers & Qt.ShiftModifier) !== 0
                        var ev = {
                            op: "press", row: model.fid,
                            x: mouse.x, y: mouse.y,
                            ctrl: ctrl,
                            shift: shift,
                            isTrash: model.isTrash,
                            rowIndex: index,
                            modsAnchor: pane.anchorIndex
                        }
                        list.applyIntents(
                            JSON.parse(controller.fileEvent(JSON.stringify(ev))))
                        controller.setSelection(JSON.stringify(pane.selectedFids))
                        if (!shift)
                            pane.anchorIndex = index
                        list.currentIndex = index
                    }

                    onPositionChanged: function(mouse) {
                        if (!pressed) return
                        if (!dragArmed && !dragging) {
                            if (Math.abs(mouse.x - pressPos.x) < 4
                                    && Math.abs(mouse.y - pressPos.y) < 4) return
                            dragging = true
                            dragArmed = true
                        }
                        var g = mapToGlobal(mouse.x, mouse.y)
                        var w = pane.Window.window
                        if (!w) return
                        var ev = {
                            op: "move", x: mouse.x, y: mouse.y,
                            gx: Math.round(g.x), gy: Math.round(g.y),
                            winX: Math.round(w.x), winY: Math.round(w.y),
                            winW: Math.round(w.width), winH: Math.round(w.height)
                        }
                        var res = JSON.parse(
                            controller.fileEvent(JSON.stringify(ev)))
                        list.applyIntents(res)
                        // M31：跟随图标——界面内显示自绘件；拖出窗口交给 QDrag
                        // ⚠️ res 是 {intents:[...], selected:...} 包装对象，
                        //    数组在 res.intents（初版误把包装当数组遍历→永不显示）
                        var arr = res.intents || []
                        var gOn = false
                        var gCount = 0
                        var gExt = ""
                        for (var gi = 0; gi < arr.length; gi++) {
                            if (arr[gi].op === "internal_drag") {
                                gOn = true
                                gCount = arr[gi].count || 1
                                gExt = arr[gi].ext || ""
                            } else if (arr[gi].op === "external_drag") {
                                gOn = false
                            }
                        }
                        var wp = mapToItem(w.contentItem, mouse.x, mouse.y)
                        pane.dragGhost = gOn ? { count: gCount, ext: gExt,
                                                 x: wp.x, y: wp.y } : null
                        if (dragging && pane.treePane) {
                            var hit = pane.hitTreeRow(
                                Math.round(g.x), Math.round(g.y))
                            if (hit !== pane.overTreeCid) {
                                pane.overTreeCid = hit
                                // M76：换到新的分类就重新计时；离开分类区停表
                                if (hit !== "") hoverExpandTimer.restart()
                                else hoverExpandTimer.stop()
                            }
                            // M32：拖到分类树上→目标行高亮（§6 落点高亮，
                            // cSelPill + cAccent 描边）。fileDropCid 是分类树
                            // 侧的渲染开关，历史遗留从未接线，自此接通。
                            pane.treePane.setFileDrop(hit)
                        }
                    }

                    onReleased: function(mouse) {
                        if (mouse.button !== Qt.LeftButton) return
                        dragArmed = false
                        pane.dragGhost = null
                        if (dragging) {
                            dragging = false
                            hoverExpandTimer.stop()
                            if (pane.overTreeCid !== "") {
                                controller.fileTransfer(
                                    JSON.stringify(pane.selectedFids),
                                    pane.overTreeCid)
                            }
                            pane.overTreeCid = ""
                            if (pane.treePane) pane.treePane.setFileDrop("")
                            controller.fileEvent(JSON.stringify(
                                {op: "dragOutFinished"}))
                            return
                        }
                        list.applyIntents(JSON.parse(
                            controller.fileEvent(JSON.stringify({op: "release"}))))
                        controller.setSelection(JSON.stringify(pane.selectedFids))
                        if (controller.rightCollapsed && pane.selectedFids.length > 0)
                            pane.requestExpandRight()
                    }

                    onDoubleClicked: function(mouse) {
                        if (mouse.button !== Qt.LeftButton) return
                        controller.fileEvent(JSON.stringify({op: "doubleClick"}))
                        controller.fileDoubleClicked(model.fid)
                    }
                    // QDrag 执行期间事件被拖动循环吞掉时的兜底：清高亮
                    onCanceled: {
                        hoverExpandTimer.stop()
                        if (dragging) {
                            dragging = false
                            pane.dragGhost = null
                            pane.overTreeCid = ""
                            if (pane.treePane) pane.treePane.setFileDrop("")
                        }
                    }
                }
            }
        }

        // ---- 页脚：左 计数，右 状态位 ----
        // M47：无文件/有文件都显示 → 常显 + 56→40
        // M94：40→32；M95：32→28；M96：28→24 并去掉列表底部那 6px 内缩。
        // 24 是下限：里面最高的是 13px 转圈，上下各留 5.5px 才不顶边。
        // 页脚现在直接贴面板底，所以「顶线→底边」= 24px，文字垂直居中于其中。
        Rectangle {
            id: footer
            objectName: "paneFooter"
            width: parent.width
            height: 24
            visible: true
            color: "transparent"

            Rectangle {
                width: parent.width
                height: 1
                color: Theme.cBorder
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: pane.totalText()
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsMeta)
                font.features: { "tnum": 1 }
                color: Theme.cTextDim
            }

            // ---- 状态位（M92：原底部状态条并入这里）----
            // 顺手去掉原来的「本地库正常 · 刚刚」——那是写死的装饰文案，
            // 并没有真的检测库状态，属于会骗人的假信息。
            Row {
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.sp6
                // M93：空闲时整行隐藏——既不显示「就绪」占位，也不留 6px 间隙。
                // 页脚右端平时就是空的，有消息才出现。
                visible: pane.statusMsg !== "" || controller.busy

                // 长任务转圈（提交 / 导出），平时不占位
                BusyIndicator {
                    objectName: "busySpinner"
                    width: 13
                    height: 13
                    running: controller.busy
                    visible: controller.busy
                    anchors.verticalCenter: parent.verticalCenter
                }

                Rectangle {
                    width: 6
                    height: 6
                    radius: 3
                    color: pane.statusKind === "ok" ? Theme.cSuccess
                         : pane.statusKind === "err" ? Theme.cDanger
                         : "transparent"
                    visible: pane.statusKind === "ok" || pane.statusKind === "err"
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    id: statusLabel
                    objectName: "statusLabel"
                    text: pane.statusMsg
                    font.family: Theme.fontFamily
                    font.pointSize: Theme.pt(Theme.fsMeta)
                    color: pane.statusKind === "ok" ? Theme.cSuccess
                         : pane.statusKind === "err" ? Theme.cDanger
                         : Theme.cTextMute
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, Math.round(pane.width * 0.5))
                    horizontalAlignment: Text.AlignRight
                }
            }

            // 消息停留 2.6s 后回落；忙的时候继续等，别把「正在提交…」提前收走
            Timer {
                id: statusReset
                interval: 2600
                onTriggered: {
                    if (controller.busy) {
                        statusReset.restart()
                        return
                    }
                    pane.statusMsg = ""
                    pane.statusKind = "dim"
                }
            }
        }
    }

    // M62：把 from 列移到 to 位置（只对正常视图生效）
    function moveColumn(from, to) {
        if (viewInfo.inTrash === true) return
        var cs = cols()
        var keys = []
        for (var i = 0; i < cs.length; i++) keys.push(cs[i].key)
        if (from < 0 || from >= keys.length || to < 0 || to >= keys.length)
            return
        var k = keys.splice(from, 1)[0]
        keys.splice(to, 0, k)
        controller.setFileColumnOrder(JSON.stringify(keys))
    }

    function lastVisibleIndex() {
        var last = -1
        for (var i = 0; i < colDefs.length; i++)
            if (pane.colVisible(colDefs[i].key)) last = i
        return last
    }

    // M61：列显隐浮层——用面板内浮层（z 优先）实现，不用 Popup：
    // Popup 在部分环境下不渲染，且不易与主界面配色同步。
    Item {
        id: colsLayer
        anchors.fill: parent
        visible: false
        z: 80
        property int cardX: 0
        property int cardY: 0

        // 点空白处关闭
        MouseArea {
            anchors.fill: parent
            onClicked: colsLayer.visible = false
        }

        Rectangle {
            id: colsCard
            x: Math.min(Math.max(8, colsLayer.cardX),
                        Math.max(8, parent.width - width - 8))
            y: Math.min(Math.max(8, colsLayer.cardY),
                        Math.max(8, parent.height - height - 8))
            width: 196
            height: colsCol.implicitHeight + 12
            radius: 14
            color: Theme.cFloatBg
            border.width: 1
            border.color: Theme.cFloatBorder
            // 吞掉卡片内的点击，避免穿透到关闭层
            MouseArea { anchors.fill: parent }

            Column {
                id: colsCol
                x: 8
                y: 6
                width: parent.width - 16
                spacing: Theme.sp2

                Repeater {
                    model: pane.colsSpec

                    delegate: Rectangle {
                        id: chk
                        required property var modelData
                        readonly property bool on:
                            pane.colsOnKeys.indexOf(modelData.key) >= 0
                        width: parent.width
                        height: 30
                        radius: 8
                        color: chkMa.containsMouse ? Theme.cRowHover
                                                   : "transparent"

                        Rectangle {
                            x: 6
                            anchors.verticalCenter: parent.verticalCenter
                            width: 16
                            height: 16
                            radius: 4.5
                            color: chk.on ? Theme.cAccent : "transparent"
                            border.width: 1.5
                            border.color: chk.on ? Theme.cAccent
                                                 : Theme.cInputBorder
                            Rectangle {
                                visible: chk.on
                                x: 3.4; y: 8; width: 4; height: 1.6
                                radius: 1; rotation: 45
                                color: Theme.cAccentText
                            }
                            Rectangle {
                                visible: chk.on
                                x: 6; y: 6.9; width: 7; height: 1.6
                                radius: 1; rotation: -45
                                color: Theme.cAccentText
                            }
                        }
                        Text {
                            x: 32
                            anchors.verticalCenter: parent.verticalCenter
                            text: chk.modelData.title
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(12)
                            color: Theme.cText
                        }
                        MouseArea {
                            id: chkMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var k = chk.modelData.key
                                var arr = pane.colsOnKeys.slice()
                                var i = arr.indexOf(k)
                                if (i >= 0) arr.splice(i, 1)
                                else arr.push(k)
                                pane.colsOnKeys = arr
                                controller.setFileColumnVisible(k, i < 0)
                            }
                        }
                    }
                }
            }
        }
    }

    property var colsSpec: []
    property var colsOnKeys: []

    function openColsMenu(px, py) {
        var sp = JSON.parse(controller.fileColumnsSpec())
        var items = [], vis = []
        for (var i = 0; i < sp.length; i++) {
            if (sp[i].key === "star") continue   // 星标固定保留，不在选项里
            items.push(sp[i])
            if (sp[i].visible === true) vis.push(sp[i].key)
        }
        colsSpec = items
        colsOnKeys = vis
        colsLayer.cardX = Math.round(px || 0)
        colsLayer.cardY = Math.round(py || 0)
        colsLayer.visible = true
    }

    function closeColsMenu() { colsLayer.visible = false }

    function moveBy(d) {
        var n = filesModel.rowCount()
        if (n === 0) return
        // M73：currentIndex 属于 ListView，未限定会在函数作用域里
        // ReferenceError（↑↓ 静默失效，End 却能用的原因）
        jumpTo(Math.max(0, Math.min(list.currentIndex + d, n - 1)))
    }

    function jumpTo(i) {
        if (filesModel.rowCount() === 0) return
        // M62：currentIndex 属于 ListView（list），不是根 pane——
        // 未限定名在函数作用域里会 ReferenceError，导致 ↑↓/Home/End 全废
        list.currentIndex = Math.max(0, Math.min(i, filesModel.rowCount() - 1))
        pane.applySelected([filesModel.row_at(list.currentIndex).fid])
        controller.setSelection(JSON.stringify(pane.selectedFids))
        anchorIndex = list.currentIndex
    }

    // ---- 右键菜单（spec 由 controller 逐字生成；V3 §4.8 外观）----
    function openMenu(index, fid) {
        if (pane.selectedFids.indexOf(fid) < 0) {
            pane.applySelected([fid])
            controller.setSelection(JSON.stringify([fid]))
            anchorIndex = index
        }
        var spec = JSON.parse(controller.fileMenuSpec())
        if (spec.trash) {
            // M40：用户反馈「回收站右键弹纯白空白小窗」——原分支只 createObject
            // 却没调 build()（Menu 0 项 → 只剩 240×16 白底空壳），且
            // trashDispatch 未下传菜单项（点了也静默无效）。行内已有
            // 「还原 + 清除」，右键菜单冗余 → 直接不再弹；右键仍会先选中该行。
            return
        }
        var m = dynMenuComp.createObject(pane)
        m.specData = spec
        m.build()
        // M64：关闭后销毁，避免每次右键累积 Menu/MenuItem
        m.closed.connect(function() { Qt.callLater(function() { m.destroy() }) })
        m.popup()
    }

    Component {
        id: dynMenuComp
        Menu {
            id: dynMenu
            property var specData: null
            // M67：显式声明关闭策略——之前点菜单外不关（动态创建的 Menu
            // 没拿到 Window 焦点时，默认策略不生效）
            modal: true
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            // M81：进出场动效。之前 Menu 是"瞬现瞬隐"——右键一按整个菜单
            // 硬切出来，这就是"不丝滑"的第一来源。
            enter: Transition {
                NumberAnimation { property: "opacity"; from: 0; to: 1
                                  duration: Theme.durBase
                                  easing.bezierCurve: Theme.easeDecel }
            }
            exit: Transition {
                NumberAnimation { property: "opacity"; from: 1; to: 0
                                  duration: Theme.durFast
                                  easing.bezierCurve: Theme.easeAccel }
            }
            width: 240
            padding: 8
            background: Rectangle {
                color: Theme.cMenuBg
                border.color: Theme.cBorder
                radius: Theme.rMenu
            }
            function build() {
                while (count > 0) removeItem(itemAt(0))
                var items = specData ? (specData.spec || []) : []
                for (var i = 0; i < items.length; i++) {
                    var it = items[i]
                    if (it.sep) {
                        dynMenu.addItem(fileSepComp.createObject(dynMenu))
                        continue
                    }
                    var mi = fileItemComp.createObject(dynMenu)
                    mi.itemData = it
                    mi.menuRef = dynMenu
                    dynMenu.addItem(mi)
                }
            }
        }
    }

    component FileMenuSep: Item {
        height: 9
        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 16
            height: 1
            color: Theme.cBorder
        }
    }

    component FileMenuItem: MenuItem {
        id: mi
        property var itemData: null
        property var menuRef: null
        // M63：后端给了 state=disabled（如「已是最早版本」），此前只做灰色
        // 文字却仍可点，点下去什么也不发生
        enabled: !(itemData && itemData.state === "disabled")
        height: 32
        contentItem: Text {
            leftPadding: 8
            rightPadding: 8
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: mi.itemData ? mi.itemData.label
                  + (mi.itemData.accel ? "   " + mi.itemData.accel : "") : ""
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsBody
            font.weight: mi.highlighted ? Font.Medium : Font.Normal
            color: (mi.itemData && !mi.enabled) ? Theme.cMenuDis
                 : (mi.itemData && mi.itemData.danger) ? Theme.cMenuDanger
                 : mi.highlighted ? Theme.cAccent : Theme.cMenuFg
        }
        background: Rectangle {
            color: mi.highlighted ? Theme.cMenuHover : "transparent"
            radius: 8
        }
        onTriggered: {
            if (mi.itemData && mi.menuRef) {
                // M64：trashDispatch 是已删除的死属性，此分支永远不可达
                controller.fileMenuAction(
                    mi.itemData.key,
                    JSON.stringify(mi.menuRef.specData.fids))
            }
        }
    }

    Component { id: fileSepComp; FileMenuSep {} }
    Component { id: fileItemComp; FileMenuItem {} }

    // ---- 空态（§4.10：整块居中，上 1/3 处偏下）----
    Rectangle {
        id: emptyBox
        visible: false
        radius: Theme.rPanel
        color: Theme.cEmptyBg
        border.width: 1
        border.color: Theme.cBorder
        width: Math.min(520, pane.width - 80)
        height: emptyCol.implicitHeight + 64
        x: (parent.width - width) / 2
        y: (parent.height - height) * 0.38
        z: 3

        Column {
            id: emptyCol
            anchors.centerIn: parent
            spacing: 0
            width: parent.width - 64

            Item {
                width: parent.width
                height: 108
                Rectangle {
                    anchors.centerIn: parent
                    width: 72
                    height: 72
                    radius: 22
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Theme.cAccent2 }
                        GradientStop { position: 1.0; color: Theme.cAccent }
                    }
                    // 白纸 + 折角
                    Rectangle {
                        anchors.centerIn: parent
                        width: 30
                        height: 38
                        radius: 5
                        color: "#FFFFFF"
                        Rectangle {
                            x: 7
                            y: 9
                            width: 3
                            height: 20
                            radius: 1.5
                            color: Theme.cAqua
                        }
                        Rectangle {
                            x: 14
                            y: 11
                            width: 10
                            height: 2.5
                            radius: 1.2
                            color: "#C9D6FF"
                        }
                        Rectangle {
                            x: 14
                            y: 18
                            width: 8
                            height: 2.5
                            radius: 1.2
                            color: "#C9D6FF"
                        }
                    }
                }
            }

            Text {
                id: emptyTitle
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                font.family: Theme.fontFamily
                font.pixelSize: 16
                font.weight: Font.DemiBold
                color: Theme.cText
            }
            Item { width: 1; height: 16 }
            Text {
                id: emptySub
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                font.family: Theme.fontFamily
                font.pixelSize: 12
                // M35 §3.4：空态说明行高 1.5（12px → 18px 固定行高；
                // 规格书写的 Text.FixedLineHeight 在本环境 Qt 不存在，
                // 枚举正确名为 Text.FixedHeight，语义一致）
                lineHeight: 18
                lineHeightMode: Text.FixedHeight
                color: Theme.cTextDim
                wrapMode: Text.Wrap
            }
            Item { width: 1; height: 20 }
            AppButton {
                id: commitBtn
                text: "提交第一个版本"
                primary: true
                visible: false
                width: 132
                height: 38
                anchors.horizontalCenter: parent.horizontalCenter
                onClicked: controller.openCommitDialog()
            }
            AppButton {
                id: clearBtn
                text: "清空搜索"
                visible: false
                width: 132
                height: 38
                anchors.horizontalCenter: parent.horizontalCenter
                onClicked: {
                    controller.clearSearchToPlaceholder()
                    pane.clearSearchRequested()
                }
            }
            Item { width: 1; height: 20 }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                // M35 §3.3：仅库空态显示；搜索空态/回收站空态不出现错语文案
                visible: pane.viewInfo.emptyState === "library"
                text: "支持 Word / Excel / PPT / PDF / 图片 / 压缩包，单个文件最大 2 GB"
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsMeta)
                color: Theme.cTextMute
                elide: Text.ElideRight
            }
        }
    }
}
