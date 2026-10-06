import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var ui
    property var pageData: ({})
    property var market: ({})
    property var account: ({})
    property var connection: ({})
    property var bridge
    property var form: ({side: "BUY", price: "", volume: "0.01", sl: "", tp: ""})

    function resetForm() { form = {side: "BUY", price: "", volume: "0.01", sl: "", tp: ""} }
    function updateField(name, value) {
        var next = Object.assign({}, form)
        next[name] = value
        form = next
        if (bridge) bridge.perform("basicInvalidate", {})
    }
    function quote(value) {
        return value !== undefined && value !== null && isFinite(Number(value)) ? Number(value).toFixed(3) : "—"
    }

    ScrollView {
        id: viewport
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: UiScrollBar { ui: root.ui }
        GridLayout {
            x: 24; y: 24
            width: Math.max(0, viewport.width - 48)
            columns: root.width >= 1100 ? 2 : 1
            columnSpacing: 16; rowSpacing: 16

            UiCard {
                objectName: "basicOrderFormCard"
                ui: root.ui; padding: 22; spacing: 18
                Layout.fillWidth: true; Layout.alignment: Qt.AlignTop
                SectionHeading { ui: root.ui; title: "限价下单"; subtitle: "XAUUSDc · 单笔挂单 · GTC 长期有效"; Layout.fillWidth: true }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: [{side: "BUY", title: "买入限价"}, {side: "SELL", title: "卖出限价"}]
                        delegate: Rectangle {
                            required property var modelData
                            readonly property bool selected: root.form.side === modelData.side
                            readonly property color tone: modelData.side === "BUY" ? root.ui.positive : root.ui.negative
                            Layout.fillWidth: true; implicitHeight: 44; radius: 9
                            color: selected ? tone : root.ui.surfaceAlt
                            border.color: selected ? tone : root.ui.border
                            Text { anchors.centerIn: parent; text: modelData.title; color: parent.selected ? root.ui.accentText : root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.updateField("side", modelData.side) }
                        }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true; columns: 2
                    columnSpacing: 12; rowSpacing: 16
                    Repeater {
                        model: [
                            {key: "price", title: "限价", hint: "输入挂单价格"},
                            {key: "volume", title: "数量 · 手", hint: "例如 0.01"},
                            {key: "sl", title: "止损价 · 可选", hint: "留空则不设止损"},
                            {key: "tp", title: "止盈价 · 可选", hint: "留空则不设止盈"}
                        ]
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 7
                            Text { text: modelData.title; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                            TextField {
                                id: field
                                objectName: "basicOrderField_" + modelData.key
                                Layout.fillWidth: true; Layout.preferredHeight: 44
                                text: root.form[modelData.key]; placeholderText: modelData.hint
                                selectByMouse: true; inputMethodHints: Qt.ImhFormattedNumbersOnly
                                color: root.ui.text; placeholderTextColor: root.ui.muted
                                font.family: root.ui.fontFamily; font.pixelSize: 14
                                leftPadding: 12; rightPadding: 12
                                onTextEdited: root.updateField(modelData.key, text)
                                background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: field.activeFocus ? root.ui.accent : root.ui.border }
                            }
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: root.form.side === "BUY" ? "买入限价需低于当前报价；等待价格回落后成交。" : "卖出限价需高于当前报价；等待价格上涨后成交。"
                    color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: Boolean(root.pageData.error || root.pageData.message)
                    text: root.pageData.error || root.pageData.message || ""
                    color: root.pageData.error ? root.ui.negative : root.ui.accent
                    font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
                UiButton {
                    objectName: "basicOrderPreviewButton"
                    ui: root.ui; text: "预览" + (root.form.side === "BUY" ? "买入" : "卖出") + "限价单"
                    variant: "primary"; Layout.fillWidth: true; Layout.preferredHeight: 44
                    enabled: root.connection.connected === true && !root.connection.locked && root.form.price.trim().length > 0 && root.form.volume.trim().length > 0
                    onClicked: if (root.bridge) root.bridge.perform("basicPreview", root.form)
                }
            }
            UiCard {
                objectName: "basicOrderMarketCard"
                ui: root.ui; padding: 22; spacing: 18
                Layout.fillWidth: true; Layout.alignment: Qt.AlignTop
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "XAUUSDc"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 20; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Text { text: root.market.stale ? "报价延迟" : "实时行情"; color: root.market.stale ? root.ui.warning : root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                }
                GridLayout {
                    Layout.fillWidth: true; columns: 2; columnSpacing: 12
                    MetricCard { ui: root.ui; Layout.fillWidth: true; title: "BID · 卖出"; value: root.quote(root.market.bid); note: "当前卖价" }
                    MetricCard { ui: root.ui; Layout.fillWidth: true; title: "ASK · 买入"; value: root.quote(root.market.ask); note: "当前买价"; tone: "accent" }
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.ui.border }
                Text {
                    Layout.fillWidth: true
                    text: root.account.login ? "账户 " + root.account.login + " · " + root.account.server : "请先连接 USC 美分账户"
                    color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
                Text { text: "下单说明"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold }
                Text {
                    Layout.fillWidth: true
                    text: "基础下单直接使用填写的手数，不自动分仓。\n\n如需按风险预算计算多档价格和手数，请使用高级下单。"
                    color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap; lineHeight: 1.3
                }
                Text {
                    Layout.fillWidth: true
                    text: root.form.sl.trim() ? "预览时按当前账户合约计算止损风险；估算未计入跳空、手续费及隔夜费。" : "当前未填写止损，亏损风险未限定。可在发送前填写止损价。"
                    color: root.ui.warning; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap
                }
            }
            Item { Layout.columnSpan: parent.columns; Layout.preferredHeight: 24 }
        }
    }
}
