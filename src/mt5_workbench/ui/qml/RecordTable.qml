import QtQuick
import QtQuick.Layouts

UiCard {
    id: table
    property string title: ""
    property string subtitle: ""
    property var columns: []
    property var rows: []
    property int maxRows: 8
    property int visibleRows: maxRows
    property string emptyText: "暂无记录"
    signal rowSelected(var record)
    padding: 0
    spacing: 0

    function cellText(record, column) {
        const value = record && column && column.key ? record[column.key] : undefined
        if (value === undefined || value === null || value === "") return "—"
        if (column.format === "time") return table.ui.formatTime(value, false)
        if (column.format === "money") {
            const n = Number(value)
            return isFinite(n) ? (n >= 0 ? "+" : "") + n.toFixed(2) : "—"
        }
        if (column.format === "price") {
            const n = Number(value)
            return isFinite(n) ? n.toFixed(3) : "—"
        }
        if (column.format === "lots") {
            const n = Number(value)
            return isFinite(n) ? n.toFixed(2) : "—"
        }
        return String(value)
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.topMargin: 18
            Layout.bottomMargin: 14
            Text {
                text: table.title
                color: table.ui.text
                font.family: table.ui.fontFamily
                font.pixelSize: 15
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            Text {
                text: table.subtitle || String(table.rows ? table.rows.length : 0) + " 笔"
                color: table.ui.muted
                font.family: table.ui.fontFamily
                font.pixelSize: 11
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 37
            color: table.ui.surfaceAlt
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 20
                spacing: 9
                Repeater {
                    model: table.columns
                    delegate: Text {
                        required property var modelData
                        text: modelData.label
                        color: table.ui.muted
                        font.family: table.ui.fontFamily
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        Layout.preferredWidth: modelData.weight || 1
                        elide: Text.ElideRight
                    }
                }
            }
        }

        Text {
            text: table.emptyText
            visible: !table.rows || table.rows.length === 0
            color: table.ui.faint
            font.family: table.ui.fontFamily
            font.pixelSize: 12
            Layout.fillWidth: true
            Layout.preferredHeight: 85
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignHCenter
        }

        Repeater {
            model: table.rows ? table.rows.slice(0, table.visibleRows) : []
            delegate: Rectangle {
                id: recordRow
                objectName: "recordRow_" + table.title + "_" + index
                required property var modelData
                required property int index
                property var record: modelData
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                color: recordMouse.containsMouse ? table.ui.hover
                      : index % 2 ? table.ui.surfaceAlt : table.ui.surface
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 20
                    anchors.rightMargin: 20
                    spacing: 9
                    Repeater {
                        model: table.columns
                        delegate: Text {
                            required property var modelData
                            property var col: modelData
                            text: table.cellText(recordRow.record, col)
                            color: (col.format === "money" && Number(recordRow.record[col.key]) < 0)
                                   ? table.ui.negative : table.ui.text
                            font.family: table.ui.fontFamily
                            font.pixelSize: 11
                            Layout.fillWidth: true
                            Layout.preferredWidth: col.weight || 1
                            elide: Text.ElideRight
                        }
                    }
                }
                MouseArea {
                    id: recordMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: table.rowSelected(recordRow.record)
                }
            }
        }

        RowLayout {
            visible: table.rows && table.rows.length > table.visibleRows
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 20
            Layout.topMargin: 10
            Layout.bottomMargin: 12
            Text {
                text: "已显示 " + Math.min(table.visibleRows, table.rows.length) + " / " + table.rows.length + " 笔"
                color: table.ui.faint
                font.family: table.ui.fontFamily
                font.pixelSize: 11
                Layout.fillWidth: true
            }
            UiButton {
                ui: table.ui
                text: "加载更多"
                variant: "ghost"
                onClicked: table.visibleRows = Math.min(table.rows.length, table.visibleRows + 20)
            }
        }
        Item { Layout.preferredHeight: 10 }
    }
}
