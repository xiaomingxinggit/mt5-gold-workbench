import QtQuick
import QtQuick.Layouts

RowLayout {
    id: root
    property var ui
    property string label: ""
    property string value: "—"
    property string valueName: ""
    spacing: 18
    Layout.fillWidth: true
    Text {
        text: root.label
        color: root.ui.muted
        font.family: root.ui.fontFamily
        font.pixelSize: 13
        Layout.preferredWidth: 150
        Layout.alignment: Qt.AlignTop
        wrapMode: Text.WordWrap
    }
    TextEdit {
        objectName: root.valueName
        text: root.value
        readOnly: true
        selectByMouse: true
        color: root.ui.text
        selectionColor: root.ui.accent
        selectedTextColor: root.ui.accentText
        font.family: root.ui.fontFamily
        font.pixelSize: 13
        Layout.fillWidth: true
        wrapMode: TextEdit.WrapAnywhere
    }
}
