import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: view

    required property var record
    required property var providers
    required property int selectedIndex
    required property string errorText
    required property bool refreshing
    property bool historyExpanded: false
    signal refreshRequested()
    signal providerRequested(int index)

    implicitWidth: Kirigami.Units.gridUnit * 23
    implicitHeight: Kirigami.Units.gridUnit * 32

    readonly property color accentColor: record && record.provider.id === "claude" ? "#D97757" : "#10A37F"
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
                        text: view.record && view.record.account.plan ? i18n("%1 plan", view.record.account.plan) : i18n("Local activity")
                        color: Kirigami.Theme.disabledTextColor
                    }
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.ToolButton {
                    icon.name: "view-refresh"
                    enabled: !view.refreshing
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
                        delegate: PlasmaComponents.Button {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            text: modelData.provider.name
                            checked: index === view.selectedIndex
                            checkable: true
                            onClicked: view.providerRequested(index)
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

            Rectangle {
                visible: !!view.record
                Layout.fillWidth: true
                implicitHeight: metrics.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.cornerRadius
                color: Kirigami.Theme.alternateBackgroundColor
                RowLayout {
                    id: metrics
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    Repeater {
                        model: view.record ? [
                            { label: i18n("Tokens today"), value: view.compactNumber(view.today.tokens) },
                            { label: i18n("Prompts"), value: view.compactNumber(view.record.localActivity.totals.prompts) },
                            { label: i18n("Sessions"), value: view.compactNumber(view.record.localActivity.totals.sessions) }
                        ] : []
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 0
                            PlasmaExtras.Heading { Layout.alignment: Qt.AlignHCenter; text: modelData.value; level: 2 }
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

                Rectangle {
                visible: !!view.record
                Layout.fillWidth: true
                implicitHeight: tokenDetails.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.cornerRadius
                color: Kirigami.Theme.alternateBackgroundColor
                GridLayout {
                    id: tokenDetails
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    columns: 2
                    columnSpacing: Kirigami.Units.largeSpacing
                    rowSpacing: Kirigami.Units.smallSpacing
                    Repeater {
                        model: view.record ? [
                            { label: i18n("Input"), value: view.record.localActivity.totals.inputTokens },
                            { label: i18n("Cache read"), value: view.record.localActivity.totals.cachedInputTokens },
                            { label: i18n("Cache write"), value: view.record.localActivity.totals.cacheWriteInputTokens },
                            { label: i18n("Output"), value: view.record.localActivity.totals.outputTokens }
                        ] : []
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            PlasmaComponents.Label { text: modelData.label; color: Kirigami.Theme.disabledTextColor }
                            Item { Layout.fillWidth: true }
                            PlasmaComponents.Label { text: view.compactNumber(modelData.value); font.weight: Font.DemiBold }
                        }
                    }
                }
                }
            }
        }
    }
}
