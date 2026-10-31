// FileTypeIcon —— 22×22 文件类型图标（规格 §2.4 / §4.3）。
// ⚠️ 打包 spec 裁剪了 QtSvg（build_pjm_qml.spec `_TRIM_PATTERNS` 含 PySide6/QtSvg），
// 所以这里用纯 QML 形状绘制，不放 SVG 资源，避免产物里图标全空。
// 编码：类型底色 + 白纸 + 图形色线条；IMG 用圆点 + 山形。
import QtQuick
import ".."

Item {
    id: root
    property string kind: ""      // docx / xlsx / pptx / pdf / png / txt …
    property int size: 22

    implicitWidth: size
    implicitHeight: size

    readonly property string type: {
        var k = String(root.kind || "").toLowerCase()
        if (k === "docx" || k === "doc") return "DOCX"
        if (k === "xlsx" || k === "xls" || k === "csv") return "XLSX"
        if (k === "pptx" || k === "ppt" || k === "pps") return "PPTX"
        if (k === "pdf") return "PDF"
        if (k === "png" || k === "jpg" || k === "jpeg" || k === "gif"
                || k === "bmp" || k === "webp" || k === "svg" || k === "ico")
            return "IMG"
        return "TXT"
    }

    readonly property color bgColor: {
        switch (type) {
        case "DOCX": return Theme.cTypeDocxBg
        case "XLSX": return Theme.cTypeXlsxBg
        case "PPTX": return Theme.cTypePptxBg
        case "PDF":  return Theme.cTypePdfBg
        case "IMG":  return Theme.cTypeImgBg
        default:     return Theme.cTypeTxtBg
        }
    }
    readonly property color fgColor: {
        switch (type) {
        case "DOCX": return Theme.cTypeDocxFg
        case "XLSX": return Theme.cTypeXlsxFg
        case "PPTX": return Theme.cTypePptxFg
        case "PDF":  return Theme.cTypePdfFg
        case "IMG":  return Theme.cTypeImgFg
        default:     return Theme.cTypeTxtFg
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: root.size >= 40 ? 13 : 7
        color: root.bgColor

        // 白纸
        Rectangle {
            id: page
            anchors.centerIn: parent
            width: Math.round(root.size * 0.46)
            height: Math.round(root.size * 0.58)
            radius: Math.max(2, Math.round(root.size * 0.10))
            color: "#FFFFFF"
            border.width: root.size <= 28 ? 0.5 : 1
            border.color: Qt.rgba(root.fgColor.r, root.fgColor.g,
                                  root.fgColor.b, 0.22)

            // 左侧竖条（标识里的青色竖条语义 → 类型色）
            Rectangle {
                visible: root.type !== "IMG"
                x: Math.round(page.width * 0.20)
                y: Math.round(page.height * 0.18)
                width: Math.max(1.5, root.size * 0.09)
                height: Math.round(page.height * 0.64)
                radius: width / 2
                color: root.fgColor
            }
            // 两条内容线
            Rectangle {
                visible: root.type !== "IMG"
                x: Math.round(page.width * 0.48)
                y: Math.round(page.height * 0.30)
                width: Math.round(page.width * 0.34)
                height: Math.max(1, root.size * 0.06)
                radius: height / 2
                color: root.fgColor
                opacity: 0.75
            }
            Rectangle {
                visible: root.type !== "IMG"
                x: Math.round(page.width * 0.48)
                y: Math.round(page.height * 0.52)
                width: Math.round(page.width * 0.24)
                height: Math.max(1, root.size * 0.06)
                radius: height / 2
                color: root.fgColor
                opacity: 0.55
            }
            // 图片类型：圆点 + 山形
            Rectangle {
                visible: root.type === "IMG"
                anchors.top: page.top
                anchors.topMargin: Math.round(page.height * 0.24)
                anchors.left: page.left
                anchors.leftMargin: Math.round(page.width * 0.22)
                width: Math.max(2, root.size * 0.12)
                height: width
                radius: width / 2
                color: root.fgColor
            }
            Rectangle {
                visible: root.type === "IMG"
                anchors.bottom: page.bottom
                anchors.bottomMargin: Math.round(page.height * 0.18)
                anchors.horizontalCenter: page.horizontalCenter
                width: Math.round(page.width * 0.52)
                height: Math.round(page.width * 0.36)
                radius: 1
                color: root.fgColor
                opacity: 0.85
            }
        }
    }
}
