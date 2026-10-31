import QtQuick
import QtQuick.Controls.Basic
import ".."
import "../components"

// 版本对比窗（H1–H3，M4；M33 改为 Main 驱动）。
// 数据流：controller.diffReady → Main.showDiff(payloadJson) →
//         本窗 applyPayload(payloadJson)。窗口常驻单例，不再自连信号。
Window {
    id: dlg
    objectName: "diffDialog"
    visible: false
    width: 880
    height: 560
    title: "版本对比"
    // M35 4.2：窗口四角透出桌面，圆角由内层 Rectangle 画（原生标题栏保留）
    color: "transparent"

    property string fileName: ""
    property string kind: ""          // text / binary / same_text
    property var payload: ({})
    property var labels: []
    property var ids: []

    // M33：由 Main.showDiff 主动调用（旧：自带 Connections 收已发射信号=空窗）
    function applyPayload(payloadJson) {
        var p = JSON.parse(payloadJson)
        dlg.payload = p
        dlg.kind = p.kind
        dlg.fileName = p.fileName || ""
        rowsModel.clear()
        var nos = JSON.parse(controller.diffVersionNos(
            JSON.stringify([p.va ? p.va.id : "", p.vb ? p.vb.id : ""])))
        dlg.labels = nos.labels
        dlg.ids = nos.ids
        if (p.kind === "text") {
            for (var i = 0; i < p.rows.length; i++) {
                var r = p.rows[i]
                rowsModel.append({
                    kind: r.kind, oldNo: String(r.oldNo || ""),
                    newNo: String(r.newNo || ""), text: r.text,
                    wa: r.wa || null, wb: r.wb || null
                })
            }
            // M35 4.2：双色 span——绿=增、红=删（琥珀只用于 rep 行）
            countLbl.text = '<span style="color:' + Theme.cIns + '">+' + p.counts.ins + '</span>'
                          + ' <span style="color:' + Theme.cDanger + '">−' + p.counts.del + '</span>'
            noteLbl.text = p.note || ""
        } else if (p.kind === "binary") {
            countLbl.text = ""
            noteLbl.text = p.note || "非文本文件的对比只能看到大小与指纹变化，不会读取文件内容"
        } else {
            countLbl.text = ""
            noteLbl.text = ""
        }
        // 两端下拉默认落在本次对比的旧端/新端（M33）
        for (var k = 0; k < dlg.ids.length; k++) {
            if (p.va && dlg.ids[k] === p.va.id) cbA.currentIndex = k
            if (p.vb && dlg.ids[k] === p.vb.id) cbB.currentIndex = k
        }
    }

    // M35 4.2：窗口套圆角 14——Window 已透明，四角透出桌面；原生标题栏保留
    Rectangle {
        anchors.fill: parent
        anchors.margins: Theme.sp6
        radius: 14
        color: Theme.cPanel
        clip: true

        Column {
            anchors.fill: parent
            anchors.margins: 12
            spacing: Theme.sp6

            Row {
                spacing: 8
                // M35 4.2：标题 13px SemiBold（原 20px Bold）
                Text { text: "版本对比" + (dlg.fileName ? " — " + dlg.fileName : "")
                       font.pixelSize: 13; font.weight: Font.DemiBold; color: Theme.cText }
                Text { text: "差异在本机计算，不会上传"
                       font.pixelSize: Theme.fsLabel; color: Theme.cTextDim }
                Item { width: 20; height: 1 }
                // M35 4.2：+N −M 胶囊徽标（门禁探针按 objectName "diffCount" 查找）
                Rectangle {
                    radius: 9
                    height: 22
                    color: Theme.cChipBg
                    width: countLbl.implicitWidth + 20
                    Text {
                        id: countLbl
                        objectName: "diffCount"
                        anchors.centerIn: parent
                        textFormat: Text.RichText
                        font.family: Theme.numFamily
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }
            }

            // H3：两端下拉 + 重新计算
            Row {
                spacing: Theme.sp6
                Text { text: "旧端"; font.pixelSize: Theme.fsMeta; color: Theme.cTextDim; anchors.verticalCenter: parent.verticalCenter }
                AppComboBox {
                    id: cbA
                    width: 96
                    height: 30
                    model: dlg.labels
                    font.pixelSize: Theme.fsMeta
                    searchable: false      // 版本号短，不需要打字过滤
                }
                Text { text: "新端"; font.pixelSize: Theme.fsMeta; color: Theme.cTextDim; anchors.verticalCenter: parent.verticalCenter }
                AppComboBox {
                    id: cbB
                    width: 96
                    height: 30
                    model: dlg.labels
                    font.pixelSize: Theme.fsMeta
                    searchable: false
                }
                AppButton {
                    text: "重新对比"
                    onClicked: {
                        if (dlg.ids.length && cbA.currentIndex >= 0 && cbB.currentIndex >= 0)
                            controller.diffRequest(dlg.ids[cbA.currentIndex],
                                                   dlg.ids[cbB.currentIndex])
                    }
                }
            }

            // 横幅（H2：相同指纹 → 两份快照完全相同）
            Rectangle {
                width: parent.width
                height: (dlg.kind === "same_text") ? 32 : 0
                visible: dlg.kind === "same_text"
                color: Theme.cSelectBg
                radius: 8
                Text {
                    anchors.centerIn: parent
                    text: "两份快照完全相同"
                    font.pixelSize: Theme.fsBody
                    color: Theme.cText
                }
            }

            // H2 二进制降级档：五行元数据对照（大小/指纹/时间/原因/来源）
            Rectangle {
                width: parent.width
                height: dlg.kind === "binary" ? binGrid.implicitHeight + 16 : 0
                visible: dlg.kind === "binary"
                color: "transparent"

                Grid {
                    id: binGrid
                    columns: 3
                    columnSpacing: 24
                    rowSpacing: 4
                    Repeater {
                        model: dlg.kind === "binary" ? [
                            {k: "版本时间", a: (dlg.payload.va ? (dlg.payload.va.time || "").slice(0, 16) : "—"),
                             b: (dlg.payload.vb ? (dlg.payload.vb.time || "").slice(0, 16) : "—")},
                            {k: "修改原因", a: (dlg.payload.va ? (dlg.payload.va.reason || "") : "—"),
                             b: (dlg.payload.vb ? (dlg.payload.vb.reason || "") : "—")},
                            {k: "意见来源", a: (dlg.payload.va ? (dlg.payload.va.source || "") || "（未填写）" : "—"),
                             b: (dlg.payload.vb ? (dlg.payload.vb.source || "") || "（未填写）" : "—")}
                        ] : []
                        Text { text: modelData.k; font.pixelSize: Theme.fsMeta; color: Theme.cTextDim; width: 80 }
                        Text { text: modelData.a; font.pixelSize: Theme.fsMeta; color: Theme.cText; width: 260; elide: Text.ElideRight }
                        Text { text: modelData.b; font.pixelSize: Theme.fsMeta; color: Theme.cText; width: 260; elide: Text.ElideRight }
                    }
                }
            }

            // H2 行内单模式：行底色 + 词级加粗下划线 span
            ListView {
                id: diffList
                width: parent.width
                height: parent.height - 120
                clip: true
                model: rowsModel
                boundsBehavior: Flickable.StopAtBounds
                visible: dlg.kind === "text"
                ScrollBar.vertical: ThinScrollBar {}
                // M35 4.2：染色行是圆角 8 整块、左右各让 6、不再通宽。
                // 注意：ListView 会把 delegate 自身的 x 强制归零（实测
                // x:6 被覆盖成 0），缩进必须由内层 Rectangle 承载。
                delegate: Item {
                    width: diffList.width
                    height: 20
                    Rectangle {
                        x: 6
                        width: parent.width - 12
                        height: parent.height
                        radius: 8
                        // M35 4.2：三色固定——del=红 / rep=琥珀 / ins=绿
                        color: model.kind === "del" ? Theme.cDangerSoft
                             : model.kind === "ins" ? Theme.cInsBg
                             : model.kind === "rep_a" ? Theme.cChangeBg
                             : model.kind === "rep_b" ? Theme.cChangeBg
                             : "transparent"
                        Row {
                            anchors.fill: parent
                            Text {
                                width: 46
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                text: model.oldNo
                                font.pixelSize: Theme.fsLabel
                                color: Theme.cTextDim
                                horizontalAlignment: Text.AlignRight
                                rightPadding: Theme.sp6
                            }
                            Text {
                                width: 46
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                text: model.newNo
                                font.pixelSize: Theme.fsLabel
                                color: Theme.cTextDim
                                horizontalAlignment: Text.AlignRight
                                rightPadding: Theme.sp6
                            }
                            Text {
                                width: parent.width - 92
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                text: model.text
                                font.pixelSize: Theme.fsMeta
                                // M35 4.2：三色固定——del/rep_a=红、rep_b=琥珀、ins=绿
                                color: model.kind === "del" ? Theme.cDanger
                                     : model.kind === "rep_a" ? Theme.cDanger
                                     : model.kind === "rep_b" ? Theme.cChange
                                     : model.kind === "ins" ? Theme.cIns
                                     : Theme.cText
                                font.bold: model.kind === "rep_a" || model.kind === "rep_b"
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }

            Text {
                id: noteLbl
                font.pixelSize: Theme.fsLabel
                color: Theme.cTextDim
                visible: text !== ""
            }

            Item { height: 4 }
            Text {
                text: "零解析底线：Diff 白名单读取是全应用唯一允许读文件内容的路径"
                font.pixelSize: Theme.fsMicro
                color: Theme.cDisabledFg
            }
        }
    }

    ListModel { id: rowsModel }
}
