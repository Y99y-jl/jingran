import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import ".."
import "../components"

// 右栏检查器（M29 · UI 规格 V3 §4.4）。
// 结构：文件头 → 版本历史 + 对比 → 当前版本白卡 / 时间线 → 查看全部入口。
// ⚠️ 列宽再分配（cw/setCW/lw/colX）与星标/diff 入口、拖出、右键菜单全部保留。
Rectangle {
    id: pane
    objectName: "rightPane"
    color: Theme.cPanelInsp
    radius: Theme.rPanel
    clip: true
    antialiasing: true

    property string sortCol: "time"
    property bool sortDesc: true
    property var selectedVids: []
    // M85：版本拖到界面内的落点由 Main.qml 转给 fileListPane 判定
    // M86：右栏展开时内容从右侧滑入（B 方案：动内容不动布局）
    property real slideX: 0
    signal dragMoved(real gx, real gy)
    signal dragDropped()
    // M78：拖拽跟随卡片（窗口坐标 + 数量）。版本区在窗口内没有合法落点，
    // 但拖拽必须有"抓住了"的即时反馈，否则界面像卡住了。
    // 真正跨出窗口后交给 QDrag 的系统拖影，此件由 internalDragStarted 清空。
    property var verGhost: null
    // M36：文件头星标的目标版本 = 选中版本（无选中回落最新）——
    // 旧实现恒点 latestRow()，选中旧版本点星标却给最新版本标星（BUG）。
    // starOn 是图标状态的最新快照（绑定链不跟踪 row_at()，故在
    // refreshFromController / selectedVids 变化时显式刷新）。
    property bool starOn: false
    // M82：当前展示的文件 id（用于判断"换文件了"→ 触发淡入）
    property string lastFid: ""

    function starTargetVid() {
        if (selectedVids.length > 0) {
            var want = selectedVids[0]
            for (var i = 0; i < verModel.rowCount(); i++) {
                var r = verModel.row_at(i)
                if (r && r.vid === want) return want
            }
        }
        var lr = latestRow()
        return lr ? (lr.vid || "") : ""
    }

    function refreshStar() {
        var vid = starTargetVid()
        for (var i = 0; i < verModel.rowCount(); i++) {
            var r = verModel.row_at(i)
            if (r && r.vid === vid) { starOn = (r.star === true); return }
        }
        starOn = (pane.info.star === true)
    }
    property string emptyState: "nofile"
    property string detailText: ""
    property var info: ({})

    // ---- 列宽系统（M21/M25 定稿，勿改）：版本 / 时间 / 星标三列几何 ----
    // 新设计不再画表头，但这套再分配仍用于行内 vN/时间/星标的横向几何，
    // 保证「同款列宽算法」与旧行为一字不差。
    property var colDefs: [
        {key: "ver",  title: "版本", def: 64, min: 32, stretch: false},
        {key: "time", title: "时间", def: 96, min: 48, stretch: true},
        {key: "star", title: "星标", def: 56, min: 28, stretch: false}
    ]
    property var colW: ({})
    function cw(i) { return pane.colW[pane.colDefs[i].key] || pane.colDefs[i].def }
    function setCW(i, w) {
        var c = Object.assign({}, pane.colW)
        c[pane.colDefs[i].key] = Math.max(pane.colDefs[i].min, Math.round(w))
        pane.colW = c
    }
    function lw(i) {
        var avail = pane.width - 22
        var bases = [], st = []
        var total = 0
        for (var k = 0; k < colDefs.length; k++) {
            bases[k] = cw(k)
            total += bases[k]
            if (colDefs[k].stretch) st.push(k)
        }
        var extra = avail - total
        if (extra > 0 && st.length > 0) {
            var each0 = Math.floor(extra / st.length)
            var rem = extra - each0 * st.length
            for (k = 0; k < st.length; k++)
                bases[st[k]] += each0 + (k < rem ? 1 : 0)
        } else if (extra < 0) {
            var d = []
            var sumD = 0
            for (k = 0; k < colDefs.length; k++) {
                d[k] = Math.max(bases[k], colDefs[k].min)
                sumD += d[k]
            }
            var deficit = sumD - avail
            var guard = 0
            while (deficit > 0.01 && guard < 10) {
                guard++
                var act = []
                for (k = 0; k < colDefs.length; k++)
                    if (colDefs[k].stretch && d[k] - colDefs[k].min > 0.01)
                        act.push(k)
                if (act.length === 0) break
                var each = deficit / act.length
                for (k = 0; k < act.length; k++) {
                    var j = act[k]
                    var dec = Math.min(each, d[j] - colDefs[j].min)
                    d[j] -= dec
                    deficit -= dec
                }
            }
            if (deficit > 0.01) {
                var s = 0
                for (k = 0; k < colDefs.length; k++) s += d[k]
                if (s > 0.01) {
                    var ratio = (s - deficit) / s
                    for (k = 0; k < colDefs.length; k++)
                        d[k] = Math.max(8, d[k] * ratio)
                }
            }
            for (k = 0; k < colDefs.length; k++) bases[k] = d[k]
        }
        return Math.round(Math.max(8, bases[i]))
    }
    function colX(i) {
        var a = 22
        for (var k = 0; k < i; k++) a += lw(k)
        return a
    }

    function fmtSize(n) {
        if (!n || n <= 0) return "—"
        if (n >= 1024 * 1024 * 1024)
            return (n / 1024 / 1024 / 1024).toFixed(1) + " GB"
        if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB"
        if (n >= 1024) return Math.round(n / 1024) + " KB"
        return n + " B"
    }

    function latestRow() {
        for (var i = 0; i < verModel.rowCount(); i++) {
            var r = verModel.row_at(i)
            if (r && r.isLatest) return r
        }
        return verModel.rowCount() > 0 ? verModel.row_at(0) : ({})
    }

    function refreshFromController() {
        var es = JSON.parse(controller.verEmptyState())
        sortCol = es.sortCol
        sortDesc = es.sortDesc
        emptyState = es.state
        selectedVids = JSON.parse(controller.selectedVersionVids())
        info = JSON.parse(controller.currentFileInfo())
        pane.refreshStar()
        // M82：换文件时版本区原来是硬切。给列表一个很轻的淡入
        // （0.4 → 1，160ms），既交代"内容换了"，又不会拖慢操作。
        if (info && info.fid !== undefined && String(info.fid) !== lastFid) {
            var first = (lastFid === "")     // 首次加载不做动画（list 可能还没建）
            lastFid = String(info.fid)
            if (!first) verFade.restart()
        }
    }

    Component.onCompleted: refreshFromController()

    // M36：选中变化（行点击 press / applyVids / moveBy）都要刷星标图标
    onSelectedVidsChanged: pane.refreshStar()

    Connections {
        target: controller
        function onVerChanged() { pane.refreshFromController() }
        function onDetailChanged(text) { detailText = text }
        function onFilesChanged() { pane.refreshFromController() }
    }

    function applyVids(vids) {
        selectedVids = vids
        controller.setVersionSelection(JSON.stringify(vids))
    }

    Column {
        anchors.fill: parent
        spacing: 0
        transform: Translate { x: pane.slideX }

        // ================= 文件头 90 =================
        Item {
            width: parent.width
            height: 90

            FileTypeIcon {
                id: headIcon
                x: 16
                y: 16
                size: 44
                kind: pane.info.ext || ""
            }

            Text {
                id: headName
                x: 72
                y: 14
                width: parent.width - 72 - 16 - 64
                text: pane.info.name || ""
                elide: Text.ElideMiddle
                wrapMode: Text.Wrap
                maximumLineCount: 2
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(13.5)
                font.weight: Font.DemiBold
                color: Theme.cText
            }

            Text {
                x: 72
                y: 52
                width: parent.width - 72 - 16 - 64
                text: (pane.info.ext ? String(pane.info.ext).toUpperCase() : "—")
                      + " · " + pane.fmtSize(pane.info.size || 0)
                      + " · " + (pane.info.count || 0) + " 个版本"
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsLabel)
                font.features: { "tnum": 1 }
                color: Theme.cTextDim
            }

            // 星标 / 更多（各 26×26 圆角 9）
            // M35 §5.2：未选中文件（emptyState === "nofile"）时隐藏，
            // 只动按钮本体，文件头其余内容保持
            Item {
                x: parent.width - 16 - 56 - 6
                y: 14
                width: 26
                height: 26
                visible: pane.emptyState !== "nofile"
                Rectangle {
                    anchors.fill: parent
                    radius: 9
                    color: starMa.containsMouse ? Theme.cRowHover : "transparent"
                }
                GlyphIcon {
                    anchors.centerIn: parent
                    // M36：图标跟随「星标目标版本」（选中优先，最新兜底）
                    name: pane.starOn ? "star" : "starOff"
                    size: 14
                    iconColor: pane.starOn ? Theme.cStar : Theme.cTextDim
                }
                MouseArea {
                    id: starMa
                    objectName: "verStarBtn"
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        // M36：点哪个版本的星标，就标/取消哪个版本
                        // （旧实现恒取 latestRow()——选中旧版本时标错人）
                        var vid = pane.starTargetVid()
                        if (vid) controller.toggleStar(vid)
                    }
                }
            }
            Item {
                x: parent.width - 16 - 26
                y: 14
                width: 26
                height: 26
                visible: pane.emptyState !== "nofile"
                Rectangle {
                    anchors.fill: parent
                    radius: 9
                    color: moreMa.containsMouse ? Theme.cRowHover : "transparent"
                }
                GlyphIcon {
                    anchors.centerIn: parent
                    name: "dots"
                    size: 14
                    iconColor: Theme.cTextDim
                }
                MouseArea {
                    id: moreMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        var r = pane.latestRow()
                        var vid = pane.selectedVids.length > 0 ? pane.selectedVids[0]
                                                              : (r.vid || "")
                        if (vid) pane.openMenu(vid)
                    }
                }
            }
        }

        // ================= 版本历史 + 对比 =================
        Item {
            width: parent.width
            height: 34
            Text {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "版本历史"
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsSection)
                font.weight: Font.DemiBold
                color: Theme.cText
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                // M35 §5.2：未选中文件时「对比」不可点（「版本历史」标题不动）
                visible: pane.emptyState !== "nofile"
                text: "对比"
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsMeta)
                color: cmpMa.containsMouse ? Theme.cAccentHover : Theme.cAccent
                MouseArea {
                    id: cmpMa
                    anchors.fill: parent
                    anchors.margins: -6
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (pane.selectedVids.length === 2) {
                            controller.diffRequest(pane.selectedVids[0],
                                                   pane.selectedVids[1])
                        } else {
                            // M33：info=状态栏可见（dim 会被隐藏=点击无反应）
                            controller.status("请先在下方选中两个版本再对比",
                                              "info")
                        }
                    }
                }
            }
        }

        // ================= 版本列表 =================
        ListView {
            id: list
            objectName: "verList"
            width: parent.width
            height: parent.height - 90 - 34
            clip: true
            model: verModel
            boundsBehavior: Flickable.StopAtBounds
            focus: true

            Keys.onUpPressed: pane.moveBy(-1)
            Keys.onDownPressed: pane.moveBy(1)
            Keys.onPressed: function(e) {
                if (e.key === Qt.Key_Home) {
                    var r1 = JSON.parse(controller.verJump("first"))
                    if (r1.vid) pane.applyVids([r1.vid])
                    currentIndex = 0
                    e.accepted = true
                } else if (e.key === Qt.Key_End) {
                    var r2 = JSON.parse(controller.verJump("last"))
                    if (r2.vid) pane.applyVids([r2.vid])
                    currentIndex = verModel.rowCount() - 1
                    e.accepted = true
                } else if (e.key === Qt.Key_Return && currentIndex >= 0) {
                    controller.versionEvent(JSON.stringify(
                        {op: "doubleClick", vid: verModel.row_at(currentIndex).vid}))
                    e.accepted = true
                }
            }

            ScrollBar.vertical: ThinScrollBar {}

            delegate: Item {
                id: vrow
                width: list.width
                // M37：卡片高亮跟「选中」走（选中几个就几张卡，多选同样式）——
                // 旧实现恒跟 isLatest，导致选中其他版本时看不出选中了谁
                height: rowSelected ? 96 : 78
                readonly property bool rowSelected:
                    pane.selectedVids.indexOf(model.vid) >= 0

                // ---- hover（140ms）----
                Rectangle {
                    z: -1
                    x: 8
                    width: parent.width - 16
                    height: vrow.height - 8
                    radius: 13
                    color: Theme.cRowHover
                    // 卡片行自带底色，不再叠 hover
                    opacity: rowMa.containsMouse && !rowSelected ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: Theme.durHover
                                              easing.bezierCurve: Theme.easeStandard } }
                }

                // 单层柔影（§2.6：只允许一层；作为兄弟项垫在卡片下方）
                Rectangle {
                    visible: rowSelected
                    x: 22
                    y: 14
                    width: parent.width - 44
                    height: 74
                    radius: 16
                    color: "#140F1C46"
                }

                // ================= 选中版本：白色小卡 =================
                Rectangle {
                    visible: rowSelected
                    x: 16
                    y: 8
                    width: parent.width - 32
                    height: 74
                    radius: 16
                    color: Theme.cCardSelBg
                    border.width: 1
                    border.color: Theme.cCardSelBorder

                    // 主色环 16 + 实心点 4
                    Rectangle {
                        x: 14
                        y: 16
                        width: 16
                        height: 16
                        radius: 8
                        color: "transparent"
                        border.width: 2
                        border.color: Theme.cAccent
                        Rectangle {
                            anchors.centerIn: parent
                            width: 4
                            height: 4
                            radius: 2
                            color: Theme.cAccent
                        }
                    }
                    Text {
                        id: curVer
                        x: 40
                        y: 14
                        text: model.vNo
                        font.family: Theme.fontFamily
                        font.pointSize: Theme.pt(12.5)
                        font.weight: Font.DemiBold
                        color: Theme.cAccent
                    }
                    Rectangle {
                        // 「当前」只属于真最新版本——M37 起卡片跟选中走，
                        // 选中旧版本时卡片照显但不挂「当前」章
                        visible: model.isLatest === true
                        x: 40 + curVer.implicitWidth + 8
                        y: 14
                        width: 36
                        height: 18
                        radius: 9
                        color: Theme.cSuccessBg
                        Text {
                            anchors.centerIn: parent
                            text: "当前"
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(Theme.fsNano)
                            font.weight: Font.DemiBold
                            color: Theme.cSuccess
                        }
                    }
                    // M51：两行观感不佳 → 恢复单行；全文靠悬停气泡
                    Text {
                        x: 40
                        y: 38
                        width: parent.width - 40 - 44
                        text: model.chip
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        font.weight: Font.Medium
                        color: Theme.cText
                    }
                    Text {
                        x: 40
                        y: 56
                        text: model.timeDisplay
                        font.family: Theme.fontFamily
                        // M101：日期单独留在 12 —— 卡片宽度固定、y 也是死值，
                        // 跟到 13 会贴到卡片下沿（用户实测反馈）
                        font.pointSize: Theme.pt(12)
                        font.features: { "tnum": 1 }
                        color: Theme.cTextDim
                    }
                }

                // ================= 未选中版本：竖轨 + 描边环 =================
                Item {
                    visible: !rowSelected
                    anchors.fill: parent

                    // 竖轨 1.5px
                    Rectangle {
                        x: 23
                        y: 0
                        width: 1.5
                        height: parent.height
                        color: Theme.cHairline
                    }
                    // 节点 10×10 白底 2px 描边环
                    Rectangle {
                        x: 19
                        y: 20
                        width: 10
                        height: 10
                        radius: 5
                        color: Theme.cNodeBg
                        border.width: 2
                        border.color: vrow.rowSelected ? Theme.cAccent
                                                       : Theme.cHairline
                    }
                    Text {
                        x: 44
                        y: 14
                        text: model.vNo
                        font.family: Theme.fontFamily
                        font.pointSize: Theme.pt(12.5)
                        font.weight: Font.DemiBold
                        color: Theme.cText2
                    }
                    Text {
                        x: 44
                        y: 34
                        width: parent.width - 44 - 34
                        text: model.chip
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        color: Theme.cText3
                    }
                    Text {
                        x: 44
                        y: 52
                        text: model.timeDisplay
                        font.family: Theme.fontFamily
                        // M101：日期单独留在 12 —— 卡片宽度固定、y 也是死值，
                        // 跟到 13 会贴到卡片下沿（用户实测反馈）
                        font.pointSize: Theme.pt(12)
                        font.features: { "tnum": 1 }
                        color: Theme.cTextDim
                    }
                }

                // 星标（仅星标版本显示，最右，独立热区）
                Item {
                    visible: model.star === true
                    x: parent.width - 16 - 20
                    // M37：星标纵向位置跟卡片走（卡片 56 / 普通行 48）
                    y: rowSelected ? 56 : 48
                    width: 20
                    height: 20
                    z: 1
                    GlyphIcon {
                        anchors.centerIn: parent
                        name: "star"
                        size: 13
                        iconColor: Theme.cStar
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: controller.toggleStar(model.vid)
                    }
                }

                // ---- 整行交互（选中 / 右键 / 拖出 / 双击）----
                MouseArea {
                    id: rowMa
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    // 拖动中用"抓住"光标：只表示手里有东西，不暗示这里能放
                    cursorShape: dragging ? Qt.ClosedHandCursor
                                          : Qt.PointingHandCursor
                    property bool dragging: false
                    property point pressPos
                    onPressed: function(mouse) {
                        list.focus = true
                        if (mouse.button === Qt.RightButton) {
                            pane.openMenu(model.vid)
                            return
                        }
                        pressPos = Qt.point(mouse.x, mouse.y)
                        var res = JSON.parse(controller.versionEvent(JSON.stringify({
                            op: "press", vid: model.vid,
                            x: mouse.x, y: mouse.y,
                            ctrl: (mouse.modifiers & Qt.ControlModifier) !== 0,
                            shift: (mouse.modifiers & Qt.ShiftModifier) !== 0
                        })))
                        pane.selectedVids = res.selected
                        list.currentIndex = index
                    }
                    onPositionChanged: function(mouse) {
                        if (!pressed || !(mouse.buttons & Qt.LeftButton)) return
                        if (!dragging) {
                            if (Math.abs(mouse.x - pressPos.x) < 4
                                    && Math.abs(mouse.y - pressPos.y) < 4) return
                            dragging = true
                        }
                        var w = pane.Window.window
                        // M78：窗口内就有跟随卡片——拖拽的即时反馈是 affordance，
                        // 不是"操作结果"。版本区在窗口内确实没有落点，但用户按
                        // 下拖动的意图通常就是"把它拖到桌面"，先有反馈才不会以为
                        // 界面卡住了。跨出窗口后由系统拖影接手。
                        if (w) {
                            var wp = mapToItem(w.contentItem, mouse.x, mouse.y)
                            pane.verGhost = {
                                count: Math.max(1, pane.selectedVids.length),
                                x: wp.x, y: wp.y
                            }
                        }
                        var g = mapToGlobal(mouse.x, mouse.y)
                        pane.dragMoved(g.x, g.y)
                        controller.versionDragEvent(JSON.stringify({
                            op: "move", x: mouse.x, y: mouse.y,
                            gx: Math.round(g.x), gy: Math.round(g.y),
                            winX: Math.round(w.x), winY: Math.round(w.y),
                            winW: Math.round(w.width), winH: Math.round(w.height)
                        }))
                    }
                    onReleased: function(mouse) {
                        if (mouse.button !== Qt.LeftButton) return
                        var wasDragging = dragging
                        dragging = false
                        pane.verGhost = null
                        controller.versionEvent(JSON.stringify({op: "release"}))
                        // M85：真的拖过才结算落点；单击松手不触发
                        if (wasDragging) pane.dragDropped()
                    }
                    onDoubleClicked: function(mouse) {
                        if (mouse.button !== Qt.LeftButton) return
                        // 星标热区双击无操作
                        if (mouseX > pane.width - 36) return
                        controller.versionEvent(JSON.stringify(
                            {op: "doubleClick", vid: model.vid}))
                    }
                    // 拖拽被系统取消时的兜底，别让卡片留在屏幕上
                    onCanceled: {
                        dragging = false
                        pane.verGhost = null
                    }
                }

                // M35 §4.11：换 BubbleTip 深底气泡（600ms 延迟由 verTip 把关）
                // ⚠️ Timer.active 在本环境 Qt 不存在（实测 meta props 只有
                // interval/running/repeat/triggeredOnStart）→ active 恒
                // undefined，show 绑定收到 undefined 气泡永不显示。改药
                // FileListPane 同款 tipFlag：Timer.onTriggered 置位。
                property bool verTipFlag: false
                BubbleTip { show: verTipFlag && model.tooltip !== "" && rowMa.containsMouse; tip: model.tooltip || "" }
                Timer {
                    id: verTip
                    interval: 600
                    running: rowMa.containsMouse && !rowMa.pressed
                    onTriggered: verTipFlag = true
                    onRunningChanged: if (!running && !rowMa.containsMouse)
                                          verTipFlag = false
                }
            }
        }

        // M94：这里原来有个「查看全部 N 个版本 →」入口（44px 高），点下去只是
        // list.positionViewAtEnd() —— 版本列表本来就全量加载且可滚动，不存在
        // 「没显示出来的部分」，所以文案是假的；End 键已有同一能力且更好
        // （会选中最早一版）；版本少时列表滚不动，点了完全没反应。
        // 删掉后这 44px 归还给列表，能多显示一行版本。
    }

    // ---- 空态（居中式提示，保留三态文案）----
    Rectangle {
        visible: emptyState !== "none"
        // M35 §5.2：空态上移到面板 1/3 处（水平仍居中；
        // 三态文案、宽 260/高 96/字号全部不动）
        anchors.horizontalCenter: parent.horizontalCenter
        y: (parent.height - height) / 3
        width: Math.min(260, pane.width - 56)
        height: 96
        radius: 16
        color: Theme.cSubtleBg
        Text {
            anchors.centerIn: parent
            width: parent.width - 32
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pointSize: Theme.pt(Theme.fsMeta)
            lineHeight: 1.3
            color: Theme.cTextDim
            text: emptyState === "nofile"
                  ? "在上方文件列表选择一个文件，\n这里显示它的版本历史"
                  : "该文件还没有任何版本\n（或没有符合当前筛选的版本）"
        }
    }

    function moveBy(d) {
        var n = verModel.rowCount()
        if (n === 0) return
        // M62：同 FileListPane——currentIndex 属于 ListView
        list.currentIndex = Math.max(0,
            Math.min(list.currentIndex + d, n - 1))
        applyVids([verModel.row_at(list.currentIndex).vid])
    }

    // ---- 右键菜单（C10 口径；V3 §4.8 外观）----
    function openMenu(vid) {
        if (selectedVids.indexOf(vid) < 0) {
            applyVids([vid])
        }
        var spec = JSON.parse(controller.versionMenuSpec(vid))
        var m = verMenuComp.createObject(pane)
        m.specData = spec
        m.build()
        // M64：菜单关闭后销毁——原实现每次右键都 new 一个 Menu + 全部
        // MenuItem 并永久挂在 pane 下，长会话持续累积
        m.closed.connect(function() { Qt.callLater(function() { m.destroy() }) })
        m.popup()
    }

    component VerMenuSep: Item {
        height: 9
        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 16
            height: 1
            color: Theme.cBorder
        }
    }

    component VerMenuItem: MenuItem {
        id: vmi
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
            text: vmi.itemData ? vmi.itemData.label : ""
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsBody
            color: (vmi.itemData && !vmi.enabled) ? Theme.cMenuDis
                 : (vmi.itemData && vmi.itemData.danger) ? Theme.cMenuDanger
                 : vmi.highlighted ? Theme.cAccent : Theme.cMenuFg
        }
        background: Rectangle {
            color: vmi.highlighted ? Theme.cMenuHover : "transparent"
            radius: 8
        }
        onTriggered: {
            // M33：versionMenuAction 是 (key, spec) 双参 slot——
            // 曾只传 1 参导致 TypeError 整个菜单「点击无反应」。
            // vid 取菜单打开时锁定的目标版本（specData.vid，openMenu 口径）。
            if (vmi.itemData && vmi.itemData.key && vmi.menuRef) {
                controller.versionMenuAction(
                    vmi.itemData.key,
                    JSON.stringify({
                        vid: vmi.menuRef.specData.vid || "",
                        vidA: vmi.itemData.vidA || "",
                        vidB: vmi.itemData.vidB || ""
                    }))
            }
        }
    }

    Component {
        id: verMenuComp
        Menu {
            id: vmenu
            property var specData: null
            // M67：点菜单外必须关闭（动态创建时默认策略不生效）
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
                var items = specData ? (specData.actions || []) : []
                for (var i = 0; i < items.length; i++) {
                    var it = items[i]
                    if (it.sep) {
                        vmenu.addItem(verSepComp.createObject(vmenu))
                        continue
                    }
                    var mi = verItemComp.createObject(vmenu)
                    mi.itemData = it
                    mi.menuRef = vmenu
                    vmenu.addItem(mi)
                }
            }
        }
    }

    Component { id: verSepComp; VerMenuSep {} }
    // M82：换文件时的淡入（0.4 → 1，160ms 减速）
    NumberAnimation {
        id: verFade
        target: list
        property: "opacity"
        from: 0.4
        to: 1.0
        duration: Theme.durBase
        easing.bezierCurve: Theme.easeDecel
    }

    Component { id: verItemComp; VerMenuItem {} }
}
