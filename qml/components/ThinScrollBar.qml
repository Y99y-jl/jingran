import QtQuick
import QtQuick.Controls.Basic
import ".."

// 细胶囊滚动条（规格 §4.7）：轨道透明、滑块 6px 圆角、hover 加深。
// ⚠️ 1 物理像素吸附逻辑在调用方（表头竖线已删除，本组件只负责轨道观感）。
ScrollBar {
    id: bar
    policy: ScrollBar.AsNeeded
    // M83：原来是 padding 3 + 8px 滑块 = 14px 的可交互宽度，
    // 行右边缘 14px 内按下都会被它吃掉（分类名长时用户正好往右挪 -> 误触）。
    // 收到 padding 1 + 6px = 8px：仍够点，但不抢行的拖拽。
    padding: 1
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: 3
        color: bar.pressed ? Theme.cAccent
             : bar.hovered ? Theme.cScrollThumbHover : Theme.cScrollThumb
        opacity: (bar.hovered || bar.pressed || (bar.parent && bar.parent.moving)) ? 1.0 : 0.5
        Behavior on opacity { NumberAnimation { duration: Theme.durHover
                                              easing.bezierCurve: Theme.easeStandard } }
    }
    background: null
}
