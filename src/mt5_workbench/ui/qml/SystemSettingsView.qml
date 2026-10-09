import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "systemSettingsView"
    property var ui
    property var systemData: ({})
    property var refreshIntervals: ({quote: 1, positions: 5, orders: 30})
    property string themeName: "light"
    property bool fullscreen: false
    property var bridge
    // Keep the selector model stable while the clock updates every second.
    property var timeZoneChoices: []
    onSystemDataChanged: {
        if (!timeZoneChoices.length && systemData.timeZoneChoices)
            timeZoneChoices = systemData.timeZoneChoices
    }
    function request(name, payload) { if (bridge) bridge.perform(name, payload || {}) }

    ScrollView {
        id: viewport
        objectName: "systemSettingsScrollView"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: UiScrollBar { ui: root.ui }
        ColumnLayout {
            x: 24
            y: 22
            width: Math.max(0, viewport.availableWidth - 48)
            spacing: 18
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                Text { text: "系统配置"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
                Text { text: "管理工作台的全局设置，修改后立即生效并自动保存。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            UiCard {
                objectName: "systemTimeCard"
                ui: root.ui
                Layout.fillWidth: true
                spacing: 16
                SectionHeading { ui: root.ui; title: "时间与时区" }
                SettingsInfoRow { ui: root.ui; label: "当前系统时间"; value: root.systemData.systemTime || "—"; valueName: "systemCurrentTime" }
                SettingsInfoRow { ui: root.ui; label: "系统时区"; value: root.systemData.systemTimeZone || "—" }
                SettingsInfoRow { ui: root.ui; label: "工作台显示时间"; value: (root.systemData.displayTime || "—") + "  " + (root.systemData.timeZoneLabel || ""); valueName: "systemDisplayTime" }
                SettingsInfoRow { ui: root.ui; label: "当前 UTC 时间"; value: root.systemData.utcTime || "—" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 18
                    Text { text: "全局显示时区"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; Layout.preferredWidth: 150 }
                    UiComboBox {
                        objectName: "systemTimeZoneSelector"
                        ui: root.ui
                        Layout.preferredWidth: 240
                        model: root.timeZoneChoices.map(value => value === "local" ? "跟随系统时区" : value === "UTC+08:00" ? "北京时间 · UTC+8（默认）" : value)
                        currentIndex: Math.max(0, root.timeZoneChoices.indexOf(root.systemData.timeZone || "UTC+08:00"))
                        onActivated: function(index) { root.request("setTimeZone", {timeZone: root.timeZoneChoices[index]}) }
                    }
                    Item { Layout.fillWidth: true }
                }
                Text { text: "报价、K 线、订单、行情监听与日志时间轴统一使用此时区。按日盈亏统计及日志热力图保留各自统计口径；日志热力图按北京时间计算。此设置只调整工作台显示。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                spacing: 16
                SectionHeading { ui: root.ui; title: "自动刷新" }
                Repeater {
                    model: [{kind: "quote", label: "行情报价"}, {kind: "positions", label: "当前持仓"}, {kind: "orders", label: "挂单与交易概览"}]
                    delegate: RowLayout {
                        id: intervalRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 18
                        Text { text: intervalRow.modelData.label; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; Layout.preferredWidth: 150 }
                        TextField {
                            id: seconds
                            objectName: "systemRefreshSeconds_" + intervalRow.modelData.kind
                            Layout.preferredWidth: 120
                            implicitHeight: 38
                            text: String(root.refreshIntervals[intervalRow.modelData.kind] || 1)
                            color: root.ui.text
                            font.family: root.ui.fontFamily
                            font.pixelSize: 13
                            selectByMouse: true
                            validator: IntValidator { bottom: 1; top: 3600 }
                            onAccepted: root.request("setRefreshInterval", {kind: intervalRow.modelData.kind, seconds: Number(text)})
                            background: Rectangle { radius: 8; color: root.ui.surfaceAlt; border.color: seconds.activeFocus ? root.ui.accent : root.ui.border }
                        }
                        Text { text: "秒"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                        UiButton {
                            objectName: "systemRefreshApply_" + intervalRow.modelData.kind
                            ui: root.ui; text: "应用"; variant: "secondary"
                            onClicked: root.request("setRefreshInterval", {kind: intervalRow.modelData.kind, seconds: Number(seconds.text)})
                        }
                        Item { Layout.fillWidth: true }
                    }
                }
                Text { text: "可设置 1–3600 秒，与底栏快捷设置同步。账户安全检查每秒执行；K 线及历史统计每 60 秒刷新，日志每 30 秒刷新。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                spacing: 16
                SectionHeading { ui: root.ui; title: "外观与窗口" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 18
                    Text { text: "界面主题"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; Layout.preferredWidth: 150 }
                    UiComboBox { objectName: "systemThemeSelector"; ui: root.ui; Layout.preferredWidth: 240; model: ["日间", "夜间"]; currentIndex: root.themeName === "dark" ? 1 : 0; onActivated: root.request("setTheme", {theme: currentIndex === 1 ? "dark" : "light"}) }
                    Item { Layout.fillWidth: true }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 18
                    Text { text: "窗口模式"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; Layout.preferredWidth: 150 }
                    UiButton { ui: root.ui; text: root.fullscreen ? "退出全屏" : "进入全屏"; variant: "secondary"; onClicked: root.request("toggleFullscreen", {}) }
                    Text { text: "F11 切换 · Esc 退出 · 仅当前会话"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                    Item { Layout.fillWidth: true }
                }
            }
            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                spacing: 16
                SectionHeading { ui: root.ui; title: "编码与运行环境" }
                SettingsInfoRow { ui: root.ui; label: "全局文本编码"; value: root.systemData.textEncoding || "UTF-8" }
                Text { text: "工作台的配置与文本文件统一使用 UTF-8，支持中文。系统默认编码与 Python UTF-8 模式是环境信息，应用文件编码始终为 UTF-8。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                SettingsInfoRow { ui: root.ui; label: "系统默认编码"; value: root.systemData.systemEncoding || "—" }
                SettingsInfoRow { ui: root.ui; label: "Python UTF-8 模式"; value: root.systemData.pythonUtf8Mode ? "已启用" : "未启用" }
                SettingsInfoRow { ui: root.ui; label: "运行环境"; value: (root.systemData.platform || "—") + " · Python " + (root.systemData.pythonVersion || "—") }
            }
            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                spacing: 16
                SectionHeading { ui: root.ui; title: "连接与本地数据" }
                SettingsInfoRow { ui: root.ui; label: "MT5 客户端"; value: root.systemData.terminalPath || "—" }
                SettingsInfoRow { ui: root.ui; label: "当前观察品种"; value: root.systemData.symbol || "XAUUSDc" }
                SettingsInfoRow { ui: root.ui; label: "账户币种与换算"; value: (root.systemData.accountCurrency || "USC") + " · " + (root.systemData.currencyRatio || "100 USC = 1 USD") }
                SettingsInfoRow { ui: root.ui; label: "本地数据目录"; value: root.systemData.stateDirectory || "—" }
                SettingsInfoRow { ui: root.ui; label: "日志与图片目录"; value: root.systemData.journalDirectory || "—" }
                Text { text: "品种和 USC 账户规则为当前版本固定配置。客户端路径可在启动时通过 --terminal 指定；目录内容可选中复制。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
            Item { Layout.preferredHeight: 22 }
        }
    }
}
