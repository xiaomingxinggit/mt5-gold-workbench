import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "journalView"
    property var ui
    property var pageData: ({})
    property var bridge
    property bool composing: false
    property string draftBody: ""
    property var selectedPositionIds: []
    property int lastPublishedRevision: 0
    property string lastAccountLabel: ""
    readonly property int calendarWeeks: weeksInYear()
    readonly property real calendarGridWidth: calendarWeeks * cellSize() + (calendarWeeks - 1) * 3

    onPageDataChanged: {
        var label = String(root.value("accountLabel", ""))
        if (root.lastAccountLabel !== "" && label !== root.lastAccountLabel) {
            root.draftBody = ""
            root.selectedPositionIds = []
            root.composing = false
        }
        root.lastAccountLabel = label
        var revision = Number(root.value("publishedRevision", 0))
        if (revision > root.lastPublishedRevision) {
            root.draftBody = ""
            root.selectedPositionIds = []
            root.composing = false
        }
        root.lastPublishedRevision = revision
    }

    function value(name, fallback) {
        var result = root.pageData ? root.pageData[name] : undefined
        return result === undefined || result === null || result === "" ? fallback : result
    }
    function request(action, payload) {
        if (root.bridge) root.bridge.perform(action, payload)
    }
    function dayKey(week, weekday) {
        var year = Number(root.value("year", new Date().getFullYear()))
        var first = new Date(year, 0, 1)
        var mondayOffset = (first.getDay() + 6) % 7
        var date = new Date(year, 0, 1 - mondayOffset + week * 7 + weekday)
        if (date.getFullYear() !== year || date > new Date()) return ""
        return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0")
    }
    function dayCount(key) {
        var counts = root.value("heatmap", {})
        return Number(counts[key] || 0)
    }
    function monthWeekIndex(month) {
        var year = Number(root.value("year", new Date().getFullYear()))
        var first = new Date(year, 0, 1)
        var mondayOffset = (first.getDay() + 6) % 7
        var elapsedDays = Math.round((Date.UTC(year, month, 1) - Date.UTC(year, 0, 1)) / 86400000)
        return Math.floor((mondayOffset + elapsedDays) / 7)
    }
    function weeksInYear() {
        var year = Number(root.value("year", new Date().getFullYear()))
        var mondayOffset = (new Date(year, 0, 1).getDay() + 6) % 7
        var days = Math.round((Date.UTC(year + 1, 0, 1) - Date.UTC(year, 0, 1)) / 86400000)
        return Math.ceil((mondayOffset + days) / 7)
    }
    function togglePosition(id, selected) {
        var current = root.selectedPositionIds.slice()
        var target = Number(id)
        var at = current.indexOf(target)
        if (selected && at < 0 && current.length < 20) current.push(target)
        if (!selected && at >= 0) current.splice(at, 1)
        root.selectedPositionIds = current
    }
    function positionResult(position) {
        var status = String(position.status || "open")
        if (status === "closed") return "已平仓 · 最终 " + String(position.resultUsd === undefined ? "—" : position.resultUsd) + " USD"
        if (status === "unverified") return "持仓已变化，结果待核实"
        return "持仓中 · 发布时浮动 " + String(position.floatingUsd === undefined ? "—" : position.floatingUsd) + " USD"
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
                    Text { text: "行情日志"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { text: "记录市场判断和持仓过程，平仓后自动补上最终结果。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 14 }
                }
                UiButton { ui: root.ui; text: "刷新"; variant: "secondary"; onClicked: root.request("journalRefresh", {}) }
                UiButton {
                    ui: root.ui; text: root.composing ? "收起编辑" : "写一条日志"; variant: "primary"
                    enabled: root.value("canPublish", false)
                    onClicked: root.composing = !root.composing
                }
            }
            Text { text: root.value("accountLabel", "账户尚未连接") + " · 数据仅保存在本地"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
            Rectangle {
                visible: !!root.value("notice", "")
                Layout.fillWidth: true
                implicitHeight: noticeText.implicitHeight + 22
                radius: 8; color: root.ui.accentSoft
                Text {
                    id: noticeText
                    anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 13; anchors.rightMargin: 13
                    text: root.value("notice", ""); color: root.ui.accent
                    font.family: root.ui.fontFamily; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
            }

            UiCard {
                ui: root.ui
                visible: root.composing
                Layout.fillWidth: true
                padding: 22
                spacing: 14
                SectionHeading { ui: root.ui; title: "写一条行情日志"; subtitle: "仅保存到此设备，并关联当前账户。"; Layout.fillWidth: true }
                TextArea {
                    id: bodyEditor
                    objectName: "journalBodyEditor"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 120
                    text: root.draftBody
                    placeholderText: "写下此刻的行情观察、开仓依据或复盘想法…"
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    color: root.ui.text; placeholderTextColor: root.ui.muted
                    font.family: root.ui.fontFamily; font.pixelSize: 14
                    leftPadding: 13; rightPadding: 13; topPadding: 11; bottomPadding: 11
                    onTextChanged: root.draftBody = text
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier)
                                && root.bridge && root.bridge.hasJournalImageOnClipboard()) {
                            root.request("journalPasteImage", {})
                            event.accepted = true
                        }
                    }
                    background: Rectangle { color: root.ui.surfaceAlt; radius: 9; border.color: bodyEditor.activeFocus ? root.ui.accent : root.ui.border }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "最多 2,100 字"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                    Item { Layout.fillWidth: true }
                    Text { text: String(root.draftBody.length) + " / 2100"; color: root.draftBody.length > 2100 ? root.ui.negative : root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "附带图片"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Text { text: String(root.value("draftImages", []).length) + " / 4"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                    UiButton { ui: root.ui; text: "粘贴图片"; variant: "secondary"; onClicked: root.request("journalPasteImage", {}) }
                    UiButton { ui: root.ui; text: "选择图片"; variant: "secondary"; onClicked: root.request("journalChooseImages", {}) }
                }
                Text { text: "可在编辑框按 Ctrl+V 粘贴截图；也支持 PNG、JPG、WebP、GIF，每张不超过 8 MiB。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                Flow {
                    Layout.fillWidth: true
                    width: parent.width
                    spacing: 8
                    visible: root.value("draftImages", []).length > 0
                    Repeater {
                        model: root.value("draftImages", [])
                        delegate: Rectangle {
                            required property var modelData
                            width: 138; height: 102; radius: 8
                            color: root.ui.surfaceAlt; border.color: root.ui.border
                            clip: true
                            Image { anchors.fill: parent; anchors.margins: 3; source: modelData.url || ""; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 24; color: root.ui.surface; opacity: 0.9 }
                            Text { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 6; text: String(modelData.name || "图片"); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 11; elide: Text.ElideMiddle }
                            Rectangle {
                                anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 5
                                width: 23; height: 23; radius: 11
                                color: root.ui.surface; border.color: root.ui.border
                                Text { anchors.centerIn: parent; text: "×"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 16 }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.request("journalRemoveImage", {"path": String(modelData.path)}) }
                            }
                        }
                    }
                }
                Text { text: "关联当前持仓（可多选）"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                Text { text: "最多关联 20 笔；平仓后显示最终盈亏。不关联也可以发布。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                Text { visible: !root.value("positions", []).length; text: "当前没有可关联的持仓"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                Repeater {
                    model: root.value("positions", [])
                    delegate: CheckBox {
                        required property var modelData
                        Layout.fillWidth: true
                        text: "#" + String(modelData.ticket || modelData.positionId) + "  ·  " + String(modelData.side || "—") + " " + String(modelData.symbol || "—") + "  ·  " + String(modelData.volume === null || modelData.volume === undefined ? "—" : modelData.volume) + " lot  ·  浮动 " + String(modelData.floatingUsd === null || modelData.floatingUsd === undefined ? "—" : modelData.floatingUsd) + " USD"
                        checked: root.selectedPositionIds.indexOf(Number(modelData.positionId)) >= 0
                        onClicked: root.togglePosition(modelData.positionId, checked)
                        font.family: root.ui.fontFamily; font.pixelSize: 13
                        palette.text: root.ui.text
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    UiButton { ui: root.ui; text: "取消"; variant: "secondary"; onClicked: root.composing = false }
                    UiButton {
                        ui: root.ui; text: "发布到本地"; variant: "primary"
                        enabled: root.value("canPublish", false) && root.draftBody.trim().length > 0 && root.draftBody.trim().length <= 2100
                        onClicked: root.request("journalPublish", {"body": root.draftBody.trim(), "positionIds": root.selectedPositionIds})
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: root.width >= 900 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 12
                MetricCard { objectName: "journalFirstMetricCard"; ui: root.ui; Layout.fillWidth: true; title: "累计日志"; value: String(root.value("total", 0)); note: "当前账户的全部记录" }
                MetricCard { ui: root.ui; Layout.fillWidth: true; title: "过去 30 天"; value: String(root.value("recent30", 0)); note: "最近的市场观察" }
                MetricCard { objectName: "journalLastMetricCard"; ui: root.ui; Layout.fillWidth: true; title: "活跃天数"; value: String(root.value("activeDays", 0)); note: "过去 365 天" }
            }

            UiCard {
                objectName: "journalHeatmapCard"
                ui: root.ui
                Layout.fillWidth: true
                padding: 22
                spacing: 18
                RowLayout {
                    objectName: "journalHeatmapHeader"
                    Layout.fillWidth: true
                    Layout.preferredWidth: parent.width
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text { objectName: "journalHeatmapTitle"; text: "记录轨迹"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                        Text { text: "每个方块代表一天；悬停可查看当日记录数。"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                    }
                    RowLayout {
                        Layout.alignment: Qt.AlignRight
                        spacing: 12
                        Text { text: String(root.value("yearTotal", 0)) + " 篇"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        Text { text: "年份"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        ComboBox {
                            id: yearSelector
                            objectName: "journalYearSelector"
                            Layout.preferredWidth: 112
                            model: root.value("years", [new Date().getFullYear()])
                            currentIndex: Math.max(0, root.value("years", [new Date().getFullYear()]).indexOf(Number(root.value("year", new Date().getFullYear()))))
                            displayText: String(root.value("year", new Date().getFullYear())) + " 年"
                            onActivated: root.request("journalYear", {"year": Number(model[currentIndex])})
                            font.family: root.ui.fontFamily; font.pixelSize: 13
                        }
                    }
                }
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: heatmapContent.implicitHeight
                    ColumnLayout {
                        id: heatmapContent
                        width: root.calendarGridWidth + 20
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 12
                    Item {
                        objectName: "journalHeatmapMonths"
                        Layout.leftMargin: 20
                        Layout.preferredWidth: root.calendarGridWidth
                        Layout.preferredHeight: 16
                        Repeater {
                            model: 12
                            delegate: Text {
                                required property int index
                                x: root.monthWeekIndex(index) * (root.cellSize() + 3)
                                text: String(index + 1) + "月"
                                color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 11
                            }
                        }
                    }
                    RowLayout {
                        Layout.preferredWidth: root.calendarGridWidth + 20
                        spacing: 8
                        Column {
                            spacing: 3
                            Text { text: "一"; height: root.cellSize(); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 10 }
                            Text { text: ""; height: root.cellSize() }
                            Text { text: "三"; height: root.cellSize(); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 10 }
                            Text { text: ""; height: root.cellSize() }
                            Text { text: "五"; height: root.cellSize(); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 10 }
                        }
                        Row {
                            id: heatmapRow
                            objectName: "journalHeatmapGrid"
                            Layout.preferredWidth: root.calendarGridWidth
                            spacing: 3
                            Repeater {
                                model: root.calendarWeeks
                                delegate: Column {
                                    required property int index
                                    property int week: index
                                    spacing: 3
                                    Repeater {
                                        model: 7
                                        delegate: Rectangle {
                                            required property int index
                                            property string key: root.dayKey(parent.week, index)
                                            property int count: root.dayCount(key)
                                            width: root.cellSize(); height: width; radius: 2
                                            color: key === "" ? "transparent" : count > 0 ? root.ui.accent : root.ui.surfaceAlt
                                            opacity: count === 0 ? 1 : count === 1 ? 0.48 : count <= 3 ? 0.66 : count <= 6 ? 0.82 : 1
                                            ToolTip.visible: hover.containsMouse && key !== ""
                                            ToolTip.text: key + " · " + count + " 篇记录"
                                            HoverHandler { id: hover }
                                        }
                                    }
                                }
                            }
                        }
                    }
                        RowLayout {
                            Layout.leftMargin: 20
                            Layout.preferredWidth: root.calendarGridWidth
                            Item { Layout.fillWidth: true }
                            Text { text: "少"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 11 }
                            Repeater { model: [0, 0.48, 0.66, 0.82, 1]
                                delegate: Rectangle { required property var modelData; width: 11; height: 11; radius: 2; color: index === 0 ? root.ui.surfaceAlt : root.ui.accent; opacity: index === 0 ? 1 : modelData } }
                            Text { text: "多"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 11 }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Text { text: "最新记录"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 17; font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
                Text { text: "共 " + String(root.value("total", 0)) + " 篇 · 每页 10 篇"; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
            }
            UiCard {
                ui: root.ui
                visible: !root.value("posts", []).length
                Layout.fillWidth: true
                padding: 34
                Text { Layout.fillWidth: true; text: root.value("total", 0) === 0 ? "还没有行情日志" : "这一页没有记录"; horizontalAlignment: Text.AlignHCenter; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold }
                Text { Layout.fillWidth: true; text: "写下第一条行情观察，或等待本地记录加载。"; horizontalAlignment: Text.AlignHCenter; color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
            }
            Repeater {
                model: root.value("posts", [])
                delegate: UiCard {
                    required property var modelData
                    ui: root.ui
                    Layout.fillWidth: true
                    padding: 22
                    spacing: 13
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "账户 " + String(modelData.accountLogin || "—"); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                        Text { text: String(modelData.createdAt || "—"); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                        Item { Layout.fillWidth: true }
                        UiButton { ui: root.ui; text: "删除"; variant: "ghost"; onClicked: root.request("journalDelete", {"postId": Number(modelData.id)}) }
                    }
                    Text { Layout.fillWidth: true; text: String(modelData.body || ""); color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 14; wrapMode: Text.WordWrap }
                    Flow {
                        Layout.fillWidth: true
                        width: parent.width
                        spacing: 8
                        visible: !!modelData.images && modelData.images.length > 0
                        Repeater {
                            model: modelData.images || []
                            delegate: Rectangle {
                                required property var modelData
                                width: 160; height: 112; radius: 8; color: root.ui.surfaceAlt; clip: true
                                Image { anchors.fill: parent; source: String(modelData); fillMode: Image.PreserveAspectCrop; asynchronous: true }
                            }
                        }
                    }
                    Text { visible: !!modelData.positions && modelData.positions.length > 0; text: "关联持仓 · " + (modelData.positions ? modelData.positions.length : 0); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                    Repeater {
                        model: modelData.positions || []
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            implicitHeight: 51; radius: 8; color: root.ui.surfaceAlt
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 13; anchors.rightMargin: 13
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 3
                                    Text { text: "#" + String(modelData.ticket || "—") + " · " + String(modelData.side || "—") + " " + String(modelData.symbol || "—") + " · " + String(modelData.volume || "—") + " lot"; color: root.ui.text; font.family: root.ui.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold }
                                    Text { text: String(modelData.accountLabel || ""); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 11 }
                                }
                                Text { text: root.positionResult(modelData); color: modelData.status === "closed" && Number(modelData.resultUsd) < 0 ? root.ui.negative : root.ui.positive; font.family: root.ui.fontFamily; font.pixelSize: 12 }
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                UiButton { ui: root.ui; text: "上一页"; variant: "secondary"; enabled: Number(root.value("page", 1)) > 1; onClicked: root.request("journalPage", {"page": Number(root.value("page", 1)) - 1}) }
                Text { text: String(root.value("page", 1)) + " / " + String(root.value("totalPages", 1)); color: root.ui.muted; font.family: root.ui.fontFamily; font.pixelSize: 13 }
                UiButton { ui: root.ui; text: "下一页"; variant: "secondary"; enabled: Number(root.value("page", 1)) < Number(root.value("totalPages", 1)); onClicked: root.request("journalPage", {"page": Number(root.value("page", 1)) + 1}) }
            }
            Item { Layout.preferredHeight: 20 }
        }
    }

    function cellSize() {
        return Math.max(8, Math.min(24, Math.floor((root.width - 125) / root.calendarWeeks) - 3))
    }
}
