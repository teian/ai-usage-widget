import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    property var providers: []
    property int selectedIndex: 0
    readonly property var record: providers.length > 0 ? providers[Math.min(selectedIndex, providers.length - 1)] : null
    property string errorText: ""
    property bool refreshing: false
    property int refreshNonce: 0

    function compactNumber(value) {
        const number = Number(value || 0)
        if (number >= 1000000) return (number / 1000000).toFixed(number >= 10000000 ? 0 : 1).replace(".0", "") + "M"
        if (number >= 1000) return (number / 1000).toFixed(number >= 10000 ? 0 : 1).replace(".0", "") + "K"
        return Math.round(number).toLocaleString(Qt.locale(), "f", 0)
    }

    function resetLabel(value) {
        if (!value) return ""
        const seconds = Math.max(0, (new Date(value).getTime() - Date.now()) / 1000)
        if (seconds < 60) return i18n("resets soon")
        if (seconds < 3600) return i18np("resets in %1 minute", "resets in %1 minutes", Math.ceil(seconds / 60))
        if (seconds < 86400) return i18np("resets in %1 hour", "resets in %1 hours", Math.ceil(seconds / 3600))
        return i18np("resets in %1 day", "resets in %1 days", Math.ceil(seconds / 86400))
    }

    function refresh() {
        refreshing = true
        errorText = ""
        refreshNonce++
        const configured = plasmoid.configuration.collectorCommand.trim()
        const command = configured.indexOf("/") === -1 ? "$HOME/.local/bin/" + configured : configured
        executable.connectSource(command + " #" + refreshNonce)
    }

    function consumeOutput(source, data) {
        refreshing = false
        executable.disconnectSource(source)
        if (Number(data["exit code"]) !== 0) {
            errorText = data.stderr || i18n("Collector exited with an error.")
            return
        }
        try {
            const result = JSON.parse(data.stdout)
            providers = result.providers || [result]
            if (selectedIndex >= providers.length) selectedIndex = 0
        } catch (error) {
            errorText = i18n("The collector returned invalid data: %1", error.toString())
        }
    }

    Plasmoid.icon: "utilities-terminal"
    Plasmoid.status: record || errorText ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus
    toolTipMainText: i18n("AI Usage")
    toolTipSubText: record ? i18n("%1 tokens today", compactNumber(record.localActivity.daily[record.localActivity.daily.length - 1].tokens)) : errorText

    compactRepresentation: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: Math.max(Kirigami.Units.gridUnit, row.implicitHeight)
        RowLayout {
            id: row
            anchors.centerIn: parent
            spacing: 0
            BrandIcon {
                visible: root.providers.length === 0
                providerId: "codex"
                iconSize: Kirigami.Units.iconSizes.smallMedium
            }
            Repeater {
                model: root.providers
                delegate: ProviderGauge {
                    required property var modelData
                    required property int index
                    provider: modelData
                    selected: index === root.selectedIndex
                    onActivated: {
                        root.selectedIndex = index
                        root.expanded = true
                    }
                }
            }
        }
    }

    fullRepresentation: UsageView {
        record: root.record
        providers: root.providers
        selectedIndex: root.selectedIndex
        errorText: root.errorText
        refreshing: root.refreshing
        onRefreshRequested: root.refresh()
        onProviderRequested: (index) => root.selectedIndex = index
    }

    Plasma5Support.DataSource {
        id: executable
        engine: "executable"
        onNewData: (source, data) => root.consumeOutput(source, data)
    }

    Timer {
        interval: Math.max(1, plasmoid.configuration.refreshMinutes) * 60 * 1000
        repeat: true
        running: true
        onTriggered: root.refresh()
    }

    Component.onCompleted: refresh()
}
