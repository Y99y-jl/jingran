// GlyphIcon —— M35 字符图标替换（UI 验收评审 5.1：▾/⊠/☀/☾ 等字符当图标
// 全部换矢量绘制）。全部用 QML 图元/Canvas 现场绘制，无字体依赖（字符
// 「⌄」在缺字形字体里渲染成 ⊠ 的事故根因即字体依赖），color 绑定 Theme
// 令牌，深浅主题 + 选中态自动跟随。
//
// 用法：GlyphIcon { name: "close"; size: 14; iconColor: Theme.cTextDim }
// 支持 name：chevron / close / plus / search / dots / star / starOff
//            / sun / moon / list / diamond
import QtQuick

Item {
    id: g

    property string name: "close"
    property real size: 14
    property color iconColor: "#7C8AA5"

    implicitWidth: size
    implicitHeight: size
    visible: name !== ""

    onIconColorChanged: { canvas1.requestPaint(); canvasSun.requestPaint();
                         canvasChevron.requestPaint() }

    // ---------- 矢量路径类（star / moon）----------
    Canvas {
        id: canvas1
        visible: g.name === "star" || g.name === "starOff" || g.name === "moon"
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var cx = width / 2, cy = height / 2
            if (g.name === "star" || g.name === "starOff") {
                var R = width * 0.48, r = width * 0.20
                ctx.beginPath()
                for (var i = 0; i < 10; i++) {
                    var rad = (i % 2 === 0) ? R : r
                    var a = -Math.PI / 2 + i * Math.PI / 5
                    var x = cx + rad * Math.cos(a)
                    var y = cy + rad * Math.sin(a) + width * 0.03
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
                }
                ctx.closePath()
                if (g.name === "star") {
                    ctx.fillStyle = g.iconColor
                    ctx.fill()
                } else {
                    ctx.strokeStyle = g.iconColor
                    ctx.lineWidth = Math.max(1.2, width * 0.09)
                    ctx.stroke()
                }
            } else if (g.name === "moon") {
                var R2 = width * 0.40
                ctx.fillStyle = g.iconColor
                ctx.beginPath()
                ctx.arc(cx + width * 0.06, cy, R2, 0, Math.PI * 2)
                ctx.fill()
                ctx.globalCompositeOperation = "destination-out"
                ctx.beginPath()
                ctx.arc(cx + width * 0.34, cy - width * 0.10, R2 * 0.94,
                        0, Math.PI * 2)
                ctx.fill()
                ctx.globalCompositeOperation = "source-over"
            }
        }
        Component.onCompleted: requestPaint()
    }

    // ---------- chevron（⌄）：一条连续折线 ----------
    // M69：原来用两段旋转矩形拼，两条臂长度/起点不一致，渲染出来
    // 像“坏图标”（右臂长、底部不对齐）。改为一笔折线，天然对称。
    Canvas {
        id: canvasChevron
        visible: g.name === "chevron"
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var w = width, h = height
            if (w <= 0 || h <= 0) return
            ctx.strokeStyle = g.iconColor
            ctx.lineWidth = Math.max(1.4, w * 0.13)
            ctx.lineCap = "round"
            ctx.lineJoin = "round"
            ctx.beginPath()
            ctx.moveTo(w * 0.22, h * 0.38)
            ctx.lineTo(w * 0.50, h * 0.64)
            ctx.lineTo(w * 0.78, h * 0.38)
            ctx.stroke()
        }
    }

    // ---------- close（×）----------
    Item {
        visible: g.name === "close"
        anchors.fill: parent
        Rectangle {
            width: parent.width * 0.78
            height: Math.max(1.4, parent.width * 0.11)
            radius: height / 2
            color: g.iconColor
            anchors.centerIn: parent
            rotation: 45
        }
        Rectangle {
            width: parent.width * 0.78
            height: Math.max(1.4, parent.width * 0.11)
            radius: height / 2
            color: g.iconColor
            anchors.centerIn: parent
            rotation: -45
        }
    }

    // ---------- plus（＋）----------
    Item {
        visible: g.name === "plus"
        anchors.fill: parent
        Rectangle {
            width: parent.width * 0.66
            height: Math.max(1.5, parent.width * 0.13)
            radius: height / 2
            color: g.iconColor
            anchors.centerIn: parent
        }
        Rectangle {
            width: Math.max(1.5, parent.width * 0.13)
            height: parent.width * 0.66
            radius: width / 2
            color: g.iconColor
            anchors.centerIn: parent
        }
    }

    // ---------- search（⌕）：圆 + 手柄 ----------
    Item {
        visible: g.name === "search"
        anchors.fill: parent
        Rectangle {
            width: parent.width * 0.62
            height: parent.width * 0.62
            radius: width / 2
            color: "transparent"
            border.width: Math.max(1.3, parent.width * 0.10)
            border.color: g.iconColor
            x: parent.width * 0.10
            y: parent.height * 0.10
        }
        Rectangle {
            width: parent.width * 0.30
            height: Math.max(1.3, parent.width * 0.10)
            radius: height / 2
            color: g.iconColor
            x: parent.width * 0.62
            y: parent.height * 0.70
            rotation: 45
            transformOrigin: Item.Left
        }
    }

    // ---------- dots（⋯）：三点 ----------
    Item {
        visible: g.name === "dots"
        anchors.fill: parent
        Row {
            anchors.centerIn: parent
            spacing: parent.width * 0.16
            Repeater {
                model: 3
                Rectangle {
                    width: Math.max(1.8, g.width * 0.12)
                    height: width
                    radius: width / 2
                    color: g.iconColor
                }
            }
        }
    }

    // ---------- sun（☀）：日轮 + 八射线（Canvas，避开多 transform 顺序歧义）----------
    Canvas {
        id: canvasSun
        visible: g.name === "sun"
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var cx = width / 2, cy = height / 2
            var R = width * 0.26
            ctx.strokeStyle = g.iconColor
            ctx.fillStyle = g.iconColor
            ctx.lineWidth = Math.max(1.2, width * 0.09)
            ctx.lineCap = "round"
            ctx.beginPath()
            ctx.arc(cx, cy, R, 0, Math.PI * 2)
            ctx.fill()
            for (var i = 0; i < 8; i++) {
                var a = i * Math.PI / 4
                ctx.beginPath()
                ctx.moveTo(cx + Math.cos(a) * R * 1.45, cy + Math.sin(a) * R * 1.45)
                ctx.lineTo(cx + Math.cos(a) * width * 0.47,
                           cy + Math.sin(a) * width * 0.47)
                ctx.stroke()
            }
        }
        Component.onCompleted: requestPaint()
    }

    // ---------- list（▤）：三条横杠 ----------
    Item {
        visible: g.name === "list"
        anchors.fill: parent
        Column {
            anchors.centerIn: parent
            spacing: parent.height * 0.20
            Repeater {
                model: 3
                Rectangle {
                    width: g.width * 0.72
                    height: Math.max(1.5, g.width * 0.13)
                    radius: height / 2
                    color: g.iconColor
                }
            }
        }
    }

    // ---------- diamond（◇）：旋转方片 ----------
    Item {
        visible: g.name === "diamond"
        anchors.fill: parent
        Rectangle {
            width: parent.width * 0.66
            height: parent.width * 0.66
            radius: Math.max(1.5, parent.width * 0.10)
            color: "transparent"
            border.width: Math.max(1.3, parent.width * 0.10)
            border.color: g.iconColor
            anchors.centerIn: parent
            rotation: 45
        }
    }
}
