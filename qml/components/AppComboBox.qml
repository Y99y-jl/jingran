// AppComboBox —— 统一风格下拉 + 可输入过滤（M75-5）
//
// 为什么不用 Controls.Basic 的 ComboBox：
//   · 点控件任意位置都会展开，而「移动到分类…」需要的是「点输入框能打字、
//     点右侧箭头才展开」；
//   · editable 模式的 contentItem 由 ComboBox 自己接管，外面塞 TextField 会
//     和它的 editText 双向同步打架；
//   · 展开后的候选列表是系统默认白底方块，和卡片语言不搭（深色模式刺眼）。
//
// 这里用 Item 自绘，接口保持与 ComboBox 一致（model / currentIndex /
// activated / currentText / font.pixelSize），因此原有调用点无需改动。
import QtQuick
import QtQuick.Controls.Basic
import ".."

Item {
    id: cb

    // ---- 兼容原 ComboBox 的对外接口 ----
    property var model: []
    property int currentIndex: (model && model.length) ? 0 : -1
    signal activated(int index)
    property font font: Qt.font({
        family: Theme.fontFamily,
        pixelSize: Theme.fsBody
    })
    /** 是否允许直接在框里打字过滤（默认开：分类名可以直接搜）。 */
    property bool searchable: true
    /** 未选中时的占位文案。 */
    property string placeholder: ""

    height: 40
    implicitHeight: 40

    readonly property int count: model ? model.length : 0
    readonly property string currentText:
        (currentIndex >= 0 && currentIndex < count) ? _textAt(currentIndex) : ""

    // 输入框里正在编辑的文字；不编辑时跟随 currentText
    property string editText: ""
    property bool _editing: false
    // 过滤后的真实索引（JS 数组，直接当 ListView 的 model 用）
    property var visibleIdx: []

    /// 取第 i 项显示文本（字符串数组 / 对象数组的 label 字段都支持）。
    function _textAt(i) {
        var m = cb.model
        if (!m || i < 0 || i >= m.length) return ""
        var item = m[i]
        if (item === undefined || item === null) return ""
        if (typeof item === "object") return String(item.label ?? "")
        return String(item)
    }

    /// 按关键字重算可见索引；空关键字 = 全部。
    function _refilter(q) {
        var key = String(q || "").trim().toLowerCase()
        var out = []
        for (var i = 0; i < cb.count; i++) {
            if (!key || _textAt(i).toLowerCase().indexOf(key) >= 0) out.push(i)
        }
        visibleIdx = out
    }

    function openPopup(showAll) {
        if (showAll) _refilter("")
        else _refilter(cb.editText)
        if (visibleIdx.length === 0) return
        popup.open()
    }

    function _commit(idx) {
        cb.currentIndex = idx
        cb.editText = _textAt(idx)
        cb._editing = false
        cb.activated(idx)
        popup.close()
    }

    onCurrentIndexChanged: if (!_editing) editText = currentText
    onModelChanged: Qt.callLater(function () { _refilter(""); if (!_editing) editText = currentText })
    Component.onCompleted: {
        _refilter("")
        editText = currentText
    }

    // ---- 外框 ----
    Rectangle {
        id: box
        anchors.fill: parent
        color: Theme.cInputBg
        border.width: 1
        border.color: input.activeFocus ? Theme.cAccent : Theme.cInputBorder
        radius: Theme.rInput

        // M80：聚焦双环（与顶栏搜索、弹窗输入框同一套语言）
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: parent.radius + 3
            color: "transparent"
            border.width: 3
            border.color: Qt.rgba(Theme.cAccent.r, Theme.cAccent.g,
                                  Theme.cAccent.b, 0.18)
            visible: input.activeFocus
            z: -1
        }
    }

    // ---- 文字区：可聚焦、可输入 ----
    TextInput {
        id: input
        anchors.left: parent.left
        anchors.right: arrow.left
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 12
        anchors.rightMargin: Theme.sp6
        verticalAlignment: TextInput.AlignVCenter
        font: cb.font
        color: Theme.cText
        clip: true
        readOnly: !cb.searchable
        selectByMouse: true

        text: cb.editText

        // 未编辑时的占位
        Text {
            anchors.fill: parent
            verticalAlignment: Text.AlignVCenter
            visible: input.text.length === 0 && cb.placeholder.length > 0
            text: cb.placeholder
            font: cb.font
            color: Theme.cTextMute
        }

        onTextEdited: {
            cb._editing = true
            cb.editText = text
            cb._refilter(text)
            if (cb.visibleIdx.length > 0 && !popup.opened) popup.open()
            else if (cb.visibleIdx.length === 0) popup.close()
        }
        onActiveFocusChanged: {
            if (!activeFocus) {
                // 失焦：放弃未提交的输入，回到当前选中项
                cb._editing = false
                cb.editText = cb.currentText
                popup.close()
            }
        }
        Keys.onDownPressed: {
            if (!popup.opened) cb.openPopup(true)
            else popup.moveHighlight(1)
        }
        Keys.onUpPressed: {
            if (popup.opened) popup.moveHighlight(-1)
        }
        Keys.onReturnPressed: {
            if (popup.opened && popup.highlight >= 0
                    && popup.highlight < cb.visibleIdx.length)
                cb._commit(cb.visibleIdx[popup.highlight])
            else
                cb.openPopup(true)
        }
        Keys.onEscapePressed: {
            cb._editing = false
            cb.editText = cb.currentText
            popup.close()
        }
    }

    // ---- 右侧箭头：只有点它才展开 ----
    Item {
        id: arrow
        width: 34
        height: parent.height
        anchors.right: parent.right

        GlyphIcon {
            anchors.centerIn: parent
            name: "chevron"
            size: 14
            iconColor: Theme.cTextDim
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (popup.opened) {
                    popup.close()
                } else {
                    cb._editing = false
                    cb.editText = cb.currentText
                    cb.openPopup(true)
                    input.forceActiveFocus()
                }
            }
        }
    }

    // ---- 弹层 ----
    Popup {
        id: popup
        y: cb.height + 6
        width: cb.width
        padding: Theme.sp6
        property int highlight: -1
        implicitHeight: Math.min(cb.visibleIdx.length * 34 + 12, 280)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        // M81：下拉进场（与右键菜单同一套时长/曲线）
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

        function moveHighlight(d) {
            var n = cb.visibleIdx.length
            if (n === 0) return
            highlight = Math.max(0, Math.min(n - 1, highlight + d))
            list.positionViewAtIndex(highlight, ListView.Contain)
        }

        onOpened: highlight = cb.visibleIdx.indexOf(cb.currentIndex)
        onClosed: highlight = -1

        background: Rectangle {
            color: Theme.cFloatBg
            radius: Theme.rInput + 2
            border.width: 1
            border.color: Theme.cFloatBorder
        }

        contentItem: ListView {
            id: list
            clip: true
            model: cb.visibleIdx
            currentIndex: popup.highlight
            boundsBehavior: Flickable.StopAtBounds

            delegate: Rectangle {
                id: row
                required property var modelData      // 真实索引
                required property int index          // 可见序号

                width: ListView.view.width
                height: 34
                radius: 8
                color: hov.containsMouse || index === popup.highlight
                       ? Theme.cRowHover : "transparent"

                Text {
                    x: 10
                    width: parent.width - 20
                    anchors.verticalCenter: parent.verticalCenter
                    text: cb._textAt(row.modelData)
                    elide: Text.ElideRight
                    font: cb.font
                    color: Theme.cText
                }
                MouseArea {
                    id: hov
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: cb._commit(row.modelData)
                }
            }
        }
    }
}
