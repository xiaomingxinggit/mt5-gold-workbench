import QtQuick
import QtQuick.Layouts

UiCard {
    id: metric
    property string title: ""
    property string value: "—"
    property string note: ""
    property string tone: "default"
    padding: 17
    spacing: 5
    implicitWidth: 178
    implicitHeight: 116

    Text {
        text: metric.title
        color: metric.ui ? metric.ui.muted : "#60758D"
        font.family: metric.ui ? metric.ui.fontFamily : "Microsoft YaHei UI"
        font.pixelSize: 13
        Layout.fillWidth: true
        elide: Text.ElideRight
    }
    Text {
        text: metric.value
        color: metric.tone === "positive" ? metric.ui.positive
             : metric.tone === "negative" ? metric.ui.negative
             : metric.tone === "accent" ? metric.ui.accent
             : metric.ui.text
        font.family: metric.ui ? metric.ui.fontFamily : "Microsoft YaHei UI"
        font.pixelSize: 22
        font.weight: Font.DemiBold
        Layout.fillWidth: true
        elide: Text.ElideRight
    }
    Text {
        text: metric.note
        visible: text.length > 0
        color: metric.ui ? metric.ui.faint : "#8A9AAF"
        font.family: metric.ui ? metric.ui.fontFamily : "Microsoft YaHei UI"
        font.pixelSize: 11
        Layout.fillWidth: true
        elide: Text.ElideRight
    }
}
