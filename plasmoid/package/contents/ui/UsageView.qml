import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import "ProviderTheme.js" as ProviderTheme
import "ProviderLimits.js" as ProviderLimits

PlasmaExtras.Representation {
    id: view

    required property var record
    required property var providers
    required property int selectedIndex
    required property string errorText
    required property bool refreshing
    required property string lastUpdatedAt
    required property var gaugeLimitPreferences
    property bool historyExpanded: false
    property bool usageDetailsExpanded: false
    signal refreshRequested()
    signal providerRequested(int index)

    implicitWidth: Kirigami.Units.gridUnit * 23
    implicitHeight: Kirigami.Units.gridUnit * 32

    readonly property color accentColor: ProviderTheme.accentColor(record ? record.provider.id : "")
    readonly property var today: record && record.localActivity.daily.length
        ? record.localActivity.daily[record.localActivity.daily.length - 1] : ({ tokens: 0 })

    function compactNumber(value) {
        const number = Number(value || 0)
        if (number >= 1000000) return (number / 1000000).toFixed(number >= 10000000 ? 0 : 1).replace(".0", "") + "M"
        if (number >= 1000) return (number / 1000).toFixed(number >= 10000 ? 0 : 1).replace(".0", "") + "K"
        return Math.round(number).toLocaleString(Qt.locale(), "f", 0)
    }

    function resetLabel(value) {
        if (!value) return ""
        const seconds = Math.max(0, (new Date(value).getTime() - Date.now()) / 1000)
        if (seconds < 60) return i18n("Resets soon")
        if (seconds < 3600) return i18np("Resets in %1 minute", "Resets in %1 minutes", Math.ceil(seconds / 60))
        if (seconds < 86400) return i18np("Resets in %1 hour", "Resets in %1 hours", Math.ceil(seconds / 3600))
        return i18np("Resets in %1 day", "Resets in %1 days", Math.ceil(seconds / 86400))
    }

    function faded(color, alpha) {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    function limitColor(percent) {
        if (percent >= 90) return Kirigami.Theme.negativeTextColor
        if (percent >= 75) return Kirigami.Theme.neutralTextColor
        return accentColor
    }

    function updatedLabel(value) {
        if (!value) return ""
        const date = new Date(value)
        if (isNaN(date.getTime())) return ""
        return i18n("Updated %1", Qt.formatTime(date, "HH:mm"))
    }

    contentItem: PlasmaComponents.ScrollView {
        id: scrollView
        contentWidth: availableWidth
        PlasmaComponents.ScrollBar.horizontal.policy: PlasmaComponents.ScrollBar.AlwaysOff

        Item {
            width: scrollView.availableWidth
            implicitHeight: contentColumn.implicitHeight + Kirigami.Units.largeSpacing * 2

            ColumnLayout {
                id: contentColumn
                x: Kirigami.Units.largeSpacing
                y: Kirigami.Units.largeSpacing
                width: Math.max(0, parent.width - Kirigami.Units.largeSpacing * 2)
                spacing: Kirigami.Units.largeSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing
                BrandIcon {
                    providerId: view.record ? view.record.provider.id : "codex"
                    iconSize: Kirigami.Units.iconSizes.large
                }
                ColumnLayout {
                    spacing: 1
                    PlasmaExtras.Heading { text: view.record ? view.record.provider.name : i18n("AI Usage"); level: 2 }
                    PlasmaComponents.Label {
                        readonly property string planText: view.record && view.record.account.plan
                            ? i18n("%1 plan", view.record.account.plan) : ""
                        readonly property string updateText: view.updatedLabel(view.lastUpdatedAt)
                        text: planText && updateText ? i18n("%1 · %2", planText, updateText)
                            : planText || updateText || i18n("Local activity")
                        color: Kirigami.Theme.disabledTextColor
                    }
                }
                Item { Layout.fillWidth: true }
                ColumnLayout {
                    visible: !!view.record
                    Layout.alignment: Qt.AlignRight
                    spacing: 0
                    PlasmaExtras.Heading {
                        Layout.alignment: Qt.AlignRight
                        text: view.compactNumber(view.today.tokens)
                        level: 2
                    }
                    PlasmaComponents.Label {
                        Layout.alignment: Qt.AlignRight
                        text: i18n("Tokens today")
                        color: Kirigami.Theme.disabledTextColor
                        font: Kirigami.Theme.smallFont
                    }
                }
                PlasmaComponents.BusyIndicator {
                    visible: view.refreshing
                    running: view.refreshing
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    Accessible.name: i18n("Refreshing usage")
                }
                PlasmaComponents.ToolButton {
                    visible: !view.refreshing
                    icon.name: "view-refresh"
                    onClicked: view.refreshRequested()
                    Accessible.name: i18n("Refresh usage")
                }
            }

            Rectangle {
                visible: view.providers.length > 1
                Layout.fillWidth: true
                implicitHeight: providerRow.implicitHeight + Kirigami.Units.smallSpacing * 2
                radius: Kirigami.Units.cornerRadius
                color: Kirigami.Theme.alternateBackgroundColor
                RowLayout {
                    id: providerRow
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.smallSpacing
                    spacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: view.providers
                        delegate: PlasmaComponents.ItemDelegate {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            highlighted: index === view.selectedIndex
                            onClicked: view.providerRequested(index)
                            contentItem: RowLayout {
                                PlasmaComponents.Label {
                                    readonly property var providerLimit: ProviderLimits.selectedLimit(
                                        modelData, view.gaugeLimitPreferences[modelData.provider.id] || 0)
                                    Layout.fillWidth: true
                                    text: providerLimit
                                        ? i18n("%1 · %2%", modelData.provider.name, Math.round(providerLimit.usedPercent))
                                        : modelData.provider.name
                                    font.weight: index === view.selectedIndex ? Font.DemiBold : Font.Normal
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                visible: view.errorText.length > 0 || (view.record && view.record.account.status !== "ok" && view.record.account.message)
                Layout.fillWidth: true
                implicitHeight: warningLabel.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.cornerRadius
                color: view.faded(Kirigami.Theme.neutralTextColor, 0.12)
                PlasmaComponents.Label {
                    id: warningLabel
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    text: view.errorText || (view.record ? view.record.account.message : "")
                    color: view.errorText ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.neutralTextColor
                    wrapMode: Text.Wrap
                }
            }

            ColumnLayout {
                visible: view.record && view.record.account.limits.length > 0
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                PlasmaExtras.Heading { text: i18n("Allowance"); level: 3 }
                Repeater {
                    model: view.record ? view.record.account.limits : []
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: limitContent.implicitHeight + Kirigami.Units.largeSpacing * 2
                        radius: Kirigami.Units.cornerRadius
                        color: Kirigami.Theme.alternateBackgroundColor
                        ColumnLayout {
                            id: limitContent
                            anchors.fill: parent
                            anchors.margins: Kirigami.Units.largeSpacing
                            spacing: Kirigami.Units.smallSpacing
                            RowLayout {
                                Layout.fillWidth: true
                                PlasmaComponents.Label { text: modelData.label; font.weight: Font.DemiBold }
                                Item { Layout.fillWidth: true }
                                PlasmaExtras.Heading {
                                    text: Math.round(modelData.usedPercent) + "%"
                                    level: 3
                                    color: view.limitColor(modelData.usedPercent)
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: 6
                                radius: height / 2
                                color: view.faded(Kirigami.Theme.textColor, 0.14)
                                Rectangle {
                                    width: parent.width * Math.min(100, Math.max(0, modelData.usedPercent)) / 100
                                    height: parent.height
                                    radius: height / 2
                                    color: view.limitColor(modelData.usedPercent)
                                }
                            }
                            PlasmaComponents.Label {
                                text: view.resetLabel(modelData.resetsAt)
                                color: Kirigami.Theme.disabledTextColor
                                font: Kirigami.Theme.smallFont
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                visible: !!view.record
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                PlasmaComponents.ToolButton {
                    text: i18n("Usage details")
                    icon.name: view.usageDetailsExpanded ? "arrow-down" : "arrow-right"
                    onClicked: view.usageDetailsExpanded = !view.usageDetailsExpanded
                    Accessible.name: view.usageDetailsExpanded
                        ? i18n("Collapse usage details") : i18n("Expand usage details")
                }
                Rectangle {
                    visible: view.usageDetailsExpanded
                    Layout.fillWidth: true
                    implicitHeight: usageDetails.implicitHeight + Kirigami.Units.largeSpacing * 2
                    radius: Kirigami.Units.cornerRadius
                    color: Kirigami.Theme.alternateBackgroundColor
                    ColumnLayout {
                        id: usageDetails
                        anchors.fill: parent
                        anchors.margins: Kirigami.Units.largeSpacing
                        spacing: Kirigami.Units.smallSpacing
                        RowLayout {
                            Layout.fillWidth: true
                            PlasmaComponents.Label {
                                Layout.fillWidth: true
                                text: i18n("%1 prompts", view.compactNumber(view.record.localActivity.totals.prompts))
                                color: Kirigami.Theme.disabledTextColor
                            }
                            PlasmaComponents.Label {
                                Layout.fillWidth: true
                                text: i18n("%1 sessions", view.compactNumber(view.record.localActivity.totals.sessions))
                                horizontalAlignment: Text.AlignRight
                                color: Kirigami.Theme.disabledTextColor
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 1
                            color: view.faded(Kirigami.Theme.textColor, 0.14)
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Repeater {
                                model: [
                                    { label: i18n("Input"), value: view.record.localActivity.totals.inputTokens },
                                    { label: i18n("Read"), value: view.record.localActivity.totals.cachedInputTokens },
                                    { label: i18n("Write"), value: view.record.localActivity.totals.cacheWriteInputTokens },
                                    { label: i18n("Output"), value: view.record.localActivity.totals.outputTokens }
                                ]
                                delegate: ColumnLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 0
                                    PlasmaComponents.Label {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: view.compactNumber(modelData.value)
                                        font.weight: Font.DemiBold
                                    }
                                    PlasmaComponents.Label {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: modelData.label
                                        color: Kirigami.Theme.disabledTextColor
                                        font: Kirigami.Theme.smallFont
                                    }
                                }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                visible: !!view.record
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                PlasmaComponents.ToolButton {
                    text: i18n("Last 7 days")
                    icon.name: view.historyExpanded ? "arrow-down" : "arrow-right"
                    onClicked: view.historyExpanded = !view.historyExpanded
                    Accessible.name: view.historyExpanded
                        ? i18n("Collapse last 7 days") : i18n("Expand last 7 days")
                }
                Repeater {
                    model: view.record && view.historyExpanded ? view.record.localActivity.daily : []
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing
                        PlasmaComponents.Label {
                            text: Qt.formatDate(new Date(modelData.date + "T12:00:00"), "ddd")
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                            color: modelData.date === view.today.date ? view.accentColor : Kirigami.Theme.textColor
                            font.weight: modelData.date === view.today.date ? Font.DemiBold : Font.Normal
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 6
                            radius: height / 2
                            color: view.faded(Kirigami.Theme.textColor, 0.13)
                            Rectangle {
                                width: parent.width * modelData.tokens / Math.max(1, ...view.record.localActivity.daily.map(day => day.tokens))
                                height: parent.height
                                radius: height / 2
                                color: view.accentColor
                                opacity: modelData.tokens > 0 ? 1 : 0
                            }
                        }
                        PlasmaComponents.Label {
                            text: view.compactNumber(modelData.tokens)
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                            horizontalAlignment: Text.AlignRight
                            color: Kirigami.Theme.disabledTextColor
                        }
                    }
                }
            }

            ColumnLayout {
                visible: view.record && view.record.localActivity.models.length > 0
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                PlasmaExtras.Heading { text: i18n("Models"); level: 3 }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: modelList.implicitHeight + Kirigami.Units.largeSpacing * 2
                    radius: Kirigami.Units.cornerRadius
                    color: Kirigami.Theme.alternateBackgroundColor
                    ColumnLayout {
                        id: modelList
                        anchors.fill: parent
                        anchors.margins: Kirigami.Units.largeSpacing
                        spacing: Kirigami.Units.smallSpacing
                        PlasmaComponents.Label {
                            text: i18n("Recent local activity")
                            color: Kirigami.Theme.disabledTextColor
                            font: Kirigami.Theme.smallFont
                        }
                        Repeater {
                            model: view.record ? view.record.localActivity.models : []
                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                PlasmaComponents.Label { Layout.fillWidth: true; text: modelData.model; elide: Text.ElideRight }
                                PlasmaComponents.Label { text: view.compactNumber(modelData.totalTokens); font.weight: Font.DemiBold }
                            }
                        }
                    }
                }
            }
        }
    }
}
}
