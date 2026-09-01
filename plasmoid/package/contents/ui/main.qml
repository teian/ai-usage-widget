import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    property var record: null
    property string errorText: ""
    property bool refreshing: false
    property int refreshNonce: 0

    function compactNumber(value) {
        const number = Number(value || 0)
        if (number >= 1000000) return (number / 1000000).toFixed(number >= 10000000 ? 0 : 1) + "M"
        if (number >= 1000) return (number / 1000).toFixed(number >= 10000 ? 0 : 1) + "K"
        return number.toLocaleString(Qt.locale())
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
        executable.connectSource(plasmoid.configuration.collectorCommand + " #" + refreshNonce)
    }

    function consumeOutput(source, data) {
        refreshing = false
        executable.disconnectSource(source)
        if (Number(data["exit code"]) !== 0) {
            errorText = data.stderr || i18n("Collector exited with an error.")
            return
        }
        try {
            record = JSON.parse(data.stdout)
        } catch (error) {
            errorText = i18n("The collector returned invalid data: %1", error.toString())
        }
    }

    Plasmoid.icon: "utilities-terminal"
    Plasmoid.status: record || errorText ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus
    toolTipMainText: i18n("AI Usage")
    toolTipSubText: record ? i18n("%1 tokens today", compactNumber(record.localActivity.daily[record.localActivity.daily.length - 1].tokens)) : errorText

    compactRepresentation: MouseArea {
        implicitWidth: row.implicitWidth + Kirigami.Units.smallSpacing * 2
        implicitHeight: Kirigami.Units.gridUnit
        onClicked: root.expanded = !root.expanded

        RowLayout {
            id: row
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "utilities-terminal"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
            PlasmaComponents.Label {
                visible: !!root.record
                text: root.record ? root.compactNumber(root.record.localActivity.daily[root.record.localActivity.daily.length - 1].tokens) : ""
                font.weight: Font.DemiBold
            }
        }
    }

    fullRepresentation: UsageView {
        record: root.record
        errorText: root.errorText
        refreshing: root.refreshing
        onRefreshRequested: root.refresh()
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
