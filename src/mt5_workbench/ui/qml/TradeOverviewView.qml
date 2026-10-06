import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property var ui
    property var pageData: ({})
    property var account: ({})
    property var connection: ({})
    property var bridge
    property var selectedRecord: null
    property string selectedKind: ""

    function value(value, places) {
        if (value === undefined || value === null || value === "") return "—"
        const n = Number(value)
        return isFinite(n) ? n.toFixed(places) : "—"
    }
    function money(value, signed) {
        if (value === undefined || value === null || value === "") return "—"
        const n = Number(value)
        return isFinite(n) ? (signed && n >= 0 ? "+" : "") + n.toFixed(2) + " USC" : "—"
    }
    function count(value) {
        if (value === undefined || value === null || value === "") return "—"
        const n = Number(value)
        return isFinite(n) ? String(n) : "—"
    }
    function maxStatusCount() {
        const rows = page.pageData.statusCounts || []
        let largest = 1
        for (let i = 0; i < rows.length; i++)
            largest = Math.max(largest, Number(rows[i].count) || 0)
        return largest
    }
    function filters(scope, days) {
        if (bridge) bridge.perform("overviewFilters", {scope: scope, days: days})
    }
    function accountLabel() {
        if (!account || !account.login) return "连接 MT5 后读取账户交易数据"
        return "账户 " + account.login + "  ·  " + (account.server || "MT5") + "  ·  " + (account.currency || "—")
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: UiScrollBar { ui: page.ui; policy: ScrollBar.AsNeeded }

        ColumnLayout {
            x: 24
            y: 22
            width: Math.max(760, scroll.availableWidth - 48)
            spacing: 18

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                ColumnLayout {
                    spacing: 5
                    Text {
                        text: "交易概览"
                        color: ui.text
                        font.family: ui.fontFamily
                        font.pixelSize: 26
                        font.weight: Font.Bold
                    }
                    Text {
                        text: page.accountLabel()
                        color: ui.muted
                        font.family: ui.fontFamily
                        font.pixelSize: 13
                    }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    Layout.preferredHeight: 29
                    Layout.preferredWidth: 80
                    radius: 15
                    color: ui.accentSoft
                    Text {
                        anchors.centerIn: parent
                        text: "只读分析"
                        color: ui.positive
                        font.family: ui.fontFamily
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                }
            }

            UiCard {
                ui: page.ui
                Layout.fillWidth: true
                padding: 17
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Text {
                        text: "分析范围"
                        color: ui.muted
                        font.family: ui.fontFamily
                        font.pixelSize: 12
                        Layout.rightMargin: 4
                    }
                    UiButton {
                        ui: page.ui
                        text: "XAUUSDc"
                        variant: (page.pageData.scope || "symbol") === "symbol" ? "primary" : "ghost"
                        onClicked: page.filters("symbol", Number(page.pageData.days || 30))
                    }
                    UiButton {
                        ui: page.ui
                        text: "整个账户"
                        variant: page.pageData.scope === "account" ? "primary" : "ghost"
                        onClicked: page.filters("account", Number(page.pageData.days || 30))
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: "时间范围"
                        color: ui.muted
                        font.family: ui.fontFamily
                        font.pixelSize: 12
                    }
                    UiComboBox {
                        id: period
                        objectName: "tradePeriodSelector"
                        ui: page.ui
                        model: ["近 7 日", "近 30 日", "近 90 日"]
                        property var periods: [7, 30, 90]
                        currentIndex: Math.max(0, periods.indexOf(Number(page.pageData.days || 30)))
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 38
                        onActivated: function(index) { page.filters(page.pageData.scope || "symbol", periods[index]) }
                    }
                    UiButton {
                        ui: page.ui
                        text: "立即刷新"
                        busy: page.pageData.loading === true
                        onClicked: if (page.bridge) page.bridge.perform("refresh", {page: "orders"})
                    }
                }
                Text {
                    text: page.pageData.loading ? "正在后台读取 MT5 历史数据…"
                          : page.pageData.asOf ? "更新于 " + page.pageData.asOf : "连接 MT5 后读取订单历史。"
                    color: ui.faint
                    font.family: ui.fontFamily
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }
            }

            Text {
                text: page.pageData.errors && page.pageData.errors.length ? page.pageData.errors.join(" · ") : ""
                visible: text.length > 0
                color: ui.warning
                font.family: ui.fontFamily
                font.pixelSize: 12
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }

            SectionHeading {
                ui: page.ui
                title: "账户资金表现"
                subtitle: "余额与净值来自当前账户；交易现金流按所选期间逐日累计。"
                Layout.fillWidth: true
            }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth >= 1260 ? 5 : scroll.availableWidth >= 900 ? 3 : 2
                columnSpacing: 12
                rowSpacing: 12
                MetricCard { ui: page.ui; title: "当前余额"; value: page.money(account.balance, false); note: "账户实时快照"; Layout.fillWidth: true }
                MetricCard { ui: page.ui; title: "当前净值"; value: page.money(account.equity, false); note: "含持仓浮盈亏"; Layout.fillWidth: true }
                MetricCard {
                    ui: page.ui; title: "期间交易现金流"
                    value: page.money(page.pageData.metrics ? page.pageData.metrics.netTradingCashflow : null, true)
                    note: "已实现盈亏及费用"; Layout.fillWidth: true
                    tone: page.pageData.metrics && Number(page.pageData.metrics.netTradingCashflow) < 0 ? "negative" : "positive"
                }
                MetricCard {
                    ui: page.ui; title: "按日最大回撤"
                    value: page.money(page.pageData.metrics ? page.pageData.metrics.maxDrawdown : null, false)
                    note: "交易现金流口径"; Layout.fillWidth: true
                }
                MetricCard {
                    ui: page.ui; title: "当前距峰值"
                    value: page.money(page.pageData.metrics ? page.pageData.metrics.currentDrawdown : null, false)
                    note: "交易现金流口径"; Layout.fillWidth: true
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth >= 1100 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 12
                UiCard {
                    ui: page.ui
                    Layout.fillWidth: true
                    Layout.minimumWidth: scroll.availableWidth >= 1100 ? 480 : 0
                    padding: 20
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "累计交易现金流"; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        Text { text: "单位 USC"; color: ui.muted; font.family: ui.fontFamily; font.pixelSize: 11 }
                    }
                    DataChart {
                        ui: page.ui
                        points: page.pageData.accountCurve || []
                        mode: "line"
                        valueKey: "cumulative"
                        emptyText: "所选期间暂无交易现金流"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 266
                    }
                }
                UiCard {
                    ui: page.ui
                    Layout.fillWidth: true
                    Layout.minimumWidth: scroll.availableWidth >= 1100 ? 360 : 0
                    padding: 20
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "每日成交笔数"; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        Text { text: "所选期间"; color: ui.muted; font.family: ui.fontFamily; font.pixelSize: 11 }
                    }
                    DataChart {
                        ui: page.ui
                        points: page.pageData.dailyExecution || []
                        mode: "bars"
                        valueKey: "dealCount"
                        emptyText: "暂无成交记录"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 266
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth >= 1100 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 12
                UiCard {
                    objectName: "tradeDrawdownCard"
                    ui: page.ui
                    Layout.fillWidth: true
                    padding: 20
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "按日回撤"; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        Text { text: "距期间现金流峰值 · USC"; color: ui.muted; font.family: ui.fontFamily; font.pixelSize: 11 }
                    }
                    DataChart {
                        ui: page.ui
                        points: page.pageData.accountCurve || []
                        mode: "line"
                        valueKey: "drawdown"
                        emptyText: "所选期间暂无回撤数据"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 220
                    }
                }
                UiCard {
                    objectName: "tradeStatusCard"
                    ui: page.ui
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: 20
                    spacing: 12
                    Text { text: "历史订单状态"; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold }
                    Text { visible: !(page.pageData.statusCounts || []).length; text: "所选期间暂无历史订单"; color: ui.muted; font.family: ui.fontFamily; font.pixelSize: 13 }
                    Repeater {
                        model: page.pageData.statusCounts || []
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 10
                            Text { text: String(modelData.label); color: ui.muted; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 90; elide: Text.ElideRight }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 12
                                radius: 6
                                color: ui.surfaceAlt
                                Rectangle {
                                    width: Math.max(4, parent.width * (Number(modelData.count) || 0) / page.maxStatusCount())
                                    height: parent.height
                                    radius: 6
                                    color: ui.chartBlue
                                }
                            }
                            Text { text: String(modelData.count); color: ui.text; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 28; horizontalAlignment: Text.AlignRight }
                        }
                    }
                    Item { Layout.fillHeight: true; Layout.minimumHeight: 20 }
                }
            }

            SectionHeading {
                ui: page.ui
                title: "订单与成交"
                subtitle: "区分当前挂单、期间订单和实际成交；点击记录可查看原始字段。"
                Layout.fillWidth: true
            }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth >= 1100 ? 4 : 2
                columnSpacing: 12
                rowSpacing: 12
                MetricCard { ui: page.ui; title: "当前挂单"; value: page.count(page.pageData.metrics ? page.pageData.metrics.pendingCount : null); note: "手数 " + page.value(page.pageData.metrics ? page.pageData.metrics.pendingLots : null, 2); Layout.fillWidth: true }
                MetricCard { ui: page.ui; title: "当前持仓"; value: page.count(page.pageData.metrics ? page.pageData.metrics.positionCount : null); note: "手数 " + page.value(page.pageData.metrics ? page.pageData.metrics.positionLots : null, 2); Layout.fillWidth: true }
                MetricCard { ui: page.ui; title: "期间成交"; value: page.count(page.pageData.metrics ? page.pageData.metrics.dealCount : null); note: "总手数 " + page.value(page.pageData.metrics ? page.pageData.metrics.tradedLots : null, 2); Layout.fillWidth: true }
                MetricCard { ui: page.ui; title: "买入 / 卖出手数"; value: page.value(page.pageData.metrics ? page.pageData.metrics.buyLots : null, 2) + " / " + page.value(page.pageData.metrics ? page.pageData.metrics.sellLots : null, 2); note: "仅实际成交"; Layout.fillWidth: true }
            }

            RecordTable {
                ui: page.ui
                title: "当前挂单"
                rows: page.pageData.pendingOrders || []
                columns: [
                    {key:"ticket",label:"Ticket",weight:1}, {key:"symbol",label:"品种",weight:1},
                    {key:"type",label:"类型",weight:1.3}, {key:"volumeCurrent",label:"剩余手数",format:"lots",weight:1},
                    {key:"priceOpen",label:"挂单价",format:"price",weight:1}, {key:"sl",label:"止损",format:"price",weight:1},
                    {key:"tp",label:"止盈",format:"price",weight:1}
                ]
                Layout.fillWidth: true
                onRowSelected: record => { page.selectedRecord = record; page.selectedKind = "当前挂单" }
            }

            RecordTable {
                ui: page.ui
                title: "最近成交"
                rows: page.pageData.recentDeals || []
                columns: [
                    {key:"ticket",label:"Ticket",weight:1}, {key:"executedAt",label:"成交时间",weight:1.6},
                    {key:"side",label:"方向",weight:0.8}, {key:"volume",label:"手数",format:"lots",weight:0.8},
                    {key:"price",label:"成交价",format:"price",weight:1},
                    {key:"cashflow",label:"净现金流 USC",format:"money",weight:1.3}
                ]
                Layout.fillWidth: true
                onRowSelected: record => { page.selectedRecord = record; page.selectedKind = "最近成交" }
            }

            RecordTable {
                ui: page.ui
                title: "历史订单"
                rows: page.pageData.recentOrders || []
                columns: [
                    {key:"ticket",label:"Ticket",weight:1}, {key:"createdAt",label:"创建时间",weight:1.6},
                    {key:"type",label:"类型",weight:1.2}, {key:"status",label:"状态",weight:1},
                    {key:"volumeInitial",label:"初始手数",format:"lots",weight:1},
                    {key:"priceOpen",label:"委托价",format:"price",weight:1}
                ]
                Layout.fillWidth: true
                onRowSelected: record => { page.selectedRecord = record; page.selectedKind = "历史订单" }
            }

            UiCard {
                ui: page.ui
                visible: page.selectedRecord !== null
                Layout.fillWidth: true
                Text {
                    text: page.selectedKind + " · 原始字段"
                    color: ui.text
                    font.family: ui.fontFamily
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
                Text {
                    text: page.selectedRecord ? JSON.stringify(page.selectedRecord, null, 2) : ""
                    color: ui.muted
                    font.family: "Consolas"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                    wrapMode: Text.WrapAnywhere
                }
            }

            Item { Layout.preferredHeight: 22 }
        }
    }
}
