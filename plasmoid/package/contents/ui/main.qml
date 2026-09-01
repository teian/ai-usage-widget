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
    property string lastUpdatedAt: ""
    property int refreshNonce: 0
    property string activeSource: ""
    readonly property bool anyProviderEnabled: plasmoid.configuration.enableCodex || plasmoid.configuration.enableClaude
    readonly property string pendingProviderId: plasmoid.configuration.enableClaude && !plasmoid.configuration.enableCodex
                                                ? "claude" : "codex"
    readonly property var gaugeLimitPreferences: ({
        codex: plasmoid.configuration.codexGaugeLimit,
        claude: plasmoid.configuration.claudeGaugeLimit
    })

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
        if (activeSource) {
            executable.disconnectSource(activeSource)
            activeSource = ""
        }
        if (!anyProviderEnabled) {
            providers = []
            selectedIndex = 0
            refreshing = false
            errorText = i18n("Enable Codex or Claude Code in the widget settings.")
            return
        }
        refreshing = true
        errorText = ""
        refreshNonce++
        const configured = plasmoid.configuration.collectorCommand.trim()
        let command = configured.indexOf("/") === -1 ? "$HOME/.local/bin/" + configured : configured
        if (plasmoid.configuration.enableCodex) command += " --provider codex"
        if (plasmoid.configuration.enableClaude) command += " --provider claude"
        activeSource = command + " #" + refreshNonce
        executable.connectSource(activeSource)
    }

    function consumeOutput(source, data) {
        executable.disconnectSource(source)
        if (source !== activeSource) return
        activeSource = ""
        refreshing = false
        if (Number(data["exit code"]) !== 0) {
            errorText = data.stderr || i18n("Collector exited with an error.")
            return
        }
        try {
            const result = JSON.parse(data.stdout)
            providers = result.providers || [result]
            lastUpdatedAt = result.updatedAt || (providers.length > 0 ? providers[0].updatedAt || "" : "")
            if (selectedIndex >= providers.length) selectedIndex = 0
        } catch (error) {
            errorText = i18n("The collector returned invalid data: %1", error.toString())
        }
    }

    Plasmoid.icon: "utilities-terminal"
    Plasmoid.status: record || errorText ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus
    toolTipMainText: root.providers.length === 0 ? i18n("AI Usage") : ""
    toolTipSubText: root.providers.length === 0
        ? (record ? i18n("%1 tokens today", compactNumber(record.localActivity.daily[record.localActivity.daily.length - 1].tokens)) : errorText)
        : ""

    compactRepresentation: Item {
        implicitWidth: row.implicitWidth + Kirigami.Units.smallSpacing * 2
        implicitHeight: Math.max(Kirigami.Units.gridUnit, row.implicitHeight)
        Layout.minimumWidth: implicitWidth
        Layout.preferredWidth: implicitWidth
        RowLayout {
            id: row
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing
            Item {
                visible: root.providers.length === 0 && root.anyProviderEnabled
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium

                BrandIcon {
                    anchors.centerIn: parent
                    providerId: root.pendingProviderId
                    iconSize: Kirigami.Units.iconSizes.smallMedium
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        root.expanded = true
                        if (!root.refreshing) root.refresh()
                    }
                }
            }
            Kirigami.Icon {
                visible: !root.anyProviderEnabled
                source: "configure"
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            }
            Repeater {
                model: root.providers
                delegate: ProviderGauge {
                    required property var modelData
                    required property int index
                    provider: modelData
                    limitPreference: root.gaugeLimitPreferences[modelData.provider.id] || 0
                    selected: index === root.selectedIndex
                    popupOpen: root.expanded
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
        lastUpdatedAt: root.lastUpdatedAt
        gaugeLimitPreferences: root.gaugeLimitPreferences
        onRefreshRequested: root.refresh()
        onProviderRequested: (index) => root.selectedIndex = index
    }

    Plasma5Support.DataSource {
        id: executable
        engine: "executable"
        onNewData: (source, data) => root.consumeOutput(source, data)
    }

    Timer {
        id: configRefreshTimer
        interval: 150
        repeat: false
        onTriggered: root.refresh()
    }

    Timer {
        interval: Math.max(1, plasmoid.configuration.refreshMinutes) * 60 * 1000
        repeat: true
        running: true
        onTriggered: root.refresh()
    }

    Connections {
        target: plasmoid.configuration
        function onEnableCodexChanged() { configRefreshTimer.restart() }
        function onEnableClaudeChanged() { configRefreshTimer.restart() }
    }

    Component.onCompleted: refresh()
}
