import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property var ui
    property var pageData: ({})
    property var account: ({})
    property var market: ({})
    property var connection: ({})
    property var bridge

    function number(value, places) {
        if (value === undefined || value === null || value === "") return "—"
        const n = Number(value)
        return isFinite(n) ? n.toFixed(places) : "—"
    }
    function money(value, signed) {
        if (value === undefined || value === null || value === "") return "—"
        const n = Number(value)
        return isFinite(n) ? (signed && n >= 0 ? "+" : "") + n.toFixed(2) + " USC" : "—"
    }
    function accountLine() {
        if (!account || !account.login) return "账户尚未连接"
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
                        text: "总览看板"
                        color: ui.text
                        font.family: ui.fontFamily
                        font.pixelSize: 26
                        font.weight: Font.Bold
                    }
                    Text {
                        text: page.accountLine()
                        color: ui.muted
                        font.family: ui.fontFamily
                        font.pixelSize: 13
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: connection.connected ? (market.stale ? "● 报价延迟" : "● 实时行情") : "● 等待行情"
                    color: market.stale ? ui.warning : connection.connected ? ui.positive : ui.muted
                    font.family: ui.fontFamily
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    Layout.alignment: Qt.AlignTop
                }
            }

            UiCard {
                ui: page.ui
                Layout.fillWidth: true
                padding: 24
                spacing: 15
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 24
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 190
                        spacing: 5
                        Text {
                            text: "市场快照"
                            color: ui.muted
                            font.family: ui.fontFamily
                            font.pixelSize: 12
                        }
                        Text {
                            text: market.symbol || "XAUUSDc"
                            color: ui.text
                            font.family: ui.fontFamily
                            font.pixelSize: 22
                            font.weight: Font.Bold
                        }
                        Text {
                            text: market.change === undefined || market.change === null ? "昨收数据不可用"
                                  : "较昨收 " + (Number(market.change) >= 0 ? "+" : "") + page.number(market.change, 3)
                                  + " (" + (Number(market.changePct) >= 0 ? "+" : "") + page.number(market.changePct, 2) + "%)"
                            color: market.change === undefined || market.change === null ? ui.muted : Number(market.change) >= 0 ? ui.positive : ui.negative
                            font.family: ui.fontFamily
                            font.pixelSize: 12
                        }
                        Text {
                            text: market.time ? "报价时间 " + ui.formatTime(market.time, false) + " " + ui.timeZoneLabel : "等待报价"
                            color: ui.faint
                            font.family: ui.fontFamily
                            font.pixelSize: 11
                        }
                    }

                    Repeater {
                        model: [
                            { caption: "BID · 卖出", value: page.number(market.bid, 3) },
                            { caption: "ASK · 买入", value: page.number(market.ask, 3) },
                            { caption: "点差", value: market.spreadPoints === undefined || market.spreadPoints === null ? "—" : page.number(market.spreadPoints, 1) + " pt" }
                        ]
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.minimumWidth: 145
                            spacing: 16
                            Text {
                                text: modelData.caption
                                color: ui.muted
                                font.family: ui.fontFamily
                                font.pixelSize: 12
                            }
                            Text {
                                text: modelData.value
                                color: ui.text
                                font.family: ui.fontFamily
                                font.pixelSize: 23
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }

            SectionHeading { ui: page.ui; title: "账户概况"; Layout.fillWidth: true }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth >= 1260 ? 5 : scroll.availableWidth >= 900 ? 3 : 2
                columnSpacing: 12
                rowSpacing: 12
                MetricCard {
                    ui: page.ui; title: "账户净值"; value: page.money(account.equity, false)
                    note: "含当前浮动盈亏"; Layout.fillWidth: true
                }
                MetricCard {
                    ui: page.ui; title: "账户余额"; value: page.money(account.balance, false)
                    note: "当前账户余额"; Layout.fillWidth: true
                }
                MetricCard {
                    ui: page.ui; title: "浮动盈亏"; value: page.money(account.profit, true)
                    note: "未平仓持仓"; tone: Number(account.profit) < 0 ? "negative" : "positive"; Layout.fillWidth: true
                }
                MetricCard {
                    ui: page.ui; title: "可用保证金"; value: page.money(account.marginFree, false)
                    note: "用于新开仓"; Layout.fillWidth: true
                }
                MetricCard {
                    ui: page.ui; title: "保证金水平"
                    value: Number(account.margin) > 0 ? page.number(account.marginLevel, 1) + "%" : "—"
                    note: "无持仓时显示为空"; Layout.fillWidth: true
                }
            }

            SectionHeading {
                ui: page.ui
                title: "行情与收益"
                subtitle: "行情与账户历史由本地 MT5 读取。"
                Layout.fillWidth: true
            }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth >= 1100 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 12

                UiCard {
                    ui: page.ui
                    Layout.fillWidth: true
                    Layout.minimumWidth: scroll.availableWidth >= 1100 ? 440 : 0
                    padding: 20
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "黄金价格 · 5 分钟 K 线"
                            color: ui.text
                            font.family: ui.fontFamily
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: "最近 72 根 · " + ui.timeZoneLabel
                            color: ui.muted
                            font.family: ui.fontFamily
                            font.pixelSize: 11
                        }
                    }
                    DataChart {
                        ui: page.ui
                        points: page.pageData.candles || []
                        mode: "candles"
                        emptyText: "连接 MT5 后显示 K 线"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 264
                    }
                }

                UiCard {
                    ui: page.ui
                    Layout.fillWidth: true
                    Layout.minimumWidth: scroll.availableWidth >= 1100 ? 360 : 0
                    padding: 20
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "近 30 日已实现净损益"
                            color: ui.text
                            font.family: ui.fontFamily
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: "单位 USC"
                            color: ui.muted
                            font.family: ui.fontFamily
                            font.pixelSize: 11
                        }
                    }
                    DataChart {
                        ui: page.ui
                        points: page.pageData.dailyPnl || []
                        mode: "bars"
                        valueKey: "amount"
                        emptyText: "暂无成交历史"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 264
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "K 线约 60 秒刷新；收益按账户币种统计，不含当前浮动盈亏。"
                    color: ui.muted
                    font.family: ui.fontFamily
                    font.pixelSize: 11
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
                UiButton {
                    ui: page.ui; text: "刷新看板"; variant: "ghost"
                    onClicked: if (page.bridge) page.bridge.perform("refresh", {page: "dashboard"})
                }
            }

            SectionHeading { ui: page.ui; title: "实时敞口"; Layout.fillWidth: true }

            GridLayout {
                Layout.fillWidth: true
                columns: scroll.availableWidth >= 1100 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 12

                UiCard {
                    ui: page.ui
                    Layout.fillWidth: true
                    Layout.minimumWidth: scroll.availableWidth >= 1100 ? 440 : 0
                    Layout.minimumHeight: 160
                    Text {
                        text: "当前持仓 · XAUUSDc"
                        color: ui.text
                        font.family: ui.fontFamily
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    Text {
                        visible: !(page.pageData.positions && page.pageData.positions.length)
                        text: "当前没有持仓"
                        color: ui.faint
                        font.family: ui.fontFamily
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Repeater {
                        model: page.pageData.positions || []
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 10
                            Text { text: "#" + modelData.ticket; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 12; Layout.fillWidth: true }
                            Text { text: modelData.side || "—"; color: ui.muted; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 80 }
                            Text { text: page.number(modelData.volume, 2) + " lot"; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 90 }
                            Text { text: page.money(modelData.profit, true); color: Number(modelData.profit) < 0 ? ui.negative : ui.positive; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 100; horizontalAlignment: Text.AlignRight }
                        }
                    }
                }

                UiCard {
                    ui: page.ui
                    Layout.fillWidth: true
                    Layout.minimumWidth: scroll.availableWidth >= 1100 ? 360 : 0
                    Layout.minimumHeight: 160
                    Text {
                        text: "当前挂单 · XAUUSDc"
                        color: ui.text
                        font.family: ui.fontFamily
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    Text {
                        visible: !(page.pageData.orders && page.pageData.orders.length)
                        text: "当前没有挂单"
                        color: ui.faint
                        font.family: ui.fontFamily
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Repeater {
                        model: page.pageData.orders || []
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 10
                            Text { text: "#" + modelData.ticket; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 12; Layout.fillWidth: true }
                            Text { text: modelData.type || "—"; color: ui.muted; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 100 }
                            Text { text: page.number(modelData.volume, 2) + " lot"; color: ui.text; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 80 }
                            Text { text: page.number(modelData.priceOpen, 3); color: ui.text; font.family: ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 80; horizontalAlignment: Text.AlignRight }
                        }
                    }
                }
            }
            Item { Layout.preferredHeight: 22 }
        }
    }
}
