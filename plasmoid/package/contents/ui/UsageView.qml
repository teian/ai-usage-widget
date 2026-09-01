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
    signal refreshRequested()
    signal providerRequested(int index)

    implicitWidth: Kirigami.Units.gridUnit * 22
    implicitHeight: Kirigami.Units.gridUnit * 30

    function compactNumber(value) {
        const number = Number(value || 0)
        if (number >= 1000000) return (number / 1000000).toFixed(number >= 10000000 ? 0 : 1) + "M"
        if (number >= 1000) return (number / 1000).toFixed(number >= 10000 ? 0 : 1) + "K"
        return number.toLocaleString(Qt.locale())
    }

    function resetLabel(value) {
        if (!value) return ""
        const seconds = Math.max(0, (new Date(value).getTime() - Date.now()) / 1000)
        if (seconds < 60) return i18n("Resets soon")
        if (seconds < 3600) return i18np("Resets in %1 minute", "Resets in %1 minutes", Math.ceil(seconds / 60))
        if (seconds < 86400) return i18np("Resets in %1 hour", "Resets in %1 hours", Math.ceil(seconds / 3600))
        return i18np("Resets in %1 day", "Resets in %1 days", Math.ceil(seconds / 86400))
    }

    contentItem: PlasmaComponents.ScrollView {
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: Kirigami.Units.largeSpacing

            RowLayout {
                Layout.fillWidth: true
                Kirigami.Icon {
                    source: view.record ? view.record.provider.icon : "utilities-terminal"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                }
                ColumnLayout {
                    spacing: 0
                    PlasmaExtras.Heading { text: view.record ? view.record.provider.name : i18n("AI Usage"); level: 2 }
                    PlasmaComponents.Label {
                        text: view.record && view.record.account.plan ? String(view.record.account.plan).toUpperCase() : i18n("Local usage")
                        opacity: 0.7
                    }
                }
                Item { Layout.fillWidth: true }
                PlasmaComponents.ToolButton {
                    icon.name: "view-refresh"
                    enabled: !view.refreshing
                    onClicked: view.refreshRequested()
                    Accessible.name: i18n("Refresh")
                }
            }

            RowLayout {
                visible: view.providers.length > 1
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: view.providers
                    delegate: PlasmaComponents.Button {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        text: modelData.provider.name
                        icon.name: modelData.provider.icon
                        checked: index === view.selectedIndex
                        checkable: true
                        onClicked: view.providerRequested(index)
                    }
                }
            }

            PlasmaComponents.Label {
                visible: view.errorText.length > 0
                Layout.fillWidth: true
                text: view.errorText
                color: Kirigami.Theme.negativeTextColor
                wrapMode: Text.Wrap
            }

            PlasmaComponents.Label {
                visible: view.record && view.record.account.status !== "ok" && view.record.account.message
                Layout.fillWidth: true
                text: view.record ? view.record.account.message : ""
                color: Kirigami.Theme.neutralTextColor
                wrapMode: Text.Wrap
            }

            ColumnLayout {
                visible: view.record && view.record.account.limits.length > 0
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                PlasmaExtras.Heading { text: i18n("Limits"); level: 3 }
                Repeater {
                    model: view.record ? view.record.account.limits : []
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        RowLayout {
                            Layout.fillWidth: true
                            PlasmaComponents.Label { text: modelData.label }
                            Item { Layout.fillWidth: true }
                            PlasmaComponents.Label { text: Math.round(modelData.usedPercent) + "%"; font.weight: Font.DemiBold }
                        }
                        PlasmaComponents.ProgressBar {
                            Layout.fillWidth: true
                            from: 0; to: 100; value: modelData.usedPercent
                        }
                        PlasmaComponents.Label { text: view.resetLabel(modelData.resetsAt); opacity: 0.65; font.pixelSize: Kirigami.Theme.smallFont.pixelSize }
                    }
                }
            }

            GridLayout {
                visible: !!view.record
                Layout.fillWidth: true
                columns: 3
                columnSpacing: Kirigami.Units.largeSpacing
                Repeater {
                    model: view.record ? [
                        { label: i18n("Today"), value: view.compactNumber(view.record.localActivity.daily[view.record.localActivity.daily.length - 1].tokens) },
                        { label: i18n("Prompts"), value: view.compactNumber(view.record.localActivity.totals.prompts) },
                        { label: i18n("Sessions"), value: view.compactNumber(view.record.localActivity.totals.sessions) }
                    ] : []
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        PlasmaExtras.Heading { Layout.alignment: Qt.AlignHCenter; text: modelData.value; level: 2 }
                        PlasmaComponents.Label { Layout.alignment: Qt.AlignHCenter; text: modelData.label; opacity: 0.65 }
                    }
                }
            }

            ColumnLayout {
                visible: !!view.record
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                PlasmaExtras.Heading { text: i18n("Last 7 days"); level: 3 }
                Repeater {
                    model: view.record ? view.record.localActivity.daily : []
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        PlasmaComponents.Label { text: Qt.formatDate(new Date(modelData.date + "T12:00:00"), "ddd"); Layout.preferredWidth: Kirigami.Units.gridUnit * 2 }
                        PlasmaComponents.ProgressBar {
                            Layout.fillWidth: true
                            from: 0
                            to: Math.max(1, ...view.record.localActivity.daily.map(day => day.tokens))
                            value: modelData.tokens
                        }
                        PlasmaComponents.Label { text: view.compactNumber(modelData.tokens); Layout.preferredWidth: Kirigami.Units.gridUnit * 3; horizontalAlignment: Text.AlignRight }
                    }
                }
            }

            ColumnLayout {
                visible: view.record && view.record.localActivity.models.length > 0
                Layout.fillWidth: true
                PlasmaExtras.Heading { text: i18n("By model"); level: 3 }
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

            PlasmaComponents.Label {
                visible: !!view.record
                Layout.fillWidth: true
                text: view.record ? i18n("Input %1 · cache read %2 · cache write %3 · output %4",
                    view.compactNumber(view.record.localActivity.totals.inputTokens),
                    view.compactNumber(view.record.localActivity.totals.cachedInputTokens),
                    view.compactNumber(view.record.localActivity.totals.cacheWriteInputTokens),
                    view.compactNumber(view.record.localActivity.totals.outputTokens)) : ""
                opacity: 0.65
                wrapMode: Text.Wrap
            }
        }
    }
}
