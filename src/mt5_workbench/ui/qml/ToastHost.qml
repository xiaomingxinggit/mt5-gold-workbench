import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: host
    objectName: "toastHost"
    property var ui
    property int sequence: 0
    readonly property int count: notifications.count
    width: Math.min(440, parent ? parent.width - 48 : 440)
    height: stack.implicitHeight

    function show(message, level) {
        if (!message) return
        // Each event is shown, including repeated results from separate clicks.
        if (notifications.count >= 3) notifications.remove(0)
        notifications.append({toastId: ++sequence, message: String(message), level: String(level || "info")})
    }
    function dismiss(toastId) {
        for (var i = 0; i < notifications.count; ++i) {
            if (notifications.get(i).toastId === toastId) {
                notifications.remove(i)
                return
            }
        }
    }

    ListModel { id: notifications }
    Column {
        id: stack
        width: host.width
        spacing: 10
        Repeater {
            model: notifications
            delegate: Rectangle {
                id: toast
                objectName: "notificationToast"
                required property int toastId
                required property string message
                required property string level
                readonly property color tone: level === "error" ? host.ui.negative
                    : level === "warning" ? host.ui.warning
                    : level === "success" ? host.ui.positive : host.ui.chartBlue
                width: stack.width
                implicitHeight: content.implicitHeight + 30
                radius: 12
                color: host.ui.surface
                border.color: tone
                border.width: 1
                Accessible.role: Accessible.AlertMessage
                Accessible.name: (level === "error" ? "操作失败：" : level === "success" ? "操作成功：" : "提示：") + message

                NumberAnimation on opacity { from: 0; to: 1; duration: 160 }
                Rectangle {
                    x: 1; y: 12; width: 4; height: parent.height - 24
                    radius: 2; color: toast.tone
                }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    onContainsMouseChanged: {
                        if (containsMouse) expiry.stop()
                        else expiry.restart()
                    }
                }
                RowLayout {
                    id: content
                    anchors.fill: parent
                    anchors.margins: 15
                    spacing: 12
                    Rectangle {
                        Layout.preferredWidth: 28; Layout.preferredHeight: 28
                        Layout.alignment: Qt.AlignTop
                        radius: 14
                        color: Qt.rgba(toast.tone.r, toast.tone.g, toast.tone.b, 0.13)
                        Canvas {
                            anchors.centerIn: parent
                            width: 18; height: 18
                            property color strokeColor: toast.tone
                            onStrokeColorChanged: requestPaint()
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.reset()
                                ctx.strokeStyle = strokeColor
                                ctx.fillStyle = strokeColor
                                ctx.lineWidth = 2
                                ctx.lineCap = "round"
                                ctx.lineJoin = "round"
                                ctx.beginPath()
                                if (toast.level === "success") {
                                    ctx.moveTo(3, 9); ctx.lineTo(7, 13); ctx.lineTo(15, 5)
                                } else if (toast.level === "error") {
                                    ctx.moveTo(5, 5); ctx.lineTo(13, 13)
                                    ctx.moveTo(13, 5); ctx.lineTo(5, 13)
                                } else {
                                    ctx.moveTo(9, 4); ctx.lineTo(9, 10)
                                    ctx.fillRect(8, 13, 2, 2)
                                }
                                ctx.stroke()
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 5
                        Text {
                            text: toast.level === "success" ? "操作成功" : toast.level === "error" ? "操作失败" : "提示"
                            color: toast.tone; font.family: host.ui.fontFamily
                            font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                        Text {
                            objectName: "notificationMessage"
                            Layout.fillWidth: true
                            text: toast.message; textFormat: Text.PlainText
                            color: host.ui.text; font.family: host.ui.fontFamily
                            font.pixelSize: 13; wrapMode: Text.Wrap; lineHeight: 1.35
                        }
                    }
                    UiButton {
                        objectName: "notificationClose"
                        ui: host.ui; text: "×"; variant: "ghost"
                        Layout.preferredWidth: 28; Layout.preferredHeight: 28
                        Layout.alignment: Qt.AlignTop
                        Accessible.role: Accessible.Button
                        Accessible.name: "关闭提示"
                        onClicked: host.dismiss(toast.toastId)
                    }
                }
                Timer {
                    id: expiry
                    objectName: "notificationExpiry"
                    interval: toast.level === "error" ? 7000 : toast.level === "warning" ? 6000 : 4000
                    running: true
                    onTriggered: host.dismiss(toast.toastId)
                }
            }
        }
    }
}
