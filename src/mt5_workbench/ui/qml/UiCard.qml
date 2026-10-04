import QtQuick
import QtQuick.Layouts

Rectangle {
    id: card
    property var ui
    property int padding: 20
    property int spacing: 12
    default property alias content: body.data

    radius: 15
    color: ui ? ui.surface : "#FFFFFF"
    border.width: 1
    border.color: ui ? ui.border : "#DDE6EF"
    implicitHeight: body.implicitHeight + padding * 2
    implicitWidth: 240

    ColumnLayout {
        id: body
        anchors.fill: parent
        anchors.margins: card.padding
        spacing: card.spacing
    }
}
