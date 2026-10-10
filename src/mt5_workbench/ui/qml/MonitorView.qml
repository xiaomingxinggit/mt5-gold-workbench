import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "monitorView"
    property var ui
    property var pageData: ({})
    property var bridge

    function value(name, fallback) {
        var result = root.pageData ? root.pageData[name] : undefined
        return result === undefined || result === null || result === "" ? fallback : result
    }
    function number(value, digits) {
        if (value === undefined || value === null || value === "") return "—"
        var parsed = Number(value)
        return isFinite(parsed) ? parsed.toFixed(digits) : "—"
    }
    function ema(period) {
        var values = root.value("emaValues", {})
        return values ? root.number(values[String(period)], 5) : "—"
    }
    function request(action, payload) {
        if (root.bridge) root.bridge.perform(action, payload)
    }

    ScrollView {
        id: viewport
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: UiScrollBar { ui: root.ui }

        ColumnLayout {
            x: 24
            y: 24
            width: Math.max(0, viewport.width - 48)
            spacing: 18

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5
                    Text { text: "行情监测"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { text: "XAUUSDc · M1 EMA 7 / 14 / 30 / 60 行情监听"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14 }
                }
                Rectangle {
                    implicitWidth: badgeText.implicitWidth + 22
                    implicitHeight: 28
                    radius: 8
                    color: root.ui.accentSoft
                    Text { id: badgeText; anchors.centerIn: parent; text: "只读"; color: root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold }
                }
                UiButton { ui: root.ui; text: "立即刷新"; variant: "secondary"; onClicked: root.request("monitorRefresh", {}) }
            }

            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                padding: 24
                spacing: 16
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 20
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "当前监听状态"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                        Text {
                            text: root.value("status", "等待行情")
                            color: root.value("status", "").indexOf("聚拢") >= 0 ? root.ui.positive : root.ui.text
                            font.family: root.ui.fontFamily; font.pixelSize: 27; font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.value("reason", "连接 MT5 后开始监听。")
                            color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14
                            wrapMode: Text.WordWrap
                        }
                    }
                    Rectangle { visible: root.width >= 980; width: 1; height: 80; color: root.ui.border }
                    ColumnLayout {
                        visible: root.width >= 980
                        spacing: 6
                        Text { text: "BID · 卖出"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        Text { text: root.number(root.value("bid", null), 3); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 23; font.weight: Font.DemiBold }
                    }
                    ColumnLayout {
                        visible: root.width >= 980
                        spacing: 6
                        Text { text: "ASK · 买入"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        Text { text: root.number(root.value("ask", null), 3); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 23; font.weight: Font.DemiBold }
                    }
                }
                RowLayout {
                    visible: root.width < 980
                    Layout.fillWidth: true
                    spacing: 24
                    Text { text: "BID  " + root.number(root.value("bid", null), 3); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                    Text { text: "ASK  " + root.number(root.value("ask", null), 3); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                }
                Text { text: "报价年龄 " + root.number(root.value("quoteAgeSeconds", null), 1) + " 秒"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 1110 ? 4 : 2
                columnSpacing: 12
                rowSpacing: 12
                Repeater {
                    model: [7, 14, 30, 60]
                    delegate: MetricCard {
                        required property var modelData
                        ui: root.ui
                        Layout.fillWidth: true
                        title: "EMA " + modelData
                        value: root.ema(modelData)
                        note: root.value("includesFormingBar", true) ? "M1 · 含形成中的 K 线" : "M1 · 已收盘 K 线"
                    }
                }
            }

            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                padding: 22
                spacing: 16
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "聚拢判定"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Text { text: "最大差距 " + root.number(root.value("emaSpreadPoints", null), 4) + " point"; color: root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                }
                Text {
                    Layout.fillWidth: true
                    text: "四条 EMA 的最高值与最低值之差不超过阈值时，标记为聚拢候选。形成中的 K 线会变化，候选状态也可能撤回。"
                    color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text { text: "最大允许差距"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14 }
                    TextField {
                        id: toleranceInput
                        Layout.preferredWidth: 120
                        text: root.number(root.value("tolerancePoints", 5), 2)
                        color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14
                        selectByMouse: true
                        validator: DoubleValidator { bottom: 0.01; top: 100000; decimals: 2 }
                        background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: toleranceInput.activeFocus ? root.ui.accent : root.ui.border }
                    }
                    Text { text: "MT5 point"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                    UiButton {
                        ui: root.ui; text: "应用阈值"; variant: "secondary"
                        onClicked: root.request("monitorTolerance", {"points": toleranceInput.text})
                    }
                    Item { Layout.fillWidth: true }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 22
                    Text { text: "M1 K 线：" + root.ui.formatTime(root.value("barTime", "—"), false); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                    Text { text: "采集时间：" + root.ui.formatTime(root.value("observedAt", "—"), false) + " " + root.ui.timeZoneLabel; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                }
            }

            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                padding: 22
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "本次运行的聚拢候选"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Text { text: "每根 M1 K 线最多记录一次"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                }
                Text {
                    visible: !root.value("history", []).length
                    text: "尚未发现聚拢候选。"
                    color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14
                    Layout.topMargin: 10; Layout.bottomMargin: 10
                }
                Repeater {
                    model: root.value("history", [])
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 42
                        radius: 8
                        color: root.ui.surfaceAlt
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                            Text { Layout.fillWidth: true; text: String(modelData.observedAt || "—"); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                            Text { Layout.fillWidth: true; text: "M1  " + root.ui.formatTime(modelData.barTime, false); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                            Text { text: root.number(modelData.spreadPoints, 4) + " point"; color: root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                        }
                    }
                }
            }
            Item { Layout.preferredHeight: 20 }
        }
    }
}
