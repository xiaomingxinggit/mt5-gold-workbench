import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 1440
    height: 900
    minimumWidth: 1200
    minimumHeight: 800
    visible: true
    title: "MT5 黄金交易工作台"
    color: theme.bg

    property var backend: bridge
    property var connection: ({})
    property var account: ({})
    property var market: ({})
    property var dashboardData: ({})
    property var overviewData: ({})
    property var journalData: ({})
    property var optimizerData: ({})
    property var controlsData: ({})
    property var monitorData: ({})
    property var confirmation: ({})
    property string themeName: "light"
    property string statusText: "就绪"
    property bool fullscreen: false
    property string confirmationToken: confirmation.token ? String(confirmation.token) : ""
    property string page: "dashboard"
    property bool compactSidebar: width < 1380

    function setSection(name, value) {
        if (name === "connection") connection = value || ({});
        else if (name === "account") account = value || ({});
        else if (name === "market") market = value || ({});
        else if (name === "dashboard") dashboardData = value || ({});
        else if (name === "overview") overviewData = value || ({});
        else if (name === "journal") journalData = value || ({});
        else if (name === "optimizer") optimizerData = value || ({});
        else if (name === "controls") controlsData = value || ({});
        else if (name === "monitor") monitorData = value || ({});
        else if (name === "confirmation") confirmation = value || ({});
        else if (name === "theme") themeName = String(value);
        else if (name === "status") statusText = String(value);
        else if (name === "page") page = String(value);
        else if (name === "fullscreen") fullscreen = Boolean(value);
    }

    Component.onCompleted: {
        const initial = backend ? backend.state : ({});
        for (const key in initial) setSection(key, initial[key]);
    }
    onFullscreenChanged: {
        if (fullscreen) showFullScreen(); else showNormal();
    }
    Shortcut {
        sequence: "F11"
        onActivated: root.action("toggleFullscreen", {})
    }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (root.confirmationToken.length > 0) root.action("cancelConfirm", {})
            else if (root.fullscreen) root.action("toggleFullscreen", {})
        }
    }
    Connections {
        target: root.backend
        function onSectionChanged(name, value) { root.setSection(name, value); }
    }

    function action(name, payload) {
        if (backend) backend.perform(name, payload || {})
    }

    function pageIndex(name) {
        const names = ["dashboard", "orders", "journal", "optimizer", "controls", "monitor"]
        const index = names.indexOf(name)
        return index < 0 ? 0 : index
    }

    Theme {
        id: theme
        dark: root.themeName === "dark"
    }

    font.family: theme.fontFamily
    font.pixelSize: 13

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Rectangle {
            id: topbar
            Layout.fillWidth: true
            Layout.preferredHeight: 68
            radius: 14
            color: theme.surface
            border.width: 1
            border.color: theme.border

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 26
                anchors.rightMargin: 22
                spacing: 12

                RowLayout {
                    spacing: 10
                    Text {
                        text: "MT5"
                        color: theme.text
                        font.family: theme.fontFamily
                        font.pixelSize: 22
                        font.weight: Font.Bold
                        Layout.alignment: Qt.AlignVCenter
                    }
                    Rectangle {
                        Layout.preferredWidth: 1
                        Layout.preferredHeight: 20
                        color: theme.border
                        Layout.alignment: Qt.AlignVCenter
                    }
                    Text {
                        text: "黄金交易工作台"
                        color: theme.muted
                        font.family: theme.fontFamily
                        font.pixelSize: 15
                        Layout.alignment: Qt.AlignVCenter
                    }
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    Layout.preferredHeight: 32
                    Layout.preferredWidth: statusRow.implicitWidth + 22
                    radius: 16
                    color: connection.locked ? (theme.dark ? "#46332D" : "#FFF1E1")
                          : connection.connected ? theme.accentSoft : theme.surfaceAlt
                    Row {
                        id: statusRow
                        anchors.centerIn: parent
                        spacing: 7
                        Rectangle {
                            width: 7
                            height: 7
                            radius: 4
                            color: connection.locked ? theme.warning : connection.connected ? theme.positive : theme.faint
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: connection.locked ? "账户受限" : connection.connected ? "已连接" : "未连接"
                            color: connection.locked ? theme.warning : connection.connected ? theme.positive : theme.muted
                            font.family: theme.fontFamily
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                    }
                }

                UiButton {
                    ui: theme
                    text: theme.dark ? "日间" : "夜间"
                    variant: "secondary"
                    onClicked: root.action("toggleTheme", {})
                }
                UiButton {
                    ui: theme
                    text: root.visibility === Window.FullScreen ? "退出全屏" : "全屏"
                    variant: "secondary"
                    onClicked: root.action("toggleFullscreen", {})
                }
                UiButton {
                    ui: theme
                    text: "重新连接"
                    variant: "secondary"
                    onClicked: root.action("reconnect", {})
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10

            Rectangle {
                id: sidebar
                Layout.preferredWidth: root.compactSidebar ? 198 : 222
                Layout.fillHeight: true
                radius: 14
                color: theme.sidebar
                border.width: 1
                border.color: theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 0

                    Text {
                        text: "工作区"
                        color: theme.faint
                        font.family: theme.fontFamily
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        Layout.leftMargin: 12
                        Layout.topMargin: 18
                        Layout.bottomMargin: 12
                    }

                    Repeater {
                        model: [
                            { page: "dashboard", label: "总览看板", icon: "dashboard" },
                            { page: "orders", label: "交易概览", icon: "orders" },
                            { page: "journal", label: "行情日志", icon: "journal" },
                            { page: "optimizer", label: "下单管理", icon: "allocation" },
                            { page: "controls", label: "控制面板", icon: "controls" },
                            { page: "monitor", label: "实验功能", icon: "chart-line" }
                        ]
                        delegate: Rectangle {
                            id: navItem
                            required property var modelData
                            readonly property bool selected: root.page === modelData.page
                            Layout.fillWidth: true
                            Layout.preferredHeight: 47
                            Layout.bottomMargin: 3
                            radius: 9
                            color: selected ? theme.navActive : navMouse.containsMouse ? theme.hover : "transparent"

                            Rectangle {
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                width: 3
                                height: 20
                                radius: 2
                                color: theme.accent
                                visible: navItem.selected
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 8
                                spacing: 12
                                Image {
                                    source: "../resources/icons/svg/" + (theme.dark ? "dark" : "light") + "/"
                                          + navItem.modelData.icon + (navItem.selected ? "-active" : "") + ".svg"
                                    sourceSize.width: 19
                                    sourceSize.height: 19
                                    Layout.preferredWidth: 19
                                    Layout.preferredHeight: 19
                                    fillMode: Image.PreserveAspectFit
                                }
                                Text {
                                    text: navItem.modelData.label
                                    color: navItem.selected ? theme.accent : theme.text
                                    font.family: theme.fontFamily
                                    font.pixelSize: 14
                                    font.weight: navItem.selected ? Font.DemiBold : Font.Medium
                                    Layout.fillWidth: true
                                }
                            }
                            MouseArea {
                                id: navMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.action("navigate", {page: navItem.modelData.page})
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        Layout.topMargin: 22
                        Layout.bottomMargin: 20
                        color: theme.border
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 13
                        spacing: 5
                        Text {
                            text: "观察品种"
                            color: theme.muted
                            font.family: theme.fontFamily
                            font.pixelSize: 11
                        }
                        Text {
                            text: "XAUUSDc"
                            color: theme.text
                            font.family: theme.fontFamily
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                    }

                    Item { Layout.fillHeight: true }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 70
                        radius: 10
                        color: theme.surfaceAlt
                        Text {
                            anchors.fill: parent
                            anchors.margins: 12
                            text: "交易操作需预览确认\n下单管理仅发送 LIMIT 挂单"
                            color: theme.muted
                            font.family: theme.fontFamily
                            font.pixelSize: 11
                            lineHeight: 1.3
                            verticalAlignment: Text.AlignVCenter
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 14
                color: theme.bg

                StackLayout {
                    anchors.fill: parent
                    currentIndex: root.pageIndex(root.page)

                    DashboardView {
                        ui: theme
                        pageData: root.dashboardData
                        account: root.account
                        market: root.market
                        connection: root.connection
                        bridge: root.backend
                    }
                    TradeOverviewView {
                        ui: theme
                        pageData: root.overviewData
                        account: root.account
                        connection: root.connection
                        bridge: root.backend
                    }
                    JournalView {
                        ui: theme
                        pageData: root.journalData
                        bridge: root.backend
                    }
                    OrderEntryView {
                        ui: theme
                        pageData: root.optimizerData
                        bridge: root.backend
                    }
                    ControlView {
                        ui: theme
                        pageData: root.controlsData
                        bridge: root.backend
                    }
                    MonitorView {
                        ui: theme
                        pageData: root.monitorData
                        bridge: root.backend
                    }
                }

                Rectangle {
                    anchors.fill: parent
                    z: 2
                    visible: root.connection.locked === true
                    color: theme.dark ? "#D80C1420" : "#DDF4F7FB"
                    radius: 14

                    UiCard {
                        ui: theme
                        width: Math.min(parent.width - 80, 480)
                        anchors.centerIn: parent
                        padding: 26
                        spacing: 12
                        Text {
                            text: "当前账户无法使用工作台"
                            color: theme.warning
                            font.family: theme.fontFamily
                            font.pixelSize: 21
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            text: root.connection.message || "此工作台仅支持 USC 美分账户。请切换账户后重新连接。"
                            color: theme.text
                            font.family: theme.fontFamily
                            font.pixelSize: 14
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            text: "请在 MT5 客户端切换至美分账户。"
                            color: theme.muted
                            font.family: theme.fontFamily
                            font.pixelSize: 12
                            Layout.fillWidth: true
                        }
                    }

                    MouseArea { anchors.fill: parent; z: -1 }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            radius: 9
            color: theme.surface
            border.width: 1
            border.color: theme.border
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                Text {
                    text: root.statusText
                    color: theme.muted
                    font.family: theme.fontFamily
                    font.pixelSize: 11
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Text {
                    text: "报价 1 秒  ·  持仓 5 秒  ·  订单 30 秒"
                    color: theme.faint
                    font.family: theme.fontFamily
                    font.pixelSize: 11
                }
            }
        }
    }

    Dialog {
        id: confirmationDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(root.width - 80, 780)
        height: Math.min(root.height - 100, 690)
        visible: root.confirmationToken.length > 0
        modal: true
        closePolicy: Popup.NoAutoClose
        padding: 0
        background: Rectangle {
            color: theme.surface
            radius: 16
            border.width: 1
            border.color: theme.border
        }
        contentItem: ColumnLayout {
            spacing: 0

            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 26
                Layout.rightMargin: 26
                Layout.topMargin: 22
                spacing: 7
                Text {
                    text: root.confirmation.title || "确认操作"
                    color: theme.text
                    font.family: theme.fontFamily
                    font.pixelSize: 20
                    font.weight: Font.DemiBold
                }
                Text {
                    text: root.confirmation.heading || "请核对以下内容"
                    color: theme.muted
                    font.family: theme.fontFamily
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            ScrollView {
                id: confirmScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: 26
                Layout.rightMargin: 26
                Layout.topMargin: 18
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ColumnLayout {
                    width: confirmScroll.availableWidth
                    spacing: 12

                    Text {
                        text: root.confirmation.details || ""
                        visible: text.length > 0
                        color: theme.text
                        font.family: theme.fontFamily
                        font.pixelSize: 13
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: confirmTable.implicitHeight + 20
                        visible: (root.confirmation.rows || []).length > 0
                        radius: 9
                        color: theme.surfaceAlt
                        ColumnLayout {
                            id: confirmTable
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 0
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 29
                                spacing: 8
                                Repeater {
                                    model: root.confirmation.columns || []
                                    delegate: Text {
                                        required property var modelData
                                        text: String(modelData)
                                        color: theme.muted
                                        font.family: theme.fontFamily
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                            Repeater {
                                model: root.confirmation.rows || []
                                delegate: RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 31
                                    spacing: 8
                                    Repeater {
                                        model: parent.modelData
                                        delegate: Text {
                                            text: String(modelData)
                                            color: theme.text
                                            font.family: theme.fontFamily
                                            font.pixelSize: 11
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Text {
                        text: root.confirmation.warning || ""
                        visible: text.length > 0
                        color: theme.warning
                        font.family: theme.fontFamily
                        font.pixelSize: 12
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                color: "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 26
                    anchors.rightMargin: 26
                    spacing: 10
                    Item { Layout.fillWidth: true }
                    UiButton {
                        ui: theme
                        text: "取消"
                        Layout.preferredWidth: 90
                        onClicked: root.action("cancelConfirm", {})
                    }
                    UiButton {
                        ui: theme
                        text: root.confirmation.confirmText || "确认"
                        variant: root.confirmation.danger ? "danger" : "primary"
                        Layout.preferredWidth: Math.max(110, implicitWidth)
                        onClicked: root.action("confirm", {token: root.confirmationToken})
                    }
                }
            }
        }
    }
}
