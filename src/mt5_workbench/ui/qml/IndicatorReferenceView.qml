import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "indicatorReferenceView"
    property var ui
    property var pageData: ({})
    property var connection: ({})
    property var bridge
    property real targetPrice: 0
    property int referenceIndex: 0
    readonly property var averages: pageData.dailyAverages || []
    readonly property var reference: averages.length > referenceIndex ? averages[referenceIndex] : ({})

    function number(value, digits) {
        if (value === undefined || value === null || value === "") return "—"
        return isFinite(Number(value)) ? Number(value).toFixed(digits) : "—"
    }
    function row(key) {
        var rows = pageData.atr || []
        for (var i = 0; i < rows.length; ++i) if (rows[i].key === key) return rows[i]
        return ({})
    }
    function request(action, payload) {
        if (bridge) bridge.perform(action, payload)
    }

    ScrollView {
        id: viewport
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: UiScrollBar { ui: root.ui }

        ColumnLayout {
            x: 24; y: 24
            width: Math.max(0, viewport.width - 48)
            spacing: 18

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5
                    Text { text: "指标参考"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { text: "XAUUSDc · ATR 与平均日波动价格幅度"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14 }
                }
                UiButton {
                    ui: root.ui; text: root.pageData.loading ? "读取中…" : "立即刷新"; variant: "secondary"
                    enabled: root.connection.connected && !root.pageData.loading
                    onClicked: root.request("refresh", {page: "indicators"})
                }
            }

            Text {
                Layout.fillWidth: true
                text: !root.connection.connected ? "连接 MT5 后显示指标数值。"
                    : root.pageData.loading ? "正在读取已收盘的历史 K 线…"
                    : "每 60 秒刷新 · 最后读取 " + root.ui.formatTime(root.pageData.updatedAt || "—", false)
                color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                visible: (root.pageData.errors || []).length > 0
                text: (root.pageData.errors || []).join("\n")
                color: root.ui.warning; font.family: root.ui.fontFamily; font.pixelSize: 13
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true
                Text { text: "各周期 ATR"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
                Text { text: "平均周期"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                TextField {
                    id: periodInput
                    objectName: "indicatorPeriodInput"
                    text: String(root.pageData.period || 14)
                    validator: IntValidator { bottom: 1; top: 100 }
                    selectByMouse: true
                    Layout.preferredWidth: 120
                    color: root.ui.text
                    font.family: root.ui.fontFamily; font.pixelSize: 14
                    background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: periodInput.activeFocus ? root.ui.accent : root.ui.border }
                }
                UiButton {
                    ui: root.ui; text: "应用"; variant: "secondary"
                    enabled: !root.pageData.loading && periodInput.acceptableInput
                    onClicked: root.request("indicatorPeriod", {period: Number(periodInput.text)})
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 1110 ? 4 : 2
                columnSpacing: 12; rowSpacing: 12
                Repeater {
                    model: [{key: "year", label: "年"}, {key: "month", label: "月"}, {key: "week", label: "周"}, {key: "day", label: "日"}]
                    delegate: UiCard {
                        required property var modelData
                        readonly property var dataRow: root.row(modelData.key)
                        ui: root.ui
                        objectName: "indicatorAtrCard_" + modelData.key
                        Layout.fillWidth: true
                        Layout.preferredHeight: 192
                        padding: 18; spacing: 7
                        Text { text: modelData.label + " ATR(" + (root.pageData.period || 14) + ")"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                        Text {
                            objectName: "indicatorAtrPrice_" + modelData.key
                            text: root.number(dataRow.price, 3)
                            Layout.fillWidth: true; elide: Text.ElideRight
                            color: root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 24; font.weight: Font.DemiBold
                        }
                        Text { text: "价格幅度"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                        Text {
                            Layout.fillWidth: true
                            text: dataRow.reason || (dataRow.lastBar ? "最后一根 " + String(dataRow.lastBar).slice(0, 10) : "等待行情")
                            color: dataRow.reason ? root.ui.warning : root.ui.faint
                            font.family: root.ui.fontFamily; font.pixelSize: 11; wrapMode: Text.WordWrap
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: "ATR 为最近 N 根已收盘 K 线真实波幅的简单平均。年线由 12 根连续月线合成；年 ATR(14) 需要 15 个完整年份。年、月、周 ATR 均为整周期幅度，不直接除以天数换算。"
                color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap
            }

            SectionHeading { ui: root.ui; title: "平均每天的价格波动"; subtitle: "统一按日线真实波幅比较；最近交易日显示单日 TR" }
            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 1110 ? 4 : 2
                columnSpacing: 12; rowSpacing: 12
                Repeater {
                    model: root.averages
                    delegate: UiCard {
                        required property var modelData
                        ui: root.ui
                        objectName: "indicatorAverageCard_" + modelData.key
                        Layout.fillWidth: true
                        Layout.preferredHeight: 178
                        padding: 18; spacing: 7
                        Text { text: modelData.label; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                        Text { objectName: "indicatorAveragePrice_" + modelData.key; text: root.number(modelData.price, 3); Layout.fillWidth: true; elide: Text.ElideRight; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 22; font.weight: Font.DemiBold }
                        Text { text: "每日价格幅度"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.reason || (modelData.samples + " 个交易日 · " + modelData.start + " 至 " + modelData.end)
                            color: modelData.reason ? root.ui.warning : root.ui.faint
                            font.family: root.ui.fontFamily; font.pixelSize: 11; wrapMode: Text.WordWrap
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }

            UiCard {
                ui: root.ui; Layout.fillWidth: true; padding: 22; spacing: 14
                Text { text: "每日价格波动目标对照"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    UiComboBox {
                        objectName: "indicatorReferenceSelector"
                        ui: root.ui; Layout.preferredWidth: 160
                        model: ["近一年平均", "近一个月平均", "近一周平均", "最近交易日"]
                        onActivated: root.referenceIndex = currentIndex
                    }
                    TextField {
                        id: targetInput
                        objectName: "indicatorTargetInput"
                        Layout.preferredWidth: 150
                        placeholderText: "目标价格幅度，如 5"
                        color: root.ui.text; placeholderTextColor: root.ui.faint
                        font.family: root.ui.fontFamily; font.pixelSize: 14
                        selectByMouse: true
                        validator: DoubleValidator { bottom: 0; top: 1000000000; decimals: 3; notation: DoubleValidator.StandardNotation; locale: "C" }
                        onTextChanged: root.targetPrice = acceptableInput && text.length ? Number(text) : 0
                        background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: targetInput.activeFocus ? root.ui.accent : root.ui.border }
                    }
                    Text { text: "价格幅度"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                    Item { Layout.fillWidth: true }
                }
                Text {
                    objectName: "indicatorTargetSummary"
                    Layout.fillWidth: true
                    text: root.reference.price === undefined || root.reference.price === null
                        ? "所选区间暂无完整数据。"
                        : "平均每日价格波动：" + root.number(root.reference.price, 3)
                          + (root.targetPrice > 0 && root.reference.price > 0
                             ? "\n你的目标价格幅度 " + root.number(root.targetPrice, 3) + "，占平均日波幅 " + root.number(root.targetPrice / root.reference.price * 100, 1) + "%" : "")
                    color: root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold; wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    text: "这里比较行情幅度与目标价格幅度，不代表每日可赚利润。ATR 不表示方向，也不表示可捕获的收益。实际盈亏还取决于手数、进出场和交易成本。"
                    color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
            }
            Text {
                Layout.fillWidth: true
                text: "所有波动数值直接使用价格幅度。例如从 4200 到 4205，波动为 5。区间以最后一个已收盘交易日为终点，按 UTC K 线日期向前取一年 / 一月 / 一周；休市日不计入分母。TR = max(最高 − 最低，|最高 − 前收|，|最低 − 前收|)。"
                color: root.ui.faint; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap
            }
            Item { Layout.preferredHeight: 24 }
        }
    }
}
