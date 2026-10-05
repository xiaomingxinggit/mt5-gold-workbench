import QtQuick
import QtQuick.Layouts

Item {
    id: root
    objectName: "orderEntryView"
    property var ui
    property var pageData: ({})
    property var basicData: ({})
    property var market: ({})
    property var account: ({})
    property var connection: ({})
    property var bridge
    property int currentTab: 0
    readonly property string accountKey: String(account.login || "") + ":" + String(account.server || "")

    function selectTab(index) {
        if (currentTab === index) return
        if (bridge) bridge.perform("entryTabChanged", {})
        advanced.resultStale = true
        currentTab = index
    }
    onAccountKeyChanged: {
        basic.resetForm()
        advanced.resultStale = true
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 24; Layout.rightMargin: 24; Layout.topMargin: 24
            spacing: 6
            Text { text: "下单管理"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: root.currentTab === 0 ? "指定价格与手数，预览后发送单笔 LIMIT 限价单。" : "以目标价和误差度生成入场区间，按风险预算分配 LIMIT 挂单。"
                color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14; wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.topMargin: 12
                spacing: 6
                UiButton {
                    objectName: "basicOrderTab"
                    ui: root.ui; text: "基础下单"
                    variant: root.currentTab === 0 ? "primary" : "ghost"
                    onClicked: root.selectTab(0)
                }
                UiButton {
                    objectName: "advancedOrderTab"
                    ui: root.ui; text: "高级下单"
                    variant: root.currentTab === 1 ? "primary" : "ghost"
                    onClicked: root.selectTab(1)
                }
            }
        }
        StackLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            currentIndex: root.currentTab
            BasicOrderEntryView {
                id: basic
                ui: root.ui; pageData: root.basicData; market: root.market
                account: root.account; connection: root.connection; bridge: root.bridge
            }
            AdvancedOrderEntryView {
                id: advanced
                ui: root.ui; pageData: root.pageData; bridge: root.bridge
            }
        }
    }
}
