import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import ".."
import "../components"

// 左栏分类树（M29 · UI 规格 V3 §4.2）。
// 事件链不变：行 MouseArea → controller.treePress/treeEvent；
// 双击改名、右键 5 项、拖入归类全部保留。
// ⚠️ 只改外观与分组呈现；树数据仍来自 categoriesModel（含零高度的内置行）。
Rectangle {
    id: pane
    objectName: "leftPane"
    color: Theme.cPanelSide
    radius: Theme.rPanel
    clip: true
    antialiasing: true

    signal requestNewCollection(string parentCid)

    property string selectedCid: "__all__"
    property string editingCid: ""
    property string dropMode: ""
    property string dropRef: ""
    property string fileDropCid: ""
    // M77：分类区内拖动时的跟随卡片（null = 不显示）
    property var catGhost: null
    property alias listViewRef: list

    function refreshFromController() {
        selectedCid = controller.selectedCollectionCid()
        var es = JSON.parse(controller.colEditState())
        editingCid = es.editing || ""
    }

    Component.onCompleted: {
        winHandle = Window.window          // M75-fix：提前解析，避免首帧竞态
        refreshFromController()
    }

    Connections {
        target: controller
        function onCatsChanged() { refreshFromController(); pane.revealPending() }
        // M32：拖出链路任何终止路径（QDrag 结束/物化失败等）都发此信号，
        // 顺带清落点高亮——防止异常终止后高亮残留（run2 实测案例）。
        function onDragOutFinished() { pane.setFileDrop("") }
        // M75-2：拖分类出窗口结束（系统拖放返回后）——顺带清可能的残留高亮
        function onCollectionDragOutFinished() { pane.setFileDrop("") }
    }

    // M33：新建分类后滚动到新行（生产 on_new_collection 的 see(cid) 口径——
    // 树默认折叠 + 新行追加在末尾，不滚动则用户 perceive 成「点击没反应」）。
    function revealPending() {
        var rc = controller.takeRevealCid()
        if (rc) {
            var i = categoriesModel.index_of_cid(rc)
            if (i >= 0) list.positionViewAtIndex(i, ListView.Contain)
        }
    }

    function setFileDrop(cid) { fileDropCid = cid }

    // ===== M75-fix：窗口外判定（拖分类出窗口 = 导出为文件夹）=====
    // 事故：原实现直接读 `rowMa.Window.window`，而本文件没有
    // `import QtQuick.Window`，该附加属性恒为 undefined →
    // `!!winRef` 永远 false → outOfWindow 永远 false。后果有两个：
    //   ① 拖到窗口外松手不走导出，而是把分类"移动"到落点算出来的
    //      边缘那一行（用户看到的"不管拖到哪都显示拖到同一项"）；
    //   ② 越界后落点高亮一直挂着，视觉上像卡住。
    // 现在：窗口句柄在根部解析一次并缓存；坐标以场景坐标（contentItem）
    // 为准，留 2px 余量避免贴边抖动。
    property var winHandle: null

    function resolveWin() {
        if (!winHandle) winHandle = Window.window
        return winHandle
    }

    function pointOutsideWindow(item, px, py) {
        var w = resolveWin()
        if (!w || !item) return false      // 取不到窗口就不判越界（保守）
        var p = item.mapToItem(null, px, py)
        var m = 2
        return p.x < -m || p.y < -m || p.x > w.width + m || p.y > w.height + m
    }

    // M57：拖拽落点必须按「指针下的行」算——旧实现把被拖行自己的
    // cid 当落点传下去，后端永远解析成"拖到自己"，所以毫无反应。
    // 行高固定 38（delegate）；内置行（全部/未分类）不渲染、高度 0，
    // 所以视觉行号 = 模型行号 - 它之前的可见行数。
    readonly property int rowH: 38

    function dropInfoFromList(pt) {
        // M62：indexAt 需要 contentItem 坐标（滚动后补 contentY）
        var cy = pt.y + list.contentY
        var idx = list.indexAt(0, cy)
        var cid = ""
        var off = 0.5
        if (idx >= 0) {
            var r = categoriesModel.row_at(idx)
            if (r && r.cid) {
                cid = r.cid
                var hiddenBefore = 0
                for (var k = 0; k < idx; k++) {
                    var rk = categoriesModel.row_at(k)
                    if (rk && rk.isBuiltin === true)
                        hiddenBefore++
                }
                off = (cy - (idx - hiddenBefore) * rowH) / rowH
            }
        }
        return {cid: cid, x: pt.x, y: pt.y,
                off: Math.max(0.01, Math.min(0.99, off))}
    }

    function rowOf(cid) {
        for (var i = 0; i < categoriesModel.rowCount(); i++) {
            var r = categoriesModel.row_at(i)
            if (r && r.cid === cid) return r
        }
        return ({})
    }

    // 当前选中的用户分类（"项目分类 +" 用它当父节点）
    function currentUserCid() {
        var r = rowOf(selectedCid)
        return (r && r.isBuiltin !== true) ? selectedCid : ""
    }

    function newCollection(parentCid) {
        controller.collectionMenuAction("new", parentCid || "", "")
    }

    // ================= 分组标题 + 新建 =================
    component GroupLabel: Item {
        id: gl
        property string label: ""
        property string plusTip: ""
        signal plusClicked()
        height: 40

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            text: gl.label
            font.family: Theme.fontFamily
            // M36→M37→M38：用户三轮反馈「还是有些小」——分组标签
            // 9.5→10.5→11.5→13（fsBody，规格书标准 10 已三倍超出）
            font.pointSize: Theme.pt(Theme.fsBody)
            font.weight: Font.DemiBold
            font.letterSpacing: 1.2
            color: Theme.cTextDim
        }

        Rectangle {
            id: plus
            visible: gl.plusTip !== ""
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 22
            height: 22
            radius: 7
            color: plusMa.containsMouse ? Theme.cAccentBg : "transparent"
            // M35 §5.1：字符「＋」→ GlyphIcon 矢量 plus
            GlyphIcon {
                anchors.centerIn: parent
                name: "plus"
                size: 14
                iconColor: plusMa.containsMouse ? Theme.cAccent : Theme.cTextDim
            }
            MouseArea {
                id: plusMa
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: gl.plusClicked()
            }
        }
    }

    // ================= 导航项（38 / 圆角 13 / 白胶囊 + 左条）=================
    component NavRow: Item {
        id: nav
        property string cid: ""
        property string label: ""
        property string glyph: ""
        property int count: 0
        property bool isSelected: false
        signal activated()
        signal menuRequested(var mouse)

        width: parent ? parent.width : 0
        height: 38

        Rectangle {
            visible: nav.isSelected
            x: 10
            y: 7
            width: parent.width - 20
            height: 28
            radius: 12
            color: "#0C0F1C46"
        }
        Rectangle {
            visible: nav.isSelected
            x: 8
            y: 3
            width: parent.width - 16
            height: 32
            radius: 13
            color: Theme.cNavSelBg
            border.width: 1
            border.color: Theme.cNavSelBorder
        }
        Rectangle {
            visible: nav.isSelected
            x: 8
            y: 12
            width: 3
            height: 14
            radius: 1.5
            color: Theme.cSelBar
        }

        // M35 §5.1：glyph 字符 → GlyphIcon 矢量（▤=list、◇=diamond，
        // 空 glyph 自动隐藏；glyph 属性与两处赋值保持原样，只改绘制）
        GlyphIcon {
            x: 16
            anchors.verticalCenter: parent.verticalCenter
            size: 14
            name: nav.glyph === "▤" ? "list" : (nav.glyph === "◇" ? "diamond" : "")
            iconColor: nav.isSelected ? Theme.cAccent : Theme.cTextDim
        }
        Text {
            x: 38
            width: parent.width - 38 - 70
            anchors.verticalCenter: parent.verticalCenter
            text: nav.label
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsBody
            font.weight: nav.isSelected ? Font.DemiBold : Font.Normal
            color: nav.isSelected ? Theme.cAccent : Theme.cText2
        }

        // 计数胶囊 46×20，右对齐（距右 12）
        Rectangle {
            visible: nav.count > 0
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 46
            height: 20
            radius: 100
            color: Theme.cAccentBg
            Text {
                anchors.centerIn: parent
                text: nav.count
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsLabel)
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                color: Theme.cAccent
            }
        }

        // M42：悬停底色与选中胶囊同几何（旧实现整行铺满无圆角，深色下
        // 看起来像一块突兀的方灰块——与树行同一处修复）
        Rectangle {
            objectName: "navRowHover"
            z: -1
            x: 8
            y: 3
            width: parent.width - 16
            height: 32
            radius: 13
            color: Theme.cRowHover
            opacity: navMa.containsMouse && !nav.isSelected ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.durHover
                                              easing.bezierCurve: Theme.easeStandard } }
        }

        MouseArea {
            id: navMa
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.PointingHandCursor
            onClicked: nav.activated()
            onPressed: function(mouse) {
                if (mouse.button === Qt.RightButton)
                    nav.menuRequested(mouse)
            }
        }
    }

    Column {
        anchors.fill: parent
        spacing: 0

        // M34：用户反馈「＋出现了两次，有两个入口，有点多」——撤掉「分类」行的＋，
        // 仅保留「项目分类」行的＋。新建一级分类入口不受影响：
        //   ① 「项目分类」行的＋在未选中用户分类时自动退化为「新建一级分类」；
        //   ② 右键菜单（collectionMenuSpec on_collection_menu 三分支）本就有
        //      「新建一级分类 / 新建子分类」两项。
        GroupLabel {
            width: parent.width
            label: "分类"
        }

        NavRow {
            width: parent.width
            cid: "__all__"
            label: "全部文件"
            glyph: "▤"
            count: pane.rowOf("__all__").count || 0
            isSelected: pane.selectedCid === "__all__"
            onActivated: {
                controller.treePress("__all__")
                pane.refreshFromController()
            }
            onMenuRequested: function(mouse) { pane.openMenu("__all__", mouse) }
        }
        NavRow {
            width: parent.width
            cid: "__unfiled__"
            label: "未分类"
            glyph: "◇"
            count: pane.rowOf("__unfiled__").count || 0
            isSelected: pane.selectedCid === "__unfiled__"
            onActivated: {
                controller.treePress("__unfiled__")
                pane.refreshFromController()
            }
            onMenuRequested: function(mouse) { pane.openMenu("__unfiled__", mouse) }
        }

        GroupLabel {
            width: parent.width
            label: "项目分类"
            plusTip: "新建子分类"
            onPlusClicked: pane.newCollection(pane.currentUserCid())
        }

        // ================= 用户分类树（可滚动）=================
        ListView {
            id: list
            objectName: "catTree"
            width: parent.width
            // M36：库信息卡删除后，固定项 = 分组×2(80) + 导航×2(76)
            // + 回收站(38) = 194；末尾 16 为原有底部呼吸位，逐字保留
            // M94 曾去掉这 16px 去对齐中栏页脚，实测观感更差（回收站贴死底边），
            // 用户要求回退 → 恢复呼吸位。两处文字因此差约 16px，这是**有意保留**
            // 的错位：左栏底部需要呼吸，中栏页脚是状态条、本来就该贴底。
            height: parent.height - 40 * 2 - 38 * 2 - 38 - 16
            clip: true
            model: categoriesModel
            boundsBehavior: Flickable.StopAtBounds
            cacheBuffer: 600

            // ===== M81：展开/收起的"丝滑" =====
            // 原来展开时子行是瞬时插进来的（模型 sync_rows 后直接重排），
            // 视觉上就是"啪"一下多出几行 —— 这是第二个不丝滑的来源。
            // add/remove 只做透明度，displaced 让下面的行平滑让位：
            // 两者叠加才像"展开"，只做其中一个会显得突兀。
            add: Transition {
                NumberAnimation { property: "opacity"; from: 0; to: 1
                                  duration: Theme.durFast
                                  easing.bezierCurve: Theme.easeDecel }
            }
            remove: Transition {
                NumberAnimation { property: "opacity"; from: 1; to: 0
                                  duration: Theme.durFast
                                  easing.bezierCurve: Theme.easeAccel }
            }
            displaced: Transition {
                NumberAnimation { property: "y"
                                  duration: Theme.durBase
                                  easing.bezierCurve: Theme.easeStandard }
            }
            onContentYChanged: repositionTimer.restart()

            ScrollBar.vertical: ThinScrollBar {}

            Timer {
                id: repositionTimer
                interval: 30
                onTriggered: {
                    if (pane.editingCid !== "") {
                        var i = categoriesModel.index_of_cid(pane.editingCid)
                        if (i >= 0) list.positionViewAtIndex(i, ListView.Contain)
                    }
                }
            }

            delegate: Item {
                id: row
                // 内置行（全部/未分类/回收站）不在此处渲染——已固定在上下两端
                visible: model.isBuiltin !== true
                width: list.width
                height: visible ? 38 : 0

                readonly property bool rowSelected: pane.selectedCid === model.cid
                readonly property bool rowEditing: pane.editingCid === model.cid
                readonly property bool dropInto: pane.dropMode === "into"
                                                 && pane.dropRef === model.cid
                readonly property int indent: 12 + model.depth * 16
                property bool dropHighlight: false

                // M42：用户反馈深色模式「鼠标位置一块方灰块很突兀」——
                // 旧实现 anchors.fill 铺满整行且无圆角，与选中胶囊（内缩 8px、
                // r13）形状不一致，悬停时像一块浮起来的色块。改为同款胶囊几何。
                Rectangle {
                    objectName: "catRowHover"
                    z: -1
                    x: 8
                    y: 3
                    width: parent.width - 16
                    height: 32
                    radius: 13
                    color: Theme.cRowHover
                    opacity: rowMa.containsMouse && !row.rowSelected ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: Theme.durHover
                                              easing.bezierCurve: Theme.easeStandard } }
                }
                // M37：用户反馈「双击重命名时选中淡框与重命名深框交叉」——
                // 重命名进行中隐藏选中框与左竖条，只留重命名输入框
                Rectangle {
                    objectName: "catRowSelBox"
                    visible: row.rowSelected && !row.rowEditing
                    x: 8
                    y: 3
                    width: parent.width - 16
                    height: 32
                    radius: 13
                    color: Theme.cNavSelBg
                    border.width: 1
                    border.color: Theme.cNavSelBorder
                }
                Rectangle {
                    visible: row.rowSelected && !row.rowEditing
                    x: 8
                    y: 12
                    width: 3
                    height: 14
                    radius: 1.5
                    color: Theme.cSelBar
                }
                // 拖入悬停 / 拖拽落点高亮（§6：整行 #EBF0FF + 1.5px 主色描边）
                Rectangle {
                    visible: row.dropInto || row.dropHighlight
                             || pane.fileDropCid === model.cid
                    x: 8
                    y: 3
                    width: parent.width - 16
                    height: 32
                    radius: 13
                    color: Theme.cSelPill
                    border.width: 1.5
                    border.color: Theme.cAccent
                }

                // 插入线（before / after / end）
                Rectangle {
                    visible: pane.dropRef === model.cid && pane.dropMode === "before"
                    anchors.top: parent.top
                    x: 16
                    width: parent.width - 32
                    height: 2
                    radius: 1
                    color: Theme.cAccent
                }
                Rectangle {
                    visible: pane.dropRef === model.cid && pane.dropMode === "after"
                    anchors.bottom: parent.bottom
                    x: 16
                    width: parent.width - 32
                    height: 2
                    radius: 1
                    color: Theme.cAccent
                }

                Item {
                    x: row.indent
                    width: parent.width - x
                    height: parent.height

                    // 展开三角（M76：26px 宽、整行高的点击区 + 13px 字形）
                    // 单击行不再展开/收起，开合只认这里。
                    // M76-2：**不再画悬停底色块**——26px 宽的块比选中胶囊的
                    // 左边缘（x:8）更靠左，会把胶囊的圆角框线顶出来，看起来
                    // 像"按钮挡住了框"。点击区仍保持 26×整行（够好点），
                    // 反馈只靠三角本身变色。
                    Item {
                        id: caret
                        width: 26
                        height: parent.height
                        visible: model.hasChildren

                        Text {
                            anchors.centerIn: parent
                            text: model.open ? "▾" : "▸"
                            font.pixelSize: 13
                            color: caretMa.containsMouse ? Theme.cAccent
                                                         : Theme.cTextDim
                        }
                        MouseArea {
                            id: caretMa
                            anchors.fill: parent
                            z: 1
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: controller.treeToggle(model.cid)
                        }
                    }

                    // 行主体：单击选中/开合、拖候选；双击重命名
                    MouseArea {
                        id: rowMa
                        x: 26
                        width: parent.width - x
                        height: parent.height
                        hoverEnabled: true
                        // M83：不设这个，按住拖动时外层 ListView（Flickable）
                        // 会在移动超过阈值后把鼠标抢走变成"滚动列表"——
                        // 表现就是"有时拖不动分类，只在滚"。分类名长时更容易
                        // 被察觉，因为用户会在行上横向找位置再拖。
                        preventStealing: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        cursorShape: outOfWindow ? Qt.DragCopyCursor
                                 : (row.dragging ? Qt.ClosedHandCursor
                                                 : Qt.ArrowCursor)
                        property bool dragging: false
                        property bool outOfWindow: false
                        property bool suppressRelease: false
                        property point pressPos

                        onPositionChanged: function(mouse) {
                            // M32 自愈：无按键悬停时若落点高亮还挂着（拖拽
                            // 异常终止残留），立即清除。拖拽中 buttons 含
                            // 左键 → 不受影响（不能用 pressed：文件行拖拽
                            // 时本行并非按下态）。
                            if ((mouse.buttons & Qt.LeftButton) === 0
                                    && pane.fileDropCid !== "")
                                pane.setFileDrop("")
                            // M77 自愈：无按键悬停时清掉可能残留的跟随卡片
                            if ((mouse.buttons & Qt.LeftButton) === 0
                                    && pane.catGhost !== null)
                                pane.catGhost = null
                            // M57：只认 pressed（按住期间恒为真）——
                            // 不用 mouse.button/buttons：前者在 move 里是
                            // NoButton，后者在部分输入路径上也会缺位。
                            if (!pressed) return
                            if (!dragging) {
                                if (Math.abs(mouse.x - pressPos.x) < 4
                                        && Math.abs(mouse.y - pressPos.y) < 4) return
                                dragging = true
                            }
                            // M77：跟随卡片（用户要求分类区内拖动也有拖影）。
                            // 坐标换算到 pane 系，右下方偏移 14/8，避免压住落点。
                            var gp = rowMa.mapToItem(pane, mouse.x, mouse.y)
                            pane.catGhost = { name: model.name || "",
                                              x: gp.x + 14, y: gp.y + 8 }
                            // M75-2：一越界就切到系统拖放——拖影跟手，
                            // 而且落到哪就复制到哪（不再弹「选目录」框）。
                            // 这一步会阻塞到用户松手（QDrag.exec 模态），
                            // 返回后鼠标已经抬起，所以这里直接收尾。
                            var outside = pane.pointOutsideWindow(
                                                rowMa, mouse.x, mouse.y)
                            if (outside) {
                                pane.dropMode = ""
                                pane.dropRef = ""
                                pane.catGhost = null      // 交给系统拖影
                                dragging = false
                                outOfWindow = false
                                suppressRelease = true
                                controller.startCollectionDragOut(model.cid)
                                return
                            }
                            var pt = rowMa.mapToItem(list, mouse.x, mouse.y)
                            var info = pane.dropInfoFromList(pt)
                            info.op = "move"
                            var res = JSON.parse(
                                controller.treeEvent(JSON.stringify(info)))
                            var ind = res.intents.length
                                    ? res.intents[res.intents.length - 1] : null
                            if (ind && ind.op === "indicator") {
                                pane.dropMode = ind.mode
                                pane.dropRef = ind.ref || ""
                            }
                        }
                        onReleased: function(mouse) {
                            if (mouse.button !== Qt.LeftButton) return
                            pane.catGhost = null
                            // M75-2：越界时已切成系统拖放（QDrag.exec 阻塞到
                            // 松手），这条 release 是拖放结束后补发的。若不拦，
                            // 会拿鼠标当前位置算内部落点 → 把分类误移到某行。
                            if (suppressRelease) {
                                suppressRelease = false
                                dragging = false
                                outOfWindow = false
                                return
                            }
                            // 兜底：甩得太快、没触发 positionChanged 时，松手处
                            // 再判一次越界，走「选目录」路径（不阻塞界面）。
                            if (dragging
                                    && pane.pointOutsideWindow(rowMa, mouse.x,
                                                               mouse.y)) {
                                dragging = false
                                outOfWindow = false
                                pane.dropMode = ""
                                pane.dropRef = ""
                                controller.exportCollectionAsFolder(model.cid)
                                return
                            }
                            outOfWindow = false
                            // M72：无论是否拖动都要发 release —— 开合已从
                            // press 延后到 release 结算（未拖动才展开/收起）
                            var pt2 = rowMa.mapToItem(list, mouse.x, mouse.y)
                            var info2 = pane.dropInfoFromList(pt2)
                            info2.op = "release"
                            controller.treeEvent(JSON.stringify(info2))
                            dragging = false
                            pane.refreshFromController()
                            pane.dropMode = ""
                            pane.dropRef = ""
                        }
                        onDoubleClicked: function(mouse) {
                            if (mouse.button !== Qt.LeftButton) return
                            var res = JSON.parse(controller.treeEvent(
                                JSON.stringify({op: "doubleClick", cid: model.cid})))
                            pane.refreshFromController()
                        }
                        onPressed: function(mouse) {
                            if (mouse.button === Qt.RightButton) {
                                pane.openMenu(model.cid, mouse)
                                return
                            }
                            pressPos = Qt.point(mouse.x, mouse.y)
                            dragging = false
                            controller.treePress(model.cid)
                            pane.refreshFromController()
                        }
                    }

                    Text {
                        x: 26
                        width: parent.width - 26 - 64
                        height: parent.height
                        verticalAlignment: Text.AlignVCenter
                        text: model.name
                        elide: Text.ElideRight
                        // M38：用户反馈「重命名不双框了，但有两层字」——
                        // 重命名 TextField anchors.fill 盖在同一槽位，编辑中
                        // 隐藏本标签，只留输入框一层字
                        visible: !row.rowEditing
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fsBody
                        font.weight: row.rowSelected ? Font.DemiBold : Font.Normal
                        color: row.rowSelected ? Theme.cAccent : Theme.cText2
                    }

                    // 计数胶囊
                    // M79：0 也显示（灰色空心），否则空分类那一格是"缺一块"，
                    // 整列的纵向节奏会断。有文件才用主色实心。
                    Rectangle {
                        readonly property int cnt: model.count || 0
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: 46
                        height: 20
                        radius: 100
                        color: cnt > 0 ? Theme.cAccentBg : "transparent"
                        Text {
                            anchors.centerIn: parent
                            text: parent.cnt
                            font.family: Theme.numFamily      // 数字用 Inter
                            font.pointSize: Theme.pt(Theme.fsLabel)
                            font.weight: Font.DemiBold
                            font.features: { "tnum": 1 }
                            color: parent.cnt > 0 ? Theme.cAccent : Theme.cTextMute
                        }
                    }

                    // 内联重命名（D3 口径：失焦提交，空串放弃）
                    TextField {
                        id: renameBox
                        objectName: "catRenameBox"
                        visible: row.rowEditing
                        anchors.fill: parent
                        anchors.rightMargin: 8
                        height: 36
                        // M75-6：文字起点必须与常态一致。常态 Text 是 x:16，
                        // 而这里是 anchors.fill（从 0 起）+ 默认 6 的内边距，
                        // 于是编辑态的字比常态靠左 10px——用户看到的就是
                        // 「改名时字离左边小三角更近」。
                        leftPadding: 26
                        rightPadding: 8
                        text: controller.collectionName(model.cid)
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fsBody
                        selectByMouse: true
                        color: Theme.cText
                        background: Rectangle {
                            color: Theme.cInputBg
                            border.color: Theme.cAccent
                            border.width: 1.5
                            radius: Theme.rInput
                        }
                        Component.onCompleted: if (row.rowEditing) {
                            forceActiveFocus(); selectAll()
                        }
                        onVisibleChanged: if (visible) { forceActiveFocus(); selectAll() }
                        Keys.onEscapePressed: {
                            controller.cancelRename()
                            pane.refreshFromController()
                        }
                        onAccepted: {
                            var r = JSON.parse(controller.commitRename(text))
                            if (r.keepEditing) {
                                selectAll()
                            } else {
                                pane.refreshFromController()
                            }
                        }
                        onActiveFocusChanged: {
                            if (!activeFocus && visible && row.rowEditing
                                    && text !== "") {
                                var r = JSON.parse(controller.commitRename(text))
                                pane.refreshFromController()
                            }
                        }
                    }
                }
            }
        }

        // M36：产品要求整卡删除「本地版本库」小卡片（导出备份入口
        // 在「设置」内已有，见 controller.open_export_backup_dialog）；
        // 高度公式已同步归还 92 + 8 间距 = 100px 给分类树列表

        // ================= 回收站（常驻底部，不用红底）=================
        Item {
            width: parent.width
            height: 38
            Rectangle {
                visible: pane.selectedCid === "__trash__"
                x: 8
                y: 3
                width: parent.width - 16
                height: 32
                radius: 13
                color: Theme.cNavSelBg
                border.width: 1
                border.color: Theme.cNavSelBorder
            }
            Text {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "♲"
                font.pixelSize: 12
                color: trashMa.containsMouse || pane.selectedCid === "__trash__"
                       ? Theme.cDanger : Theme.cTextDim
            }
            Text {
                x: 38
                width: parent.width - 38 - 70
                anchors.verticalCenter: parent.verticalCenter
                text: "回收站"
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fsBody
                color: trashMa.containsMouse || pane.selectedCid === "__trash__"
                       ? Theme.cDanger : Theme.cText2
            }
            Rectangle {
                visible: (pane.rowOf("__trash__").count || 0) > 0
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                width: 46
                height: 20
                radius: 100
                color: Theme.cAccentBg
                Text {
                    anchors.centerIn: parent
                    text: pane.rowOf("__trash__").count || 0
                    font.family: Theme.fontFamily
                    font.pointSize: Theme.pt(Theme.fsLabel)
                    font.weight: Font.DemiBold
                    color: Theme.cAccent
                }
            }
            MouseArea {
                id: trashMa
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    controller.treePress("__trash__")
                    pane.refreshFromController()
                }
                onPressed: function(mouse) {
                    if (mouse.button === Qt.RightButton)
                        pane.openMenu("__trash__", mouse)
                }
            }
        }
    }

    // ---- 右键菜单（生产 on_collection_menu 三分支；V3 §4.8 外观）----
    function openMenu(cid, mouse) {
        var spec = JSON.parse(controller.collectionMenuSpec(cid))
        if (spec.actions.length === 0) return
        var m = catMenuComp.createObject(pane)
        m.specData = spec
        m.build()
        // M64：菜单关闭后销毁——原实现每次右键都 new 一个 Menu + 全部
        // MenuItem 并永久挂在 pane 下，长会话持续累积
        m.closed.connect(function() { Qt.callLater(function() { m.destroy() }) })
        m.popup()
    }

    component CatMenuSep: Item {
        height: 9
        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 16
            height: 1
            color: Theme.cBorder
        }
    }

    component CatMenuItem: MenuItem {
        id: cmi
        property var itemData: null
        property var menuRef: null
        height: 32
        contentItem: Text {
            leftPadding: 8
            rightPadding: 8
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: cmi.itemData ? cmi.itemData.label
                  + (cmi.itemData.accel ? "   " + cmi.itemData.accel : "") : ""
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fsBody
            color: (cmi.itemData && !cmi.enabled) ? Theme.cMenuDis
                 : (cmi.itemData && cmi.itemData.danger) ? Theme.cMenuDanger
                 : cmi.highlighted ? Theme.cAccent : Theme.cMenuFg
        }
        background: Rectangle {
            color: cmi.highlighted ? Theme.cMenuHover : "transparent"
            radius: 8
        }
        onTriggered: {
            if (cmi.itemData && cmi.itemData.key && cmi.menuRef)
                controller.collectionMenuAction(
                    cmi.itemData.key, cmi.itemData.arg || "",
                    JSON.stringify(cmi.menuRef.specData.fids || []))
        }
    }

    // ===== M77：分类区内拖动的跟随卡片 =====
    // 用户要求「分类在分类区里拖动时也要有拖影」。这里用 QML 自绘（不是
    // QDrag）：窗口内拖动要同时保留落点高亮/插入线，系统拖放会把事件吞掉。
    // 一旦越过窗口边界，catGhost 立即置空，改由 QDrag 自带拖影接管。
    //
    // M77-2 外观（用户反馈"太大、有点丑"）：从 186×34 收到自适应宽度
    // （78–148）× 26，字号 12、圆角 7。宽度靠 TextMetrics 量文本自然宽度，
    // 不能用父宽度算（会形成绑定循环）。只显示分类名，不加副标题与计数
    // —— 拖拽过程中信息越少越安静。
    TextMetrics {
        id: catGhostMetrics
        font.family: Theme.fontFamily
        font.pixelSize: 12
        text: pane.catGhost ? pane.catGhost.name : ""
    }

    Rectangle {
        id: catGhostCard
        visible: pane.catGhost !== null
        z: 5000
        width: Math.min(148, Math.max(78, catGhostMetrics.width + 20))
        height: 26
        radius: 7
        color: Theme.cAccent
        opacity: 0.94
        x: pane.catGhost
           ? Math.max(2, Math.min(pane.catGhost.x, pane.width - width - 2))
           : 0
        y: pane.catGhost
           ? Math.max(2, Math.min(pane.catGhost.y, pane.height - height - 2))
           : 0

        Text {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignLeft
            text: pane.catGhost ? pane.catGhost.name : ""
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: 12
            color: "#FFFFFF"
        }
    }

    Component {
        id: catMenuComp
        Menu {
            id: catMenu
            property var specData: null
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
                        catMenu.addItem(catSepComp.createObject(catMenu))
                        continue
                    }
                    var mi = catItemComp.createObject(catMenu)
                    mi.itemData = it
                    mi.menuRef = catMenu
                    catMenu.addItem(mi)
                }
            }
        }
    }

    Component { id: catSepComp; CatMenuSep {} }
    Component { id: catItemComp; CatMenuItem {} }
}
