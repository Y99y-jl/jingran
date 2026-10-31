import QtQuick
import QtQuick.Controls.Basic
// M99：Screen 附加属性需要它。缺这个 import 时 Screen.xxx 会静默返回
// undefined（不报错、qmllint 也查不出），所以高度兜底逻辑必须同时存在。
import QtQuick.Window
import ".."
import "../components"

// F 组弹窗宿主（M29 · UI 规格 V3 §4.5 / §4.6 / §4.7 / §4.8）。
// 数据驱动结构不动（spec.fields/groups/buttons、rid、keepOpen、Esc）。
// 提交弹窗按 V3 重排：文件卡片 → 分类 → 修改原因（默认聚焦 + 主色描边 +
// 外发光）→ 意见来源 → 版本对照条；字段顺序与数量一个不少。
Dialog {
    id: pane
    objectName: "dialogHost"
    modal: true
    visible: false
    closePolicy: Popup.NoAutoClose
    padding: 0
    // M35 2.2：弹窗遮罩——浅 rgba(11,18,36,.20) / 深 rgba(0,0,0,.40)，
    // 主题切换自动跟随。Qt 6 的正确写法是 Overlay.modal 挂自定义项
    // （Overlay.overlay.color 在 6.12 编译期报 "non-existent property
    // color"——overlay 项是 QQuickItem 无 color 属性，已实测确认）。
    // 挂在 Dialog 根上，对本窗口全部 F 组弹窗生效。
    Overlay.modal: Rectangle {
        color: Theme.cScrim
    }

    // M81：弹窗原本"啪"一下出现。加 160ms 淡入 / 110ms 淡出
    // （桌面端 Material 建议 150–200ms，退场更短）。
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

    readonly property bool isCommit: !!(specData
        && String(specData.title || "").indexOf("提交") >= 0
        && commitFields())
    // M102：带导航的设置面板需要更宽（Material 560 是无导航对话框的上限，
    // 带侧栏的面板类对话框业界普遍更宽：Home Assistant 580、Figma 800+）
    width: hasNav ? 660 : 560
    // 设计基准 560×652；本实现字段块略高，用内容自适应避免页脚悬空
    // M99：原上限写死 720，弹窗比窗口还高时会被上下切掉（标题和按钮都不见了）。
    // 判据要用**窗口高度**而不是屏幕高度——窗口被拉小、或屏幕本来矮，都会出现
    // 这个问题。
    // M101：按 Material Design 3 官方规格收一档 —— 对话框容器
    // 「宽 min 280 / max 560，高同样 max 560，距屏幕上下边缘至少 48dp」。
    // 原来只压到「窗口高 −96」还不够克制，设置/帮助几乎占满一屏。现在取
    // min(520, 窗口高 −120)，上下各留 60 的呼吸；内容超高交给滚动。
    readonly property int maxDialogH: {
        var avail = parent ? parent.height : 0
        if (!avail || avail <= 0)
            avail = Screen.desktopAvailableHeight || 800   // 兜底
        return Math.max(240, Math.min(520, Math.floor(avail - 120)))
    }
    // M99：页脚已移出滚动区（固定底部），所以高度要把页脚那一段算进去，
    // 否则短弹窗会被页脚压住。footBar 在本文件后段声明，前向引用安全。
    readonly property int footH: (pane.isCommit || btnRepeater.count > 0)
                                  ? 38 + 12 : 0
    height: Math.min(body.implicitHeight + 56 + footH, maxDialogH)
    anchors.centerIn: parent

    background: Rectangle {
        color: Theme.cFloatBg
        border.width: 1
        border.color: Theme.cFloatBorder
        radius: Theme.rPanel
    }

    Shortcut {
        sequence: "Esc"
        enabled: pane.visible
        onActivated: pane.submit("cancel")
    }
    // §4.5 页脚提示：Ctrl + Enter 快速保存
    Shortcut {
        sequence: "Ctrl+Return"
        enabled: pane.visible && pane.isCommit
        onActivated: pane.submit("ok")
    }
    Shortcut {
        sequence: "Ctrl+Enter"
        enabled: pane.visible && pane.isCommit
        onActivated: pane.submit("ok")
    }
    // M36：产品要求「许多地方的确认改用 Enter」——新增 Enter = 弹窗
    // 主动作快捷键（保留原有点击/Esc/Ctrl+Enter 全部不变）。
    // 判定规则（刻意与「最后一个按钮 = 主动作」的视觉口径区分）：
    //   ① accent===true 的主色按钮优先（ok/cancel 家族、merge、commit…）；
    //   ② 无主色时回落 key==="ok"——删除/清空等 danger 确认的主动作
    //      accent 恒 false 且按 spec 留在最左，不是「最后一个按钮」，
    //      只看视觉最后一项会把 Enter 判成「取消」，必须按 key 取；
    //   ③ 两者都没有（孤儿副本 open/drop/later 三选一无主动作、设置
    //      组内按钮无页脚）→ Enter 不触发，避免误伤。
    // 豁免：提交弹窗多行「修改原因」聚焦时 Enter = 换行（§4.6 交互
    //       保持），快速保存仍是 Ctrl+Enter（上方既有 Shortcut）。
    Shortcut {
        sequences: ["Return", "Enter"]
        enabled: pane.visible && !(pane.isCommit
                && pane.reasonItem && pane.reasonItem.activeFocus)
        onActivated: {
            var bs = pane.footerBtns || []
            var key = ""
            for (var i = 0; i < bs.length; i++)
                if (bs[i] && bs[i].accent === true) { key = bs[i].key; break }
            if (key === "")
                for (var j = 0; j < bs.length; j++)
                    if (bs[j] && bs[j].key === "ok") { key = "ok"; break }
            if (key !== "") pane.submit(key)
        }
    }

    property var specData: null
    property var valueMap: ({})
    property int reasonLen: 0
    property Item reasonItem: null
    // M36：Enter 主动作判定用——openSpec 排序后的页脚按钮副本
    property var footerBtns: []

    function commitFields() {
        var f = (specData && specData.fields) || []
        for (var i = 0; i < f.length; i++)
            if (f[i].key === "reason") return true
        return false
    }

    function fieldValue(key) {
        var f = (specData && specData.fields) || []
        for (var i = 0; i < f.length; i++)
            if (f[i].key === key) return f[i]
        return null
    }

    function categoryLabel() {
        var f = fieldValue("category")
        if (!f) return ""
        var opts = f.options || []
        var idx = (typeof pane.valueMap["category"] === "number")
                ? pane.valueMap["category"] : 0
        return (idx >= 0 && idx < opts.length) ? opts[idx].label : ""
    }

    function openSpec(spec) {
        specData = spec
        valueMap = {}
        var f = spec.fields || []
        for (var i = 0; i < f.length; i++) {
            valueMap[f[i].key] = f[i].value
            if (f[i].key === "reason")
                reasonLen = String(f[i].value || "").length
        }
        titleLbl.text = spec.title || ""
        msgLbl.text = spec.message || ""
        msgLbl.visible = !!spec.message
        // 弹窗副标（V3）：提交弹窗固定一句，其它弹窗不显示
        subLbl.visible = !!spec.message ? false : isCommit
        headIcon.visible = isCommit
        repeater.model = f
        groupsRepeater.model = spec.groups || []
        // M102：默认高亮第一个分区
        curSection = sectionList.length > 0 ? sectionList[0] : ""
        // §4.5 按钮右对齐：取消在左、主动作在最右——渲染前把 accent 排到最后
        var _btns = (spec.buttons || []).slice()
        _btns.sort(function(a, b) {
            return (a.accent === true ? 1 : 0) - (b.accent === true ? 1 : 0)
        })
        btnRepeater.model = _btns
        // M36：Enter 主动作判定源，与渲染用同一排序数组
        footerBtns = _btns
        open()
        if (isCommit) focusTimer.restart()
    }

    Connections {
        target: controller
        function onDialogFieldPicked(key, path) {
            pane.setValue(key, path)
            if (key === "path" && pathField)
                pathField.text = path
            if (pathField) pathField.forceActiveFocus()
        }
    }

    Timer {
        id: focusTimer
        interval: 80
        onTriggered: if (pane.reasonItem) pane.reasonItem.forceActiveFocus()
    }

    // keepOpen=true：动作按钮（复制路径/重建索引/切换主题…）不关闭弹窗
    // M50：必填未填时主动作置灰（提交弹窗路径为空 → 保存不可点）
    function okEnabled(b) {
        if (!b || b.accent !== true) return true
        var req = (specData && specData.okRequire) || []
        for (var i = 0; i < req.length; i++) {
            var v = pane.valueMap[req[i]]
            if (v === undefined || v === null || String(v).trim() === "")
                return false
        }
        return true
    }

    function submit(btnKey, keepOpen) {
        var rid = specData ? specData.rid : ""
        valueMap["__btn"] = btnKey
        if (keepOpen !== true)
            visible = false
        controller.dialogResult(JSON.stringify(
            {rid: rid, values: valueMap}))
    }

    function setValue(key, v) {
        var m = Object.assign({}, pane.valueMap)
        m[key] = v
        pane.valueMap = m
    }

    // M99：内容区可滚动。超过 maxDialogH 时这里滚动，不再让弹窗顶出屏幕。
    // 页脚随内容一起滚——普通弹窗（确认/提交/设置）内容不足一屏，完全无感；
    // 只有帮助这类长文本需要拉到底。（页脚固定是另一种做法，但那要把页脚
    // 从 Column 里提出来单独定位，改动面大，收益只是"少滚一下"。）
    // M102：标题固定在弹窗顶部，不随内容滚动（Material/MUI paper 滚动规范）。
    // ---------------- 标题区 ----------------
    Row {
        id: titleRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 24
        anchors.rightMargin: 24
        anchors.topMargin: 24
        spacing: 12
        Rectangle {
            id: headIcon
            visible: false
            width: 36
            height: 36
            radius: 11
            color: Theme.cAccentBg
            // M35 5.1：字符「＋」换矢量图标
            GlyphIcon {
                anchors.centerIn: parent
                name: "plus"
                size: 18
                iconColor: Theme.cAccent
            }
        }
        Column {
            width: parent.width - (headIcon.visible ? 48 : 0) - closeBtn.width
            spacing: Theme.sp2
            Text {
                id: titleLbl
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsDialog)
                font.weight: Font.DemiBold
                color: Theme.cText
            }
            Text {
                id: subLbl
                visible: false
                text: "为文件保存一个快照，之后可随时回滚"
                font.family: Theme.fontFamily
                font.pointSize: Theme.pt(Theme.fsMeta)
                color: Theme.cTextDim
            }
        }
        Item { width: 1; height: 1 }
    }

    // M102：左侧分区导航（设置类弹窗专用）。groups 带 section 标签时出现，
    // 点击滚动到该区第一张卡片。参考 macOS 系统设置 / VS Code 的侧栏做法——
    // 分区多于 3 个时列表比一堆卡片更好找。
    readonly property var sectionList: {
        var gs = pane.specData ? (pane.specData.groups || []) : []
        var seen = [], out = []
        for (var i = 0; i < gs.length; i++) {
            var sc = gs[i].section
            if (sc && seen.indexOf(sc) < 0) { seen.push(sc); out.push(sc) }
        }
        return out
    }
    readonly property bool hasNav: sectionList.length > 1
    property string curSection: ""

    function jumpToSection(sect) {
        curSection = sect
        var gs = pane.specData ? (pane.specData.groups || []) : []
        for (var i = 0; i < gs.length; i++) {
            if (gs[i].section !== sect) continue
            var it = groupsRepeater.itemAt(i)
            if (it) {
                scroll.contentY = Math.max(0, it.y + groupsCol.y - 4)
                return
            }
        }
    }

    Column {
        id: navCol
        visible: pane.hasNav
        width: 104
        anchors.left: parent.left
        anchors.leftMargin: 24
        anchors.top: scroll.top
        anchors.bottom: scroll.bottom
        spacing: 2

        Repeater {
            model: pane.sectionList

            delegate: Rectangle {
                id: navRow
                required property string modelData
                width: navCol.width
                height: 30
                radius: 8
                color: pane.curSection === modelData ? Theme.cAccentBg
                                                     : "transparent"

                Text {
                    x: 10
                    width: parent.width - 20
                    anchors.verticalCenter: parent.verticalCenter
                    text: navRow.modelData
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pointSize: Theme.pt(Theme.fsMeta)
                    font.weight: pane.curSection === modelData
                                 ? Font.DemiBold : Font.Normal
                    color: pane.curSection === modelData
                           ? Theme.cAccent : Theme.cText2
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: pane.jumpToSection(navRow.modelData)
                }
            }
        }
    }

    Flickable {
        id: scroll
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleRow.bottom
        // M102：有导航时左边让出导航栏宽度
        anchors.leftMargin: pane.hasNav ? 24 + 116 : 24
        anchors.rightMargin: 24
        anchors.topMargin: 12
        // 底部让给固定的页脚
        anchors.bottom: footBar.top
        anchors.bottomMargin: 12
        // M102：右边留 14 给滚动条，内容不再被压住
        contentWidth: width - 14
        contentHeight: body.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        ScrollBar.vertical: ScrollBar {
            policy: scroll.contentHeight > scroll.height
                    ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
            width: 6
            // M102：贴右侧 gutter
            anchors.right: parent.right
            anchors.rightMargin: 4
            padding: 0
        }

    Column {
        id: body
        width: scroll.contentWidth
        spacing: 16


        // M102：正文（message）属于滚动内容，不能跟标题一起固定。
        // 原来它和 titleLbl 同在一个 Column 里，整块提出去后正文溢出弹窗。
        Text {
            id: msgLbl
            width: parent.width
            visible: false
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            font.family: Theme.fontFamily
            font.pointSize: Theme.pt(Theme.fsMeta)
            color: Theme.cTextDim
        }

        // ---------------- 设置弹窗分组（M35 4.3：四组卡片 + 主题分段）----------------
        Column {
            id: groupsCol
            width: parent.width
            spacing: 12
            visible: groupsRepeater.count > 0

            Repeater {
                id: groupsRepeater

                delegate: Rectangle {
                    id: groupWrap
                    required property var modelData
                    width: parent.width
                    height: groupCol.implicitHeight + 28
                    radius: Theme.rCard
                    color: Theme.cSubtleBg
                    border.width: 1
                    border.color: Theme.cBorder

                    Column {
                        id: groupCol
                        x: 14
                        y: 14
                        width: parent.width - 28
                        spacing: 8

                        Text {
                            text: groupWrap.modelData.title || ""
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(Theme.fsMeta)
                            font.weight: Font.DemiBold
                            color: Theme.cTextHeader
                        }

                        Repeater {
                            model: groupWrap.modelData.items || []

                            delegate: Column {
                                id: gItem
                                required property var modelData
                                width: parent.width
                                spacing: Theme.sp6

                                Text {
                                    visible: gItem.modelData.type === "text"
                                    width: parent.width
                                    text: gItem.modelData.value || ""
                                    font.family: Theme.fontFamily
                                    font.pointSize: Theme.pt(Theme.fsMeta)
                                    color: Theme.cTextDim
                                    wrapMode: Text.WrapAnywhere
                                    textFormat: Text.PlainText
                                }

                                // M50：开关型设置项（左侧文字 + 右侧状态按钮）
                                Row {
                                    visible: gItem.modelData.type === "toggle"
                                    width: parent.width
                                    spacing: 12
                                    Text {
                                        width: parent.width - 96 - 12
                                        text: gItem.modelData.label || ""
                                        font.family: Theme.fontFamily
                                        font.pointSize: Theme.pt(Theme.fsMeta)
                                        color: Theme.cText
                                        elide: Text.ElideRight
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    AppButton {
                                        width: 96
                                        height: 32
                                        soft: gItem.modelData.on === true
                                        text: gItem.modelData.on === true
                                              ? "已开启" : "已关闭"
                                        onClicked: pane.submit(
                                            gItem.modelData.key, false)
                                    }
                                }

                                Row {
                                    visible: gItem.modelData.type === "buttons"
                                    spacing: 8

                                    Repeater {
                                        model: gItem.modelData.buttons || []

                                        delegate: AppButton {
                                            required property var modelData
                                            text: modelData.label
                                            danger: modelData.danger === true
                                            height: 34
                                            onClicked: pane.submit(
                                                modelData.key,
                                                modelData.keepOpen === true)
                                        }
                                    }
                                    Text {
                                        visible: !!gItem.modelData.note
                                        text: gItem.modelData.note || ""
                                        font.family: Theme.fontFamily
                                        font.pointSize: Theme.pt(Theme.fsNano)
                                        color: Theme.cTextWeak
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                }

                                // ---- 主题分段（二选一）：容器 rInput，
                                // 点选即 setValue + submit("theme_switch", true) ----
                                Rectangle {
                                    visible: gItem.modelData.type === "segment"
                                    width: parent.width
                                    height: 34
                                    radius: Theme.rInput
                                    color: Theme.cInputBg
                                    border.width: 1
                                    border.color: Theme.cInputBorder
                                    Row {
                                        anchors.fill: parent
                                        anchors.margins: 3
                                        spacing: 3
                                        Repeater {
                                            model: gItem.modelData.options || []

                                            delegate: Rectangle {
                                                required property var modelData
                                                readonly property bool isOn: gItem.modelData.value === modelData.value
                                                // Repeater 本身也是 Row 的 child
                                                // （探针实测 children.length=选项数+1），
                                                // 等宽必须按 options 长度算，不能用
                                                // parent.children.length
                                                readonly property int optCount: (gItem.modelData.options || []).length
                                                height: parent.height
                                                width: (parent.width - 3 * (optCount - 1)) / optCount
                                                radius: Theme.rInput - 3
                                                color: isOn ? Theme.cAccent : "transparent"
                                                Text {
                                                    anchors.centerIn: parent
                                                    text: modelData.label
                                                    font.family: Theme.fontFamily
                                                    font.pixelSize: 12
                                                    font.weight: Font.Medium
                                                    color: isOn ? Theme.cAccentText : Theme.cTextDim
                                                }
                                                MouseArea {
                                                    anchors.fill: parent
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: {
                                                        pane.setValue(gItem.modelData.key, modelData.value)
                                                        pane.submit("theme_switch", true)
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---------------- 字段区 ----------------
        Column {
            id: fieldsCol
            width: parent.width
            spacing: 12

            Repeater {
                id: repeater

                delegate: Column {
                    id: fieldWrap
                    required property var modelData
                    width: parent.width
                    spacing: Theme.sp6
                    visible: modelData.type !== "index"

                    // ---- 字段标签（左对齐，与输入框同一条左边界）----
                    Text {
                        visible: fieldWrap.modelData.type !== "list"
                                 && (fieldWrap.modelData.label !== ""
                                     || fieldWrap.modelData.key === "path")
                        text: fieldWrap.modelData.key === "path"
                              ? "文件" : fieldWrap.modelData.label
                        font.family: Theme.fontFamily
                        // M35 3.4：弹窗字段标签 10.5 → 11（仅此处，不动 Theme.fsLabel）
                        font.pointSize: Theme.pt(11)
                        font.weight: Font.DemiBold
                        color: fieldWrap.modelData.key === "reason"
                               ? Theme.cText2 : Theme.cTextDim
                    }

                    // ---- 文件卡片（§4.5：504×64，图标 28 + 名 + 路径）----
                    Rectangle {
                        visible: fieldWrap.modelData.key === "path"
                        width: parent.width
                        height: 64
                        radius: Theme.rCard
                        color: Theme.cSubtleBg
                        border.width: 1
                        border.color: Theme.cBorder

                        FileTypeIcon {
                            id: pathIcon
                            x: 14
                            anchors.verticalCenter: parent.verticalCenter
                            size: 28
                            kind: {
                                var v = String(fieldWrap.modelData.value || "")
                                var i = v.lastIndexOf(".")
                                return i >= 0 ? v.substring(i + 1) : ""
                            }
                        }
                        Text {
                            x: 52
                            y: 12
                            width: parent.width - 52 - 16
                            text: {
                                var v = String(fieldWrap.modelData.value || "")
                                if (v === "") return "选择或粘贴文件路径"
                                var parts = v.split(/[\\/]/)
                                return parts[parts.length - 1]
                            }
                            elide: Text.ElideMiddle
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(12.5)
                            font.weight: Font.DemiBold
                            color: fieldWrap.modelData.value ? Theme.cText
                                                             : Theme.cTextMute
                        }
                        TextField {
                            id: pathField
                            x: 52
                            y: 32
                            width: parent.width - 52 - 16 - 84
                            height: 22
                            text: fieldWrap.modelData.value || ""
                            placeholderText: "C:\\…\\文件.docx"
                            readOnly: fieldWrap.modelData.readonly === true
                            selectByMouse: true
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(Theme.fsLabel)
                            color: Theme.cTextDim
                            placeholderTextColor: Theme.cTextMute
                            background: null
                            onTextChanged: if (fieldWrap.modelData.key)
                                pane.setValue(fieldWrap.modelData.key, text)
                        }
                    }

                    // M50：路径字段的「选择…」（系统文件对话框，选完回填）
                    AppButton {
                        visible: fieldWrap.modelData.key === "path"
                                 && fieldWrap.modelData.readonly !== true
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        y: 26
                        height: 30
                        text: "选择…"
                        onClicked: controller.pickFileForField(
                                       fieldWrap.modelData.key)
                    }

                    // ---- 普通单行输入 ----
                    TextField {
                        visible: fieldWrap.modelData.type === "text"
                                 && fieldWrap.modelData.key !== "path"
                                 && fieldWrap.modelData.key !== "reason"
                        width: parent.width
                        height: 40
                        leftPadding: 12
                        rightPadding: 12
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fsBody
                        readOnly: fieldWrap.modelData.readonly === true
                        text: fieldWrap.modelData.value || ""
                        selectByMouse: true
                        color: Theme.cText
                        placeholderText: fieldWrap.modelData.hint || ""
                        placeholderTextColor: Theme.cTextMute
                        background: Rectangle {
                            color: Theme.cInputBg
                            // M80：聚焦用双环（1px 主色内框 + 3px 主色 18% 外环），
                            // 不再靠加粗边框——加粗会让文字整体位移 0.25px 且显脏。
                            border.width: 1
                            border.color: parent.activeFocus ? Theme.cAccent
                                                             : Theme.cInputBorder
                            radius: Theme.rInput
                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: -3
                                radius: parent.radius + 3
                                color: "transparent"
                                border.width: 3
                                border.color: Qt.rgba(Theme.cAccent.r,
                                                      Theme.cAccent.g,
                                                      Theme.cAccent.b, 0.18)
                                visible: parent.parent.activeFocus
                                z: -1
                            }
                        }
                        onTextChanged: if (fieldWrap.modelData.key)
                            pane.setValue(fieldWrap.modelData.key, text)
                    }

                    // ---- 修改原因：多行 + 默认聚焦 + 主色描边 + 外发光 ----
                    Item {
                        visible: fieldWrap.modelData.type === "textarea"
                                 || fieldWrap.modelData.key === "reason"
                        width: parent.width
                        height: 84

                        // 外发光（§4.7 焦点态 rgba(78,107,255,.22)）
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -3
                            radius: Theme.rInput + 3
                            color: "transparent"
                            border.width: 3
                            border.color: "#384E6BFF"
                            visible: reasonArea.activeFocus
                        }
                        TextArea {
                            id: reasonArea
                            anchors.fill: parent
                            topPadding: 12
                            bottomPadding: 24
                            leftPadding: 12
                            rightPadding: 12
                            wrapMode: TextArea.Wrap
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fsBody
                            color: Theme.cText
                            placeholderText: "写清楚改了什么，回滚时一眼就能找到"
                            placeholderTextColor: Theme.cTextMute
                            text: fieldWrap.modelData.value || ""
                            background: Rectangle {
                                color: Theme.cInputBg
                                border.width: reasonArea.activeFocus ? 1.5 : 1
                                border.color: reasonArea.activeFocus
                                              ? Theme.cAccent : Theme.cInputBorder
                                radius: Theme.rInput
                            }
                            Component.onCompleted: if (fieldWrap.modelData.key === "reason")
                                pane.reasonItem = reasonArea
                            onTextChanged: {
                                if (fieldWrap.modelData.key)
                                    pane.setValue(fieldWrap.modelData.key, text)
                                pane.reasonLen = text.length
                            }
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 12
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: Theme.sp6
                            text: reasonArea.text.length + " / 200"
                            font.family: Theme.fontFamily
                            font.pointSize: Theme.pt(Theme.fsNano)
                            font.features: { "tnum": 1 }
                            color: Theme.cTextMute
                        }
                    }

                    // ---- 分类下拉（504×40，右侧 12×12 箭头距右 12）----
                    AppComboBox {
                        id: combo
                        visible: fieldWrap.modelData.type === "combo"
                        width: parent.width
                        model: fieldWrap.modelData.options || []
                        currentIndex: (typeof fieldWrap.modelData.value
                                       === "number")
                                      ? fieldWrap.modelData.value : 0
                        onActivated: function(idx) {
                            pane.setValue(fieldWrap.modelData.key, idx)
                        }
                    }

                    // ---- list（只读清单）----
                    Rectangle {
                        visible: fieldWrap.modelData.type === "list"
                        width: parent.width
                        height: Math.min(120, 16 * (fieldWrap.modelData.value || []).length + 12)
                        color: Theme.cInputBg
                        border.color: Theme.cInputBorder
                        radius: Theme.rInput
                        clip: true
                        Column {
                            x: 12; y: 8
                            spacing: Theme.sp2
                            Repeater {
                                model: fieldWrap.modelData.value || []
                                Text {
                                    text: modelData
                                    font.family: Theme.fontFamily
                                    font.pointSize: Theme.pt(Theme.fsNano)
                                    color: Theme.cTextDim
                                }
                            }
                        }
                    }

                    // ---- hint（修改原因下方一行提示）----
                    Text {
                        visible: !!fieldWrap.modelData.hint
                                 && fieldWrap.modelData.key !== "path"
                        text: fieldWrap.modelData.hint || ""
                        font.family: Theme.fontFamily
                        font.pointSize: Theme.pt(Theme.fsNano)
                        color: Theme.cTextWeak
                    }
                }
            }
        }

        // ---------------- 版本对照条（§4.5 504×56）----------------
        Rectangle {
            visible: pane.isCommit
            width: parent.width
            height: 56
            radius: Theme.rCard
            color: Theme.cSubtleBg
            border.width: 1
            border.color: Theme.cBorder
            Column {
                x: 14
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.sp2
                Text {
                    text: "保存为新版本"
                    font.family: Theme.fontFamily
                    font.pointSize: Theme.pt(12.5)
                    font.weight: Font.DemiBold
                    color: Theme.cText
                }
                Text {
                    text: "新快照 · 存入「" + pane.categoryLabel() + "」"
                    font.family: Theme.fontFamily
                    font.pointSize: Theme.pt(Theme.fsLabel)
                    color: Theme.cTextDim
                }
            }
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                width: 46
                height: 24
                radius: 8
                color: Theme.cAccentBg
                Text {
                    anchors.centerIn: parent
                    text: "新版本"
                    font.family: Theme.fontFamily
                    font.pointSize: Theme.pt(Theme.fsNano)
                    font.weight: Font.DemiBold
                    color: Theme.cAccent
                }
            }
        }

    }
    }   // ← 关闭 M99 的 Flickable（内容区滚动容器）

    // M99：页脚固定在弹窗底部——长弹窗滚动时按钮始终可见。
    // （早先把页脚留在滚动内容里，小屏上滚动后底部按钮会被滚出可视区，
    //   看起来像内容被切断。）
    Item { width: 1; height: 2 }

    // ---------------- 页脚 ----------------
    // M31：无按钮的弹窗（设置：只留右上 ×）整条页脚收起
    Item {
        id: footBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 24
        anchors.rightMargin: 24
        anchors.bottomMargin: 24
        height: (pane.isCommit || btnRepeater.count > 0) ? 38 : 0
        visible: height > 0

        Text {
            visible: pane.isCommit
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "Ctrl + Enter 快速保存"
            font.family: Theme.fontFamily
            font.pointSize: Theme.pt(Theme.fsLabel)
            color: Theme.cTextMute
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            layoutDirection: Qt.LeftToRight

            Repeater {
                id: btnRepeater

                delegate: AppButton {
                    required property var modelData
                    text: modelData.label
                    enabled: pane.okEnabled(modelData)
                    primary: modelData.accent === true
                    danger: modelData.danger === true
                    height: 38
                    width: pane.isCommit
                           ? (modelData.accent === true ? 110 : 88)
                           : Math.max(88, implicitWidth)
                    onClicked: pane.submit(modelData.key)
                }
            }
        }
    }

    // M35 5.1：字符「×」换矢量图标（Dialog 直接子项，避免被 Column 布局接管）
    Item {
        id: closeBtn
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.rightMargin: 16
        anchors.topMargin: 16
        width: 24
        height: 24
        z: 10
        GlyphIcon {
            anchors.centerIn: parent
            name: "close"
            size: 14
            iconColor: closeMa.containsMouse ? Theme.cText : Theme.cTextDim
        }
        MouseArea {
            id: closeMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: pane.submit("cancel")
        }
    }
}
