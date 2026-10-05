import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var ui
    property var pageData: ({})
    property var bridge
    property string scope: "symbol"

    function value(name, fallback) {
        var result = root.pageData ? root.pageData[name] : undefined
        return result === undefined || result === null || result === "" ? fallback : result
    }
    function request(action, payload) {
        if (root.bridge) root.bridge.perform(action, payload)
    }
    function changeScope(value) {
        if (root.scope === value) return
        root.scope = value
        root.request("controlsRefresh", {"scope": root.scope})
    }
    function preview(kind) {
        root.request("controlsPreview", {"kind": kind, "scope": root.scope, "deviation": deviationInput.text})
    }
    function validPositiveNumber(value) {
        var content = String(value).trim()
        return /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(content) && isFinite(Number(content)) && Number(content) > 0
    }
    function validBatchStops() {
        var sl = stopLossInput.text.trim()
        var tp = takeProfitInput.text.trim()
        return (sl !== "" || tp !== "")
                && (sl === "" || root.validPositiveNumber(sl))
                && (tp === "" || root.validPositiveNumber(tp))
    }

    ScrollView {
        id: viewport
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

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
                    Text { text: "控制面板"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { text: "选择范围、预览目标并确认。平仓、撤单和保护价修改都会影响真实账户。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14 }
                }
                UiButton { ui: root.ui; text: "刷新目标"; variant: "secondary"; onClicked: root.request("controlsRefresh", {"scope": root.scope}) }
            }

            UiCard {
                ui: root.ui
                Layout.fillWidth: true
                padding: 22
                spacing: 13
                SectionHeading { ui: root.ui; title: "操作范围"; subtitle: "目标列表随范围变化重新读取。"; Layout.fillWidth: true }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 22
                    RadioButton {
                        id: symbolScope
                        text: "仅当前品种 XAUUSDc"
                        checked: root.scope === "symbol"
                        onClicked: root.changeScope("symbol")
                        font.family: root.ui.fontFamily; font.pixelSize: 14
                        contentItem: Text {
                            text: symbolScope.text
                            color: root.ui.text
                            font.family: root.ui.fontFamily; font.pixelSize: 14
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: symbolScope.indicator.width + symbolScope.spacing
                        }
                    }
                    RadioButton {
                        id: accountScope
                        text: "整个账户 · 所有品种"
                        checked: root.scope === "account"
                        onClicked: root.changeScope("account")
                        font.family: root.ui.fontFamily; font.pixelSize: 14
                        contentItem: Text {
                            text: accountScope.text
                            color: root.ui.text
                            font.family: root.ui.fontFamily; font.pixelSize: 14
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: accountScope.indicator.width + accountScope.spacing
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
                Text { text: root.value("accountLabel", "账户尚未连接"); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                Text { text: root.value("summary", "等待读取持仓与挂单"); color: root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 18; font.weight: Font.DemiBold }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 1170 ? 2 : 1
                columnSpacing: 16
                rowSpacing: 16
                UiCard {
                    ui: root.ui
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: 22
                    spacing: 13
                    SectionHeading { ui: root.ui; title: "全部平仓"; subtitle: "按所选范围逐笔平仓，挂单不会自动撤销。"; Layout.fillWidth: true }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Text { text: "最大偏差"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                        TextField {
                            id: deviationInput
                            Layout.preferredWidth: 100
                            Layout.preferredHeight: 40
                            text: "50"
                            validator: IntValidator { bottom: 1; top: 1000 }
                            selectByMouse: true
                            color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14
                            leftPadding: 10; rightPadding: 10
                            background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: deviationInput.activeFocus ? root.ui.accent : root.ui.border }
                        }
                        Text { text: "MT5 point · 1–1000"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        Item { Layout.fillWidth: true }
                    }
                    UiButton {
                        ui: root.ui; text: "预览全部平仓"; variant: "danger"; Layout.fillWidth: true
                        enabled: root.value("canClose", false)
                        onClicked: root.preview("close")
                    }
                }
                UiCard {
                    ui: root.ui
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: 22
                    spacing: 13
                    SectionHeading { ui: root.ui; title: "删除所有挂单"; subtitle: "按所选范围逐笔撤销仍在等待的挂单。"; Layout.fillWidth: true }
                    Text { Layout.fillWidth: true; text: "不会平仓。挂单若已成交，撤单无法撤销该持仓。"; color: root.ui.warning; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap }
                    Item { Layout.fillHeight: true; Layout.minimumHeight: 12 }
                    UiButton {
                        ui: root.ui; text: "预览删除挂单"; variant: "danger"; Layout.fillWidth: true
                        enabled: root.value("canRemove", false)
                        onClicked: root.preview("remove")
                    }
                }
                UiCard {
                    objectName: "controlBreakevenCard"
                    ui: root.ui
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: 22
                    spacing: 13
                    SectionHeading { ui: root.ui; title: "一键推保本"; subtitle: "按所选范围，为每笔持仓设置可锁定约指定 USD 利润的止损。"; Layout.fillWidth: true }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Text { text: "目标锁盈"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                        TextField {
                            id: beAmountInput
                            Layout.preferredWidth: 110
                            Layout.preferredHeight: 40
                            text: "1"
                            inputMethodHints: Qt.ImhFormattedNumbersOnly
                            selectByMouse: true
                            color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14
                            leftPadding: 10; rightPadding: 10
                            background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: beAmountInput.activeFocus ? root.ui.accent : root.ui.border }
                        }
                        Text { text: "USD / 笔"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        Item { Layout.fillWidth: true }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "默认 1 USD。预览会列出每笔持仓的新止损价；手续费和隔夜费可能影响实际净利。"
                        color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap
                    }
                    Item { Layout.fillHeight: true; Layout.minimumHeight: 4 }
                    UiButton {
                        ui: root.ui; text: "预览一键推保本"; variant: "primary"; Layout.fillWidth: true
                        enabled: root.value("positions", []).length > 0 && root.validPositiveNumber(beAmountInput.text)
                        onClicked: root.request("previewBreakEven", {"scope": root.scope, "amountUsd": beAmountInput.text.trim()})
                    }
                }
                UiCard {
                    objectName: "controlBatchStopsCard"
                    ui: root.ui
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    padding: 22
                    spacing: 13
                    SectionHeading { ui: root.ui; title: "批量设置止盈 / 止损"; subtitle: "为所选范围内的持仓设置统一绝对价。"; Layout.fillWidth: true }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.width >= 650 ? 2 : 1
                        columnSpacing: 12
                        rowSpacing: 10
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text { text: "止损价 · 可选"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                            TextField {
                                id: stopLossInput
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                placeholderText: "留空则保持原值"
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                selectByMouse: true
                                color: root.ui.text; placeholderTextColor: root.ui.muted
                                font.family: root.ui.fontFamily; font.pixelSize: 14
                                leftPadding: 10; rightPadding: 10
                                background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: stopLossInput.activeFocus ? root.ui.accent : root.ui.border }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text { text: "止盈价 · 可选"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                            TextField {
                                id: takeProfitInput
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                placeholderText: "留空则保持原值"
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                selectByMouse: true
                                color: root.ui.text; placeholderTextColor: root.ui.muted
                                font.family: root.ui.fontFamily; font.pixelSize: 14
                                leftPadding: 10; rightPadding: 10
                                background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: takeProfitInput.activeFocus ? root.ui.accent : root.ui.border }
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "至少填写一项，价格须大于 0。统一价格只适用于同一品种；全账户含混合品种时，请切到当前品种范围。"
                        color: root.ui.warning; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap
                    }
                    Item { Layout.fillHeight: true; Layout.minimumHeight: 4 }
                    UiButton {
                        ui: root.ui; text: "预览批量设置"; variant: "primary"; Layout.fillWidth: true
                        enabled: root.value("positions", []).length > 0 && root.validBatchStops()
                        onClicked: root.request("previewBatchStops", {"scope": root.scope, "sl": stopLossInput.text.trim(), "tp": takeProfitInput.text.trim()})
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: statusText.implicitHeight + 24
                radius: 9
                color: root.ui.surfaceAlt
                Text {
                    id: statusText
                    anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 14; anchors.rightMargin: 14
                    text: root.value("status", "尚未执行控制操作。")
                    color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 1420 ? 2 : 1
                columnSpacing: 16
                rowSpacing: 16

                UiCard {
                    ui: root.ui
                    Layout.fillWidth: true
                    padding: 22
                    spacing: 12
                    SectionHeading { ui: root.ui; title: "范围内持仓"; subtitle: "当前范围的实时持仓快照"; Layout.fillWidth: true }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: 34; radius: 7; color: root.ui.surfaceAlt
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                            Repeater { model: ["Ticket", "品种", "方向", "手数", "开仓价", "浮盈亏"]
                                delegate: Text { required property var modelData; Layout.fillWidth: true; text: modelData; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight } }
                        }
                    }
                    Text { visible: !root.value("positions", []).length; text: "当前范围内没有持仓"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; Layout.topMargin: 10; Layout.bottomMargin: 10 }
                    Repeater {
                        model: root.value("positions", [])
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true; implicitHeight: 36; radius: 7
                            color: index % 2 ? root.ui.surfaceAlt : root.ui.surface
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                                Repeater {
                                    model: [modelData.ticket, modelData.symbol, modelData.side, modelData.volume, modelData.openPrice, modelData.profit]
                                    delegate: Text { required property var modelData; Layout.fillWidth: true; text: String(modelData === undefined || modelData === null ? "—" : modelData); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                            }
                        }
                    }
                }

                UiCard {
                    ui: root.ui
                    Layout.fillWidth: true
                    padding: 22
                    spacing: 12
                    SectionHeading { ui: root.ui; title: "范围内挂单"; subtitle: "当前范围的待成交订单"; Layout.fillWidth: true }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: 34; radius: 7; color: root.ui.surfaceAlt
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                            Repeater { model: ["Ticket", "品种", "类型", "手数", "挂单价", "止损"]
                                delegate: Text { required property var modelData; Layout.fillWidth: true; text: modelData; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight } }
                        }
                    }
                    Text { visible: !root.value("orders", []).length; text: "当前范围内没有挂单"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; Layout.topMargin: 10; Layout.bottomMargin: 10 }
                    Repeater {
                        model: root.value("orders", [])
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true; implicitHeight: 36; radius: 7
                            color: index % 2 ? root.ui.surfaceAlt : root.ui.surface
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                                Repeater {
                                    model: [modelData.ticket, modelData.symbol, modelData.type, modelData.volume, modelData.price, modelData.stop]
                                    delegate: Text { required property var modelData; Layout.fillWidth: true; text: String(modelData === undefined || modelData === null ? "—" : modelData); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                            }
                        }
                    }
                }
            }
            Item { Layout.preferredHeight: 20 }
        }
    }
}
