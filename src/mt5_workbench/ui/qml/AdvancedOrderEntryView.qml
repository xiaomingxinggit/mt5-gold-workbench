import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "advancedOrderEntryView"
    property var ui
    property var pageData: ({})
    property var bridge
    property var form: ({ budget: "", usage: "95", center: "", tolerance: "", stop: "", takeProfit: "", levels: "3", weights: "1,2,3", mode: "weighted" })
    property bool resultStale: true
    readonly property var modes: ["weighted", "equal_risk", "max_lots_ladder", "max_lots_single"]

    function value(name, fallback) {
        var result = root.pageData ? root.pageData[name] : undefined
        return result === undefined || result === null || result === "" ? fallback : result
    }
    function updateField(name, content) {
        var next = Object.assign({}, root.form)
        next[name] = content
        root.form = next
        root.resultStale = true
        root.request("entryInvalidate", {})
    }
    function request(action, payload) {
        if (root.bridge) root.bridge.perform(action, payload)
    }
    function calculate() {
        root.request("entryCalculate", root.form)
        root.resultStale = false
    }
    function rangeHint() {
        var center = Number(root.form.center)
        var tolerance = Number(root.form.tolerance)
        if (isFinite(center) && center > 0 && isFinite(tolerance) && tolerance > 0 && center > tolerance)
            return "自动入场区间  " + (center - tolerance).toFixed(3) + "  ～  " + (center + tolerance).toFixed(3)
        return "示例：4220 ± 1 → 4219～4221；按档数等距生成价格。"
    }
    function rowRiskTotal() {
        var rows = root.value("rows", [])
        var total = 0
        for (var i = 0; i < rows.length; ++i) total += Number(rows[i].riskUsd) || 0
        return Math.max(0.01, total)
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

            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 1360 ? 2 : 1
                columnSpacing: 16
                rowSpacing: 16

                UiCard {
                    ui: root.ui
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    padding: 22
                    spacing: 16
                    SectionHeading { ui: root.ui; title: "配置参数"; subtitle: "风险预算以 USD 计，预算使用比例默认 95%。"; Layout.fillWidth: true }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 12
                        rowSpacing: 14
                        Repeater {
                            model: [
                                {key:"budget", title:"风险预算 · USD", hint:"例如 30"},
                                {key:"usage", title:"预算使用比例 · %", hint:"95"},
                                {key:"center", title:"目标入场价", hint:"例如 4220"},
                                {key:"tolerance", title:"误差度 · ±价格", hint:"例如 1"},
                                {key:"stop", title:"统一止损价", hint:"输入止损"},
                                {key:"takeProfit", title:"统一止盈价 · 可选", hint:"留空则不设止盈"},
                                {key:"levels", title:"开仓档数 · 2～12", hint:"3"},
                                {key:"weights", title:"每档风险权重", hint:"1,2,3"}
                            ]
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 7
                                Text { text: modelData.title; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                                TextField {
                                    id: entryField
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 42
                                    text: root.form[modelData.key]
                                    placeholderText: modelData.hint
                                    enabled: modelData.key !== "weights" || root.form.mode === "weighted"
                                    selectByMouse: true
                                    color: root.ui.text
                                    placeholderTextColor: root.ui.muted
                                    font.family: root.ui.fontFamily; font.pixelSize: 14
                                    leftPadding: 12; rightPadding: 12
                                    onTextEdited: root.updateField(modelData.key, text)
                                    background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: entryField.activeFocus ? root.ui.accent : root.ui.border }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: rangeText.implicitHeight + 24
                        radius: 9; color: root.ui.accentSoft
                        Text {
                            id: rangeText
                            anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 13; anchors.rightMargin: 13
                            text: root.rangeHint()
                            color: root.ui.accent; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        Text { text: "风险分配方式"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        UiComboBox {
                            id: modeSelector
                            ui: root.ui
                            objectName: "entryModeSelector"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 42
                            model: ["加权分配 · 自定义风险比例", "等风险 · 每档承担相同风险", "覆盖区间 · 尽量增大总手数", "单点开仓 · 总手数最大"]
                            currentIndex: Math.max(0, root.modes.indexOf(root.form.mode))
                            onActivated: root.updateField("mode", root.modes[currentIndex])
                            font.pixelSize: 14
                        }
                        Text { text: "权重 1,2,3 表示三个档位分别承担 1:2:3 的预算。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }
                    UiButton { ui: root.ui; text: "计算 LIMIT 挂单"; variant: "primary"; Layout.fillWidth: true; onClicked: root.calculate() }
                }

                UiCard {
                    ui: root.ui
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    padding: 22
                    spacing: 16
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "测算结果"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        UiButton {
                            ui: root.ui; text: "复制配置"; variant: "secondary"
                            enabled: !root.resultStale && root.value("rows", []).length > 0
                            onClicked: root.request("entryCopy", {})
                        }
                        UiButton {
                            ui: root.ui; text: "预览 LIMIT 挂单"; variant: "primary"
                            enabled: !root.resultStale && root.value("canPreview", false)
                            onClicked: root.request("entryPreview", root.form)
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.resultStale ? "填写参数并计算；发送前会再次核对账户与报价。" : root.value("info", "等待测算结果。")
                        color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 3
                        columnSpacing: 10
                        MetricCard { ui: root.ui; Layout.fillWidth: true; title: "总手数"; value: root.resultStale ? "—" : root.value("lot", "—"); note: "LIMIT 挂单总量" }
                        MetricCard { ui: root.ui; Layout.fillWidth: true; title: "预计止损风险"; value: root.resultStale ? "—" : root.value("risk", "—"); note: "USD · 预算上限内"; tone: "accent" }
                        MetricCard { ui: root.ui; Layout.fillWidth: true; title: "原预算剩余"; value: root.resultStale ? "—" : root.value("unused", "—"); note: "USD" }
                    }

                    Text { text: "建议挂单"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 38
                        radius: 8; color: root.ui.surfaceAlt
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                            Repeater {
                                model: ["档位", "建议类型", "入场价", "手数", "止损距离", "风险 USD"]
                                delegate: Text { required property var modelData; Layout.fillWidth: true; Layout.preferredWidth: 1; text: modelData; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold }
                            }
                        }
                    }
                    Text {
                        visible: root.resultStale || !root.value("rows", []).length
                        text: "计算后在这里查看分档价格、手数与风险。"
                        color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13
                        Layout.topMargin: 12; Layout.bottomMargin: 12
                    }
                    Repeater {
                        model: root.resultStale ? [] : root.value("rows", [])
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            objectName: "advancedOrderResultRow_" + index
                            Layout.fillWidth: true
                            implicitHeight: 38
                            radius: 7; color: index % 2 ? root.ui.surfaceAlt : root.ui.surface
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                                Repeater {
                                    model: [modelData.level, modelData.type, modelData.price, modelData.volume, modelData.stopDistance, modelData.riskUsd]
                                    delegate: Text {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: 1
                                        text: String(modelData === undefined || modelData === null ? "—" : modelData)
                                        color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 13
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                    Text { text: "每档风险分配"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Repeater {
                        model: root.resultStale ? [] : root.value("rows", [])
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 10
                            Text { text: String(modelData.price); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 78 }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 10; radius: 5; color: root.ui.surfaceAlt
                                Rectangle {
                                    height: parent.height; radius: 5; color: root.ui.accent
                                    width: Math.max(5, parent.width * Math.min(1, Number(modelData.riskUsd) / root.rowRiskTotal()))
                                }
                            }
                            Text { text: String(modelData.riskUsd) + " USD"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 12; Layout.preferredWidth: 92; horizontalAlignment: Text.AlignRight }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: comparisonText.implicitHeight + 24
                        radius: 8; color: root.ui.surfaceAlt
                        Text {
                            id: comparisonText
                            anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 13; anchors.rightMargin: 13
                            text: root.resultStale ? "计算后显示各分配方式的总手数。" : root.value("comparison", "")
                            color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.value("warning", "测算不包含滑点、跳空、手续费和保证金限制。")
                        color: root.ui.warning; font.family: root.ui.fontFamily; font.pixelSize: 12; wrapMode: Text.WordWrap
                    }
                }
            }
            Item { Layout.preferredHeight: 20 }
        }
    }
}
