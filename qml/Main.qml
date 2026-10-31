import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "components"
import "panes"

// ============================================================================
// M29 · UI 规格书 V3 主窗（§3 布局 / §4.1 顶栏 / §4.2-§4.4 三栏 / §2.7 玻璃）
// 铁律不变：数据路径、列宽算法、弹窗流、右栏收纳语义、手柄拖拽语义一行不动。
// ============================================================================
ApplicationWindow {
    id: root
    width: 1280
    // §3：启动尺寸钳制——旧版 1047 > 工作区 1030，底部被任务栏遮 17px。
    // Windows 的 availableGeometry 是**外框**口径，QWindow.height 是客户区，
    // 需再扣非客户区（本机 125% DPI 实测 ≈38 逻辑px），否则仍被任务栏吃一截。
    // offscreen 平台没有 Screen，兜底 864 逻辑高（1080 物理 @125%）。
    height: {
        // M65：minimumHeight=760，原先 600 的下限分支不可达 → 直接夹在 760~900
        var ah = Screen.availableGeometry ? Screen.availableGeometry.height : 0
        if (ah <= 400) return 778
        return Math.max(760, Math.min(900, ah - 48 - 38))
    }
    minimumWidth: 1180
    minimumHeight: 760
    visible: true
    title: "井然"
    color: Theme.cBg

    // ---- 状态（controller 为真相，QML 只镜像）----
    property bool collapsed: false
    // M60：版本栏宽度必须夹在窄区间——用户遇到「展开后特别宽」，
    // 是历史 sash 把宽度记成了大值。默认取最窄，上限 420。
    property int rightMinW: 250      // M83：与后端 RIGHT_DEFAULT_W / SASH_MIN_R 对齐
    property int rightMaxW: 420
    property int lastRightW: 280
    property int rightW: 250         // M83：默认就是最窄（用户要求）
    property bool restoring: true
    property int totalW: splitView.width
    property int fileTotal: 0

    // M97：拖动开始时的左栏宽度快照，用来判断用户拖的是哪根分隔条。
    // 拖左/中分隔条会改变左栏宽度；拖中/右分隔条不会。
    property real _dragCatW: -1

    function geomString() {
        return Math.round(root.width) + "x" + Math.round(root.height)
               + "+" + Math.round(root.x) + "+" + Math.round(root.y)
    }

    // 旧版工具栏图标（ICON_ASSETS 同源 PNG）。必须用 Qt.resolvedUrl 在
    // Main.qml 基准下解析成绝对 URL，否则 Image 会以组件所在目录为基准。
    function iconUrl(name, px) {
        var t = Theme.mode === "dark" ? "dark" : "light"
        var s = px || 28
        return Qt.resolvedUrl("../resources/icons/" + name + "_" + t + "_" + s + ".png")
    }

    function refreshTotal() {
        // M53：左上角始终是「库内总数」，不随回收站/搜索视图变
        fileTotal = controller.libraryTotal
    }

    function applyCollapsed(c, animate) {
        if (c === collapsed) return
        if (c) lastRightW = Math.max(rightMinW,
                                     Math.min(rightMaxW,
                                              Math.round(verPane.width)))
        collapsed = c
        // 收纳 = 隐藏该栏（SplitView 对隐藏项不参与布局）；
        // 包装层与 pane 同时隐藏（门禁/探针读 pane.visible）。
        verWrap.visible = !c
        verPane.visible = !c
        // M82：原来这里先把 rightW 直接赋成目标值、再启动动画，
        // 等于「从终点动到终点」——动画一直在跑但什么都看不见。
        // 展开时先把宽度归 0 再动画过去；收起按 Material 的规则
        // 直接消失（退场本来就该更快，不做拖沓的收缩）。
        if (animate && !c) {
            // 展开：宽度一次给终值（只重排 1 次），内容从右侧滑入并淡入
            rightW = lastRightW
            verPane.slideX = 24
            verPane.opacity = 0
            verSlideAnim.to = 0
            verSlideAnim.start()
            verFadeAnim.to = 1
            verFadeAnim.start()
        } else {
            // 收起 / 无动画：宽度瞬时，内容归位，不做拖沓的收缩
            rightW = c ? 0 : lastRightW
            verPane.slideX = 0
            verPane.opacity = 1
        }
    }

    // §3：宽屏兜底保留（minimumWidth 1180 下正常不会触发；OS 强压窄时仍生效）

    // ---- M6：F 组弹窗宿主 ----
    DialogHost { id: dialogHost }

    Connections {
        target: controller
        function onDialogRequested(specJson) {
            dialogHost.openSpec(JSON.parse(specJson))
        }
        function onEditSaveAsk(askJson) {
            controller.onEditSaveAsk(askJson)
        }
        function onCloseRejected(pendingJson) {
            controller.onCloseRejected(pendingJson)
        }
        function onThemeChanged(mode) {
            Theme.mode = mode
        }
        function onFilesChanged() { root.refreshTotal() }
    }

    // K1：Ctrl+F / Ctrl+K 聚焦搜索；F5 刷新；K3 F2 分派；K4 Esc 两级
    Shortcut {
        sequences: ["Ctrl+F", "Ctrl+K"]
        onActivated: search.forceActiveFocus()
    }
    Shortcut { sequence: "F5"; onActivated: controller.refresh() }
    Shortcut { sequence: "F1"; onActivated: controller.openCommitDialog() }
    Shortcut {
        sequence: "F2"
        onActivated: {
            if (JSON.parse(controller.colEditState()).editing) return
            controller.hotkeyF2(
                catPane.listViewRef.activeFocus ? "tree" : "files")
        }
    }
    Shortcut {
        sequence: "Esc"
        onActivated: {
            if (dialogHost.visible) { dialogHost.submit("cancel"); return }
            if (JSON.parse(controller.colEditState()).editing) {
                controller.cancelRename()
                return
            }
            if (search.text !== "") {
                controller.clearSearchToPlaceholder()
                return
            }
            controller.clearSelection()
        }
    }

    // ---- E3：拖入提交 ----
    // M39：拖到具体文件行 → 为该文件续版本（极小确认窗）；拖到空白 → 原有
    // 「提交新版本」。落点判定靠 fileListPane 的行命中（不做逐行 DropArea，
    // 避免与行内拖拽手势/多 DropArea 抢事件冲突）。
    DropArea {
        id: dragArea
        anchors.fill: parent

        // ===== M77：内部拖拽（拖出窗口后又拖回来）=====
        // 关键：拖出后走的是 QDrag，此时 QML 的 MouseArea 收不到事件，
        // 只有这个窗口级 DropArea 还能收到系统派发的拖动事件。
        // 必须和「外部文件拖入」彻底分开——否则拖回来会被当成新文件、
        // 直接提交一个新版本（1.1.18 实测就是这个现象）。
        function _internalGhost(drag) {
            var gp = dragArea.mapToGlobal(drag.x, drag.y)
            var cid = fileListPane.hitTreeRow(gp.x, gp.y)
            if (catPane) catPane.setFileDrop(cid)
            // ⚠️ 这里刻意**不再画自绘卡片**。
            // 拖出窗口后那张跟手的图是 Windows OLE 拖放子系统画的，
            // 一旦开始就无法中途撤掉（Qt 没有接口）。所以只能让
            // controller 里生成的那张系统位图和 QML 的自绘卡片**同款
            // 同位置**（尺寸/圆角/字号/偏移都对齐），越过边界时看起来
            // 就是同一个东西。再叠一张自绘的，反而会变成两个。
            if (catPane) catPane.catGhost = null
            fileListPane.dragGhost = null
            drag.accept()
        }
        function _clearInternalGhost() {
            if (catPane) { catPane.catGhost = null; catPane.setFileDrop("") }
            fileListPane.dragGhost = null
            if (verPane) verPane.verGhost = null
        }

        onEntered: function(drag) {
            if (controller.isInternalDrag()) { dragArea._internalGhost(drag); return }
            controller.dropProbe("entered")
        }
        onPositionChanged: function(drag) {
            if (controller.isInternalDrag()) { dragArea._internalGhost(drag); return }
            controller.dropProbe("over")
            if (drag.hasUrls && drag.urls.length > 0) {
                var p = fileListPane.mapFromItem(dragArea, drag.x, drag.y)
                fileListPane.dropHoverFid = fileListPane.hitFileRowAt(p.x, p.y)
            } else {
                fileListPane.dropHoverFid = ""
            }
        }
        onExited: {
            // 内部拖拽离开窗口 → 界面内的一切拖影/高亮立刻消失，
            // 由系统拖影独占（用户明确要求：里外只显示一套）。
            dragArea._clearInternalGhost()
            fileListPane.dropHoverFid = ""
        }
        onDropped: function(drop) {
            // 内部拖拽：落在分类行 = 改分类；落在别处 = 什么都不做
            // （就像在文件区随便拖了一下）。绝不走提交新版本。
            if (controller.isInternalDrag()) {
                var igp = dragArea.mapToGlobal(drop.x, drop.y)
                var icid = fileListPane.hitTreeRow(igp.x, igp.y)
                dragArea._clearInternalGhost()
                if (icid !== "") controller.internalDropOnTree(icid)
                drop.accepted = true
                return
            }
            var fid = ""
            if (drop.hasUrls) {
                var dp = fileListPane.mapFromItem(dragArea, drop.x, drop.y)
                fid = fileListPane.hitFileRowAt(dp.x, dp.y)
            }
            fileListPane.dropHoverFid = ""
            if (drop.hasUrls) {
                var urls = []
                for (var i = 0; i < drop.urls.length; i++)
                    urls.push(drop.urls[i].toString())
                if (fid !== "")
                    controller.dropOntoFile(fid, JSON.stringify(urls))
                else
                    controller.dropInFiles(JSON.stringify(urls))
            }
            drop.accepted = true
        }
    }

    Component.onCompleted: {
        // T2：恢复持久化主题（controller 只在 setThemeMode 时发信号，
        // 启动若不主动取一次，ui.theme=dark 的库会永远以浅色打开）
        Theme.mode = controller.themeMode()
        restoreTimer.start()
        refreshTotal()
    }

    Timer {
        id: restoreTimer
        interval: 200
        onTriggered: {
            var j = JSON.parse(controller.uiRestore(root.totalW))
            leftWrap.SplitView.preferredWidth = j.l
            if (j.r !== null) {
                lastRightW = Math.max(root.rightMinW,
                                      Math.min(root.rightMaxW,
                                               root.totalW - j.r))
                rightW = lastRightW
            }
            root.applyCollapsed(j.collapsed, false)
            restoring = false
            controller.refreshStatus()
        }
    }

    function diagSash() {
        return JSON.stringify({
            left: Math.round(catPane.width),
            mid: Math.round(fileListPane.width),
            right: Math.round(verPane.width),
            prefR: Math.round(verWrap.SplitView.preferredWidth),
            minR: Math.round(verWrap.SplitView.minimumWidth),
            collapsed: collapsed,
            totalW: totalW
        })
    }

    NumberAnimation {
        id: rightAnim
        target: root
        property: "rightW"
        duration: Theme.durPane
        easing.type: Easing.OutCubic
        onRunningChanged: if (!running) clamping = false
    }

    // M86：B 方案——宽度瞬时到位，内容滑入 + 淡入
    NumberAnimation {
        id: verSlideAnim
        target: verPane
        property: "slideX"
        duration: Theme.durLarge
        easing.bezierCurve: Theme.easeDecel
    }
    NumberAnimation {
        id: verFadeAnim
        target: verPane
        property: "opacity"
        duration: Theme.durBase
        easing.bezierCurve: Theme.easeDecel
    }

    // ---- 拖动钳制（A1：_sash_bounds custom 口径，松手落定）----
    property bool clamping: false

    // M97：右栏宽度绑定只在这一处重挂。**拖动过程中不重挂** ——
    // 旧实现每次 verPane.width 变化都 callLater 重挂到 rightW，
    // 而拖动时 SplitView 是命令式改 preferredWidth 的，绑定一挂上就被
    // rightW(旧值) 拉回去 → 拖右栏会「闪退回最窄」。
    function remountRightWidth() {
        verWrap.SplitView.preferredWidth =
            Qt.binding(function() { return root.rightW })
    }

    // M97：把当前三栏宽度写进 config（拖动结束/收纳切换时调，不必等退出）
    function persistPaneWidths() {
        controller.savePaneWidths(
            Math.round(catPane.width),
            root.collapsed ? 0 : Math.round(root.totalW - verPane.width),
            root.totalW)
    }

    function clampPane(pane, idx) {
        if (restoring || clamping) return
        var curL = Math.round(catPane.width)
        var pos = Math.round(pane === catPane ? catPane.width
                                               : root.totalW - verPane.width)
        var res = JSON.parse(controller.clampSash(idx, pos, root.totalW, curL))
        if (Math.abs(res.pos - pos) > 0.5) {
            clamping = true
            if (pane === catPane)
                leftWrap.SplitView.preferredWidth = res.pos
            else
                root.rightW = Math.max(root.rightMinW,
                                       Math.min(root.rightMaxW,
                                                root.totalW - res.pos))
            clamping = false
        }
        // M21：手柄拖动会命令式写 attached preferredWidth，一次性断开
        // verPane.SplitView.preferredWidth ← root.rightW 的声明式绑定。
        // 宽度回稳后重挂（值已被钳到当前实际宽，求值不变）。
        // M97：拖动**进行中**不重挂——重挂会把宽度立刻拉回 rightW 旧值。
        // 松手后由 splitView.onResizingChanged 统一同步 rightW 再重挂。
        if (pane === verPane && !splitView.resizing)
            Qt.callLater(root.remountRightWidth)
    }

    // ========================================================================
    // §2.7 玻璃氛围：极光只放两处——顶栏背后横向光带、右栏背后竖向冷光；
    // 列表背后不放颜色。QML 无 backdrop-filter，用半透明面板 + 柔边渐变近似。
    // ========================================================================
    Item {
        objectName: "auroraLayer"
        anchors.fill: parent
        clip: true
        // M44：深色模式下这几块「极光」只露出含糊的圆弧/椭圆边（按窗口定位、
        // 会溢进中栏：「版本数」上方那道弧 = 右栏竖向冷光的左缘 r=44；文件区
        // 下方的「椭圆胶囊」= 底部光斑 r=120）。深色下无视觉收益，整层关闭；
        // 浅色模式保持原样。
        opacity: Theme.mode === "dark" ? 0 : 1

        // M31：极光柔化——色阶改为缓入缓出，并叠一层「背景色羽化罩」，
        // 把矩形边缘的硬切线融进背景（实测：深浅过渡生硬）。
        // 羽化罩颜色 = 窗口底色，只压暗极光、不产生新色块。

        // ① 顶栏背后横向光带：水平缓变 + 底缘垂直羽化
        Rectangle {
            x: Theme.sp16
            y: Theme.sp16
            width: parent.width - Theme.sp16 * 2
            height: 210
            radius: 26
            opacity: Theme.auroraA
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.00; color: "#006C8CFF" }
                GradientStop { position: 0.14; color: "#1A6C8CFF" }
                GradientStop { position: 0.32; color: "#406C8CFF" }
                GradientStop { position: 0.50; color: "#3C7A5CFF" }
                GradientStop { position: 0.68; color: "#2E7A5CFF" }
                GradientStop { position: 0.84; color: "#1C22D3EE" }
                GradientStop { position: 1.00; color: "#0022D3EE" }
            }
        }
        Rectangle {
            x: Theme.sp16
            y: Theme.sp16
            width: parent.width - Theme.sp16 * 2
            height: 210
            radius: 26
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.00; color: Qt.alpha(Theme.cBg, 0) }
                GradientStop { position: 0.42; color: Qt.alpha(Theme.cBg, 0) }
                GradientStop { position: 0.78; color: Qt.alpha(Theme.cBg, 0.53) }
                GradientStop { position: 1.00; color: Qt.alpha(Theme.cBg, 1) }
            }
        }

        // ② 右栏背后竖向冷光：垂直缓变 + 左右两侧羽化
        Rectangle {
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16
            y: 96
            width: 380
            height: Math.max(120, parent.height - 190)
            radius: 44
            opacity: Theme.auroraB
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.00; color: "#007A5CFF" }
                GradientStop { position: 0.16; color: "#2A7A5CFF" }
                GradientStop { position: 0.34; color: "#447A5CFF" }
                GradientStop { position: 0.55; color: "#3A7A5CFF" }
                GradientStop { position: 0.76; color: "#266C8CFF" }
                GradientStop { position: 1.00; color: "#0022D3EE" }
            }
        }
        Rectangle {
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16
            y: 96
            width: 380
            height: Math.max(120, parent.height - 190)
            radius: 44
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.00; color: Qt.alpha(Theme.cBg, 1) }
                GradientStop { position: 0.38; color: Qt.alpha(Theme.cBg, 0.40) }
                GradientStop { position: 0.78; color: Qt.alpha(Theme.cBg, 0.08) }
                GradientStop { position: 1.00; color: Qt.alpha(Theme.cBg, 0.91) }
            }
        }

        // ③ 中下部冷光斑：水平缓变 + 上下羽化（收成软椭圆）
        Rectangle {
            x: parent.width * 0.30
            y: parent.height * 0.55
            width: 360
            height: 240
            radius: 120
            opacity: Theme.auroraC
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.00; color: "#007A5CFF" }
                GradientStop { position: 0.22; color: "#1E7A5CFF" }
                GradientStop { position: 0.50; color: "#3D7A5CFF" }
                GradientStop { position: 0.78; color: "#1E7A5CFF" }
                GradientStop { position: 1.00; color: "#007A5CFF" }
            }
        }
        Rectangle {
            x: parent.width * 0.30
            y: parent.height * 0.55
            width: 360
            height: 240
            radius: 120
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.00; color: Qt.alpha(Theme.cBg, 1) }
                GradientStop { position: 0.32; color: Qt.alpha(Theme.cBg, 0.165) }
                GradientStop { position: 0.68; color: Qt.alpha(Theme.cBg, 0.165) }
                GradientStop { position: 1.00; color: Qt.alpha(Theme.cBg, 1) }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        // M50：用户反馈三栏与边界留白偏多 → 外距 16→12、栏间距 12→10
        anchors.leftMargin: Theme.sp8
        anchors.rightMargin: Theme.sp8
        anchors.topMargin: Theme.sp8
        anchors.bottomMargin: Theme.sp8
        spacing: Theme.sp6

        // ====================================================================
        // §4.1 顶栏：M35 收窄为 48px 单行玻璃条（原 60px，全组件缩一号）
        // 左 → 右：Logo24 + 名/副标 → 弹性 → 搜索 320×30 → 主按钮 116×30
        //          → 右栏开合 / 设置 / 主题 / 帮助（各 28×28）
        // ====================================================================
        Rectangle {
            objectName: "topBar"
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            radius: Theme.rTopBar
            antialiasing: true
            color: Theme.cToolbar
            border.width: 1
            border.color: Theme.cGlassBorder

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 0
                anchors.rightMargin: 0
                spacing: Theme.sp12

                // 顶栏内左留白（用子项而不是 leftMargin：main.py 的钉右判据
                // 以按钮 x+width 相对窗口宽度计算，父项偏移会把间隙算大）
                Item { Layout.preferredWidth: Theme.sp16
                       Layout.minimumWidth: Theme.sp16 }

                // M31b：产品澄清——左上角 Logo 保留原样（此前理解错了指向）
                Image {
                    source: Qt.resolvedUrl("../resources/logo_v3.png")
                    sourceSize.width: 60
                    sourceSize.height: 60
                    Layout.preferredWidth: 24
                    Layout.preferredHeight: 24
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                }

                Column {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 1
                    Text {
                        text: "井然"
                        font.family: Theme.fontFamily
                        font.pointSize: Theme.pt(13.5)
                        font.weight: Font.DemiBold
                        color: Theme.cText
                    }
                    Text {
                        text: "本地版本库 · " + controller.libraryTotal
                              + " 个文件"
                        font.family: Theme.fontFamily
                        font.pointSize: Theme.pt(10)
                        color: Theme.cTextDim
                    }
                }

                Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }

                // ---- 搜索：320×30、圆角 10、白 62%、内嵌 Ctrl K 键帽 ----
                Rectangle {
                    objectName: "searchBox"
                    // 宽裕 320；极窄（<1180，仅无窗管平台会出现）可收到 0，
                    // 保证右上三按钮永远钉右可达（M12 降级规则）
                    Layout.fillWidth: true
                    Layout.preferredWidth: 320
                    Layout.maximumWidth: 320
                    Layout.minimumWidth: 0
                    Layout.preferredHeight: 30
                    radius: 10
                    color: Theme.cSearchBg
                    // M80：聚焦不再加粗描边（会挤动内边距、看着发飘），
                    // 改成「1px 主色内框 + 3px 主色 18% 外环」的双环。
                    border.width: 1
                    border.color: search.activeFocus ? Theme.cAccent : Theme.cBorder

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: -3
                        radius: parent.radius + 3
                        color: "transparent"
                        border.width: 3
                        border.color: Qt.rgba(Theme.cAccent.r, Theme.cAccent.g,
                                              Theme.cAccent.b, 0.18)
                        visible: search.activeFocus
                        z: -1
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 8
                        spacing: Theme.sp6
                        GlyphIcon {
                            name: "search"
                            size: 14
                            iconColor: Theme.cTextDim
                        }
                        TextField {
                            id: search
                            Layout.fillWidth: true
                            placeholderText: "搜索文件名 / 修改原因 / 意见来源"
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(12.5)
                            color: Theme.cText
                            placeholderTextColor: Theme.cTextMute
                            background: null
                            selectByMouse: true
                            onTextChanged: searchDebounce.restart()
                        }
                        GlyphIcon {
                            name: "close"
                            size: 14
                            iconColor: Theme.cTextDim
                            visible: search.text.length > 0
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: { search.text = ""; controller.clearSearch() }
                            }
                        }
                        Rectangle {
                            visible: parent.width > 260
                            width: 36
                            height: 18
                            radius: 6
                            color: search.activeFocus ? Theme.cAccentBg : "transparent"
                            border.width: 1
                            border.color: search.activeFocus ? Theme.cAccent
                                                             : Theme.cBorder
                            Text {
                                anchors.centerIn: parent
                                text: "Ctrl K"
                                font.family: Theme.fontFamily
                                font.pointSize: Theme.pt(Theme.fsNano)
                                color: search.activeFocus ? Theme.cAccent
                                                          : Theme.cTextWeak
                            }
                        }
                    }

                    Timer {
                        id: searchDebounce
                        interval: 250
                        onTriggered: controller.searchApply(search.text)
                    }
                }

                // ---- 主按钮 116×30 ----
                AppButton {
                    id: commitToolBtn
                    objectName: "commitToolBtn"
                    text: "提交新版本"
                    primary: true
                    btnHeight: 30
                    Layout.preferredWidth: 116
                    Layout.preferredHeight: 30
                    font.pointSize: Theme.pt(12.5)
                    tip: "提交新版本：把文件的当前内容保存为新版本快照\n（也可把文件或文件夹直接拖进窗口；F1 等价）"
                    onClicked: controller.openCommitDialog()
                }

                // ---- 图标按钮 28×28（objectName 门禁依赖，顺序勿动）----
                AppButton {
                    id: toggleBtn
                    objectName: "toggleRight"
                    text: ""
                    iconSrc: root.collapsed ? root.iconUrl("panel_show", 22)
                                         : root.iconUrl("panel_hide", 22)
                    iconSize: 14
                    btnHeight: 28
                    Layout.preferredWidth: 28
                    Layout.preferredHeight: 28
                    tip: root.collapsed ? "展开版本栏" : "收纳版本栏"
                    onClicked: {
                        var c = !root.collapsed
                        controller.toggleCollapseRight(
                            c, Math.round(catPane.width),
                            root.collapsed ? 0 : Math.round(root.totalW - verPane.width),
                            root.totalW)
                        root.applyCollapsed(c, true)
                    }
                }
                AppButton {
                    id: settingsBtn
                    objectName: "settingsBtn"
                    text: ""
                    iconSrc: root.iconUrl("settings")
                    iconSize: 14
                    btnHeight: 28
                    Layout.preferredWidth: 28
                    Layout.preferredHeight: 28
                    tip: "设置"
                    onClicked: controller.open_settings()
                }

                // 主题切换 28×28（规格 §4.1：设置 / 主题两个图标按钮）
                // helpBtn 必须是最右图标按钮（main.py reach 钉右判据用它）
                AppButton {
                    id: helpBtn
                    objectName: "helpBtn"
                    text: ""
                    iconSrc: root.iconUrl("help")
                    iconSize: 14
                    btnHeight: 28
                    Layout.preferredWidth: 28
                    Layout.preferredHeight: 28
                    tip: "帮助"
                    onClicked: controller.open_help()
                }

                // M31：右缘留白——修「帮助图标超出最右边缘」；整组左移、相对位置不变
                Item { Layout.preferredWidth: Theme.sp16
                       Layout.minimumWidth: Theme.sp16 }
            }
        }

        // ====================================================================
        // §3 三栏：16 外距 / 12 缝隙 / 圆角 22 浮动面板；栏间 1px 发丝线
        // ====================================================================
        SplitView {
            id: splitView
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            handle: Item {
                id: splitHandle
                implicitWidth: 6
                // M45：用户反馈「文件区左右两条竖线难看」——原本 1px 发丝线
                // 常显（深色 12% 白 / 浅色浅灰）。改为仅鼠标移到分隔条上
                // （或正在拖拽）时淡入，平时完全隐藏；10px 热区与拖拽语义不变。
                readonly property bool hov: SplitHandle.hovered
                                      || SplitHandle.pressed
                Item {
                    anchors.centerIn: parent
                    width: 10
                    height: parent.height
                    Rectangle {
                        property real dpr: Screen.devicePixelRatio
                        anchors.verticalCenter: parent.verticalCenter
                        width: 1 / dpr
                        height: parent.height
                        x: Math.round((parent.width / 2) * dpr) / dpr - 0.5 / dpr
                        color: Theme.cHairline
                        opacity: (root.collapsed || !splitHandle.hov) ? 0 : 0.8
                        Behavior on opacity {
                            NumberAnimation { duration: Theme.durHover; easing.bezierCurve: Theme.easeStandard }
                        }
                    }
                    CursorMouseArea { anchors.fill: parent }
                }
            }

            // ---------------- 左栏：分类树 248 ----------------
            Item {
                id: leftWrap
                SplitView.minimumWidth: 200
                SplitView.preferredWidth: 248

                Rectangle {   // 单层柔影（§2.6：只允许一层）
                    anchors.fill: parent
                    anchors.topMargin: parent.height - 14
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    radius: 10
                    color: "#120F1C46"
                }
                CategoryTreePane {
                    id: catPane
                    anchors.fill: parent
                }
            }

            // ---------------- 中栏：文件列表（吃余量）----------------
            Item {
                id: midWrap
                SplitView.minimumWidth: 320
                SplitView.fillWidth: true

                Rectangle {
                    anchors.fill: parent
                    anchors.topMargin: parent.height - 14
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    radius: 10
                    color: "#120F1C46"
                }
                FileListPane {
                    id: fileListPane
                    anchors.fill: parent
                    treePane: catPane
                    onClearSearchRequested: search.text = ""
                    onRequestExpandRight: {
                        var l = Math.round(catPane.width)
                        var r = Math.round(root.totalW - verPane.width)
                        controller.toggleCollapseRight(false, l, r, root.totalW)
                        root.applyCollapsed(false, true)
                    }
                    onWidthChanged: root.clampPane(verPane, 1)
                }
            }

            // ---------------- 右栏：检查器 312 ----------------
            Item {
                id: verWrap
                SplitView.minimumWidth: root.collapsed ? 0 : 260
                SplitView.preferredWidth: root.rightW
                clip: true

                Rectangle {
                    anchors.fill: parent
                    anchors.topMargin: parent.height - 14
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    radius: 10
                    color: "#120F1C46"
                }
                VersionPane {
                    id: verPane
                    anchors.fill: parent
                    visible: true
                    onWidthChanged: if (!root.collapsed) root.clampPane(verPane, 1)
                }
            }
        }

        // M92：这里原本有一条常驻状态条（M87 做的，高 14）。
        // 它的问题不是"高"，而是**下面还压着 6px 栏间距 + 8px 外边距**，
        // 面板结束后到底边共 28px 全是背景色，中间只浮一行小灰字「就绪」
        // —— 用户看到的就是一条空带。中栏页脚右侧本来就有状态位，两处
        // 各占一块纯属重复。现代桌面端（Linear / Notion / Figma）都不设
        // 全局状态栏，状态信息寄生在已有容器里。
        // 消息与转圈已全部移到 fileListPane.showStatus() / 页脚。
    }

    // M33：Diff 窗常驻单实例——payload 必须由本函数主动灌入。
    // 旧实现在 diffReady 之后才 createObject（且 DiffDialog 自带
    // Connections 收不到已发射的信号）→ 弹空窗，用户视为「无反应」。
    property Window diffDlg: null

    function showDiff(payloadJson) {
        if (!root.diffDlg)
            root.diffDlg = diffDialogComp.createObject(root)
        root.diffDlg.applyPayload(payloadJson)
        root.diffDlg.show()
        root.diffDlg.requestActivate()
    }

    Component {
        id: diffDialogComp
        DiffDialog {}
    }

    Connections {
        target: controller
        function onDiffReady(payloadJson) { root.showDiff(payloadJson) }
        // M92：状态消息一律落到中栏页脚右侧（底部状态条已删除）。
        // dim = 计数刷新，视为「无消息」；其余按类型着色，2.6s 后回落。
        function onStatusChanged(text, kind) {
            fileListPane.showStatus(text, kind)
        }
        function onRightCollapsedChanged(c) {
            if (c !== root.collapsed) root.applyCollapsed(c, true)
        }
        // M77-6：QDrag.exec 是模态阻塞，启动后 QML 收不到任何事件。
        // 必须在它开始前把自绘跟随卡片收走，否则卡片会僵在最后位置
        // （1.1.21 实测：文件拖出窗口后，界面内那张还在原地）。
        function onInternalDragStarted() {
            fileListPane.dragGhost = null
            if (catPane) catPane.catGhost = null
            if (verPane) verPane.verGhost = null
        }
    }

    // ========================================================================
    // M97：分区宽度只在「用户亲手拖完」时落定
    // ------------------------------------------------------------------------
    // 旧行为：verPane.width 一变就 clampPane → 重挂 preferredWidth ← rightW。
    // 拖动时 SplitView 是命令式改 preferredWidth 的，绑定一挂上就被 rightW
    // 的旧值拉回 → 拖右栏「闪退回最窄」，且再拖左栏会更明显。
    //
    // 现在按「拖动开始/结束」两段处理：
    //   · 开始：记下左栏宽度，用来判断拖的是哪根分隔条
    //   · 结束：左栏没动 = 拖的是中/右分隔条 → 把实际宽度确认为 rightW，
    //           写库并重挂绑定；左栏动了 = 右栏是被动让位 → 保留 rightW 不动
    // ========================================================================
    Connections {
        target: splitView
        function onResizingChanged() {
            if (restoring) return
            if (splitView.resizing) {
                root._dragCatW = Math.round(catPane.width)
                return
            }
            var catMoved = root._dragCatW >= 0
                    && Math.abs(Math.round(catPane.width) - root._dragCatW) > 1
            root._dragCatW = -1
            if (!catMoved && !root.collapsed) {
                root.rightW = Math.max(root.rightMinW,
                                       Math.min(root.rightMaxW,
                                                Math.round(verPane.width)))
                root.lastRightW = root.rightW
            }
            root.remountRightWidth()
            root.persistPaneWidths()
        }
    }

    // ---- 关窗（A8 闸门 → A3 保存段 → M47 托盘驻留）----
    onClosing: function(close) {
        var ok = controller.requestClose()
        if (!ok) {
            close.accepted = false
            return
        }
        controller.appClosing(
            root.geomString(),
            root.visibility === Window.Maximized,
            Math.round(catPane.width),
            root.collapsed ? 0 : Math.round(root.totalW - verPane.width),
            root.totalW)
        // M47：默认「关闭即隐藏到托盘」，只有托盘菜单退出（forceQuit）才真退出
        if (!controller.forceQuit() && controller.closeToTray()) {
            close.accepted = false
            root.hide()
            controller.notifyHidden()
            return
        }
        close.accepted = true
        // M71：程序为托盘常驻设了「最后一个窗口关闭不退出」
        // （main.py: setQuitOnLastWindowClosed(tray is None)），
        // 所以关掉「关闭即隐藏」后不能只 accepted —— 必须显式退出，
        // 否则窗口消失、进程和托盘图标还在（实测就是这种情况）。
        if (!controller.forceQuit())
            controller.requestQuit()
    }

    component CursorMouseArea: MouseArea {
        cursorShape: root.collapsed ? Qt.ArrowCursor : Qt.SplitHCursor
        acceptedButtons: Qt.NoButton
    }

    // ====================================================================
    // M31：界面内拖拽的自绘跟随图标（文件→分类）。
    // 数据源：FileListPane.dragGhost（窗口坐标 + 数量 + 类型）；
    // 拖出窗口后由 QDrag 系统接管（Windows 原生拖拽视觉），此件自动隐藏。
    // ====================================================================
    // M85：版本卡片拖到界面内 → 判定落点 → 另存为文件
    Connections {
        target: verPane
        function onDragMoved(gx, gy) {
            if (fileListPane) fileListPane.updateVersionDrop(gx, gy)
        }
        function onDragDropped() {
            if (!fileListPane) return
            var t = fileListPane.takeVersionDrop()
            if (t.kind === "cid" && t.cid !== "") {
                controller.saveVersionAsFile("cid", t.cid)
            } else if (t.kind === "list") {
                controller.saveVersionAsFile("list", "")
            }
        }
    }

    Item {
        id: dragGhost
        // 数据源二选一：中栏文件列表 / 右栏版本区。两边字段口径一致
        // （count + 窗口坐标 x/y），所以共用同一张卡片——三个可拖区域
        // 视觉统一，用户不用分别学。
        property var g: fileListPane.dragGhost || verPane.verGhost || null
        visible: g !== null
        x: g ? Math.max(4, Math.min(g.x + 14,
                                    root.width - ghostCard.width - 4)) : 0
        y: g ? Math.max(4, Math.min(g.y + 12,
                                    root.height - ghostCard.height - 4)) : 0
        z: 1000

        Rectangle {
            id: ghostCard
            width: ghostRow.implicitWidth + 24
            height: 44
            radius: 12
            color: "#FFFFFF"
            border.width: 1
            border.color: "#DCE3EF"
            opacity: 0.96
            Rectangle {
                anchors.fill: parent
                radius: 12
                color: Theme.cAccent
                opacity: 0.10
            }
            Row {
                id: ghostRow
                anchors.centerIn: parent
                spacing: 8
                FileTypeIcon {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: dragGhost.g ? (dragGhost.g.ext || "txt") : ""
                    size: 22
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: dragGhost.g
                          ? ((dragGhost.g.count || 1) === 1
                             ? "移动这个文件"
                             : "移动 " + dragGhost.g.count + " 个文件")
                          : ""
                    font.family: Theme.fontFamily
                    font.pointSize: Theme.pt(12.5)
                    font.weight: Font.Medium
                    color: Theme.cText
                }
            }
        }
    }
}
