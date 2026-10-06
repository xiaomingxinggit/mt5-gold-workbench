import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    property var ui
    implicitHeight: 38
    padding: 0
    leftPadding: 0
    rightPadding: 0
    font.family: ui.fontFamily
    font.pixelSize: 13
    background: Rectangle {
        radius: 9
        color: control.ui.surfaceAlt
        border.color: control.activeFocus ? control.ui.accent : control.ui.border
    }
    contentItem: Text {
        text: control.displayText
        color: control.enabled ? control.ui.text : control.ui.muted
        font: control.font
        leftPadding: 12
        rightPadding: 34
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: Text {
        x: control.width - width - 14
        y: (control.height - height) / 2
        text: "▾"
        color: control.ui.muted
        font.family: control.ui.fontFamily
        font.pixelSize: 16
    }
    delegate: ItemDelegate {
        id: option
        required property int index
        required property var modelData
        objectName: control.objectName + "Option_" + index
        width: control.width - 8
        height: 38
        text: String(modelData)
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: option.text
            color: control.ui.text
            font: control.font
            leftPadding: 10
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 6
            color: option.highlighted ? control.ui.accentSoft
                   : option.hovered ? control.ui.hover : control.ui.surface
        }
    }
    popup: Popup {
        objectName: control.objectName + "Popup"
        y: control.height + 4
        width: control.width
        padding: 4
        implicitHeight: Math.min(280, contentItem.implicitHeight) + topPadding + bottomPadding
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollBar.vertical: UiScrollBar { ui: control.ui }
        }
        background: Rectangle {
            objectName: control.objectName + "PopupBackground"
            radius: 9
            color: control.ui.surface
            border.color: control.ui.border
        }
    }
}
