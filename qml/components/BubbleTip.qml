// BubbleTip —— M35 §4.11 悬停气泡（UI 验收评审 4.1）：
// 11px/Medium、深底 #0F1A33 白字、圆角 8、无描边、内边距 8×14；
// 淡入 150ms、悬停 600ms 后出现（600ms 延迟由调用方 Timer 把关，
// show 由调用方驱动——与既有 tooltipTimer 模式一致）。
// 用法：
//   Timer { interval: 600; running: ma.containsMouse && !ma.pressed
//            onTriggered: tipShow = true; onRunningChanged: if (!running) tipShow = false }
//   BubbleTip { show: tipShow && tipText !== ""; tip: tipText }
import QtQuick
import QtQuick.Controls
import QtQuick.Window
import ".."

pragma ComponentBehavior: Bound

Popup {
    id: bubble
    property string tip: ""
    property bool show: false
    visible: show && tip !== ""
    padding: 0
    // M52：气泡跟随主题——浅色下不再是突兀的深蓝块，改用与卡片同调的白底 + 细描边
    background: Rectangle {
        color: Theme.cBubbleBg
        radius: 10
        border.width: 1
        border.color: Theme.cBubbleBorder
    }
    contentItem: Text {
        text: bubble.tip
        width: Math.min(implicitWidth, 240)
        wrapMode: Text.Wrap
        font.family: Theme.fontFamily
        font.pixelSize: 12
        font.weight: Font.Medium
        lineHeight: 1.25
        color: Theme.cText
        leftPadding: 12
        rightPadding: 12
        topPadding: 8
        bottomPadding: 8
    }
    // M81：原来只有 150ms 淡入、曲线是默认 Linear；补上减速曲线
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1
                          duration: 150
                          easing.bezierCurve: Theme.easeDecel }
    }
    // 定位：父项下方 8px 居中；贴近窗口底边时翻到父项上方
    x: Math.round((parent.width - width) / 2)
    y: {
        const below = parent.height + 8
        const w = parent ? parent.Window.window : null
        if (w) {
            const tl = parent.mapToItem(w.contentItem, 0, below)
            if (tl.y + bubble.height > w.height - 8)
                return -bubble.height - 8
        }
        return below
    }
}
