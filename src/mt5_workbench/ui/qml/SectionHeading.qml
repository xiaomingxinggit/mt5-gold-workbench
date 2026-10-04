import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: section
    property var ui
    property string title: ""
    property string subtitle: ""
    spacing: 4

    Text {
        text: section.title
        color: section.ui ? section.ui.text : "#172A40"
        font.family: section.ui ? section.ui.fontFamily : "Microsoft YaHei UI"
        font.pixelSize: 17
        font.weight: Font.DemiBold
        Layout.fillWidth: true
    }
    Text {
        text: section.subtitle
        visible: text.length > 0
        color: section.ui ? section.ui.muted : "#60758D"
        font.family: section.ui ? section.ui.fontFamily : "Microsoft YaHei UI"
        font.pixelSize: 12
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
    }
}
