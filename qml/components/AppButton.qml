// AppButton —— V3 统一按钮（规格 §4.6）。
//   primary  : 主按钮 高 38（顶栏 30）、圆角 10（Theme.rBtnPrimary）、渐变
//              Theme.cPrimaryA→cPrimaryB、白字 12.5 SemiBold；
//              默认无阴影（定稿 #2：M35 已去彩色光晕）
//   soft     : 浅底按钮 高 40、#EBF0FF、主色字 12/SemiBold（导出文件）
//   danger   : 危险文字按钮 白底 + 1px 边 + #E5484D 字（回滚 / 删除）
//   默认      : 次按钮 白 80% + 1px #DCE3EF、次级色 12.5/Medium
//   iconOnly : 图标按钮 28×28（顶栏）/ 26×26，圆角 9，无底色，hover 才出现白 8%
// 铁律：文字水平 + 垂直居中，左右内边距相等（§4.6 / §5）。
import QtQuick
import QtQuick.Controls.Basic
import ".."

Button {
    id: control
    property bool primary: false
    property bool soft: false
    property bool danger: false
    property string tip: ""
    property string iconSrc: ""
    property int iconSize: 18
    readonly property bool iconOnly: iconSrc !== "" && text === ""
    // 允许调用方显式指定宽高（顶栏 116×30 / 图标 28×28 / 弹窗 88×38）
    property int btnHeight: 38

    implicitHeight: btnHeight
    implicitWidth: iconOnly ? btnHeight : (content.implicitWidth + 32)

    leftPadding: iconOnly ? 0 : 16
    rightPadding: iconOnly ? 0 : 16
    hoverEnabled: true
    font.family: Theme.fontFamily
    font.pointSize: Theme.pt(12.5)
    font.weight: primary || soft ? Font.DemiBold : Font.Medium
    opacity: enabled ? 1 : 1          // §6：禁用不做半透明，只换底色/字色

    background: Item {
        Rectangle {
            id: body
            anchors.fill: parent
            radius: control.iconOnly ? 9 : (control.primary ? Theme.rBtnPrimary : Theme.rBtn)
            color: {
                if (!control.enabled) return Theme.cDisabledBg
                if (control.primary) return "transparent"
                // M42b：图标按钮按设计应「无底色」，悬停只由下方 8% 白叠层表达。
                // 旧实现让它照普通按钮铺 cBtnBg/cBtnHover 实色 + 描边，
                // 深色模式下鼠标一停上去就是一块突兀的亮方块（用户两次反馈）。
                if (control.iconOnly) return "transparent"
                if (control.soft) return Theme.cAccentBg
                if (control.danger) return control.hovered ? Theme.cDangerSoft
                                                           : "transparent"
                return control.pressed ? Theme.cBtnPress
                     : control.hovered ? Theme.cBtnHover : Theme.cBtnBg
            }
            border.width: (control.primary || control.iconOnly) ? 0 : 1
            border.color: control.danger ? Theme.cDanger : Theme.cBorder
            gradient: control.primary && control.enabled ? grad : null
            Behavior on color { ColorAnimation { duration: Theme.durHover
                                             easing.bezierCurve: Theme.easeStandard } }

            Gradient {
                id: grad
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.cPrimaryA }
                GradientStop { position: 1.0; color: Theme.cPrimaryB }
            }
        }
        // 图标按钮 hover 底（白 8% / 浅色 #F4F6FA）
        Rectangle {
            visible: control.iconOnly && control.hovered && control.enabled
            anchors.fill: parent
            radius: 9
            color: Theme.cBtnHover
        }
    }

    contentItem: Item {
        id: content
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent          // §5：按钮文字必须居中
            spacing: Theme.sp6
            Image {
                visible: control.iconSrc !== ""
                source: control.iconSrc
                width: control.iconSize
                height: control.iconSize
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: control.text !== ""
                text: control.text
                font: control.font
                verticalAlignment: Text.AlignVCenter
                color: !control.enabled ? Theme.cDisabledFg
                     : control.primary ? Theme.cAccentText
                     : control.danger ? Theme.cDanger
                     : control.soft ? Theme.cAccent
                     : Theme.cText2
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
    // M35 §4.11：ToolTip 换 BubbleTip（11px 深底白字气泡），600ms 延迟
    property bool tipShow: false
    Timer {
        interval: 600
        running: control.hovered && control.tip !== "" && !control.pressed
        onTriggered: control.tipShow = true
        // M51：Timer 触发后 running 会自动变 false，这里必须再看 hovered，
        // 否则 onRunningChanged 会立刻把刚弹出的气泡关掉（真凶）
        onRunningChanged: if (!running && !control.hovered)
                              control.tipShow = false
    }
    // 移开/按下立即收起（onRunningChanged 在部分平台收不到 leave）
    onHoveredChanged: if (!hovered) tipShow = false
    onPressedChanged: if (pressed) tipShow = false
    BubbleTip { show: control.tipShow && control.tip !== ""; tip: control.tip }
}
