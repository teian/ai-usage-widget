import QtQuick
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents

Item {
    id: gauge

    required property var provider
    property bool selected: false
    property int gaugeSize: Math.max(Kirigami.Units.iconSizes.smallMedium, Kirigami.Units.gridUnit + 4)
    readonly property var primaryLimit: provider && provider.account.limits.length > 0 ? provider.account.limits[0] : null
    readonly property real percentage: primaryLimit ? Number(primaryLimit.usedPercent || 0) : -1
    readonly property color accentColor: provider && provider.provider.id === "claude" ? "#D97757" : "#10A37F"
    signal activated()

    implicitWidth: gaugeSize + Kirigami.Units.smallSpacing
    implicitHeight: gaugeSize

    function faded(color, alpha) {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    Canvas {
        id: ring
        anchors.centerIn: parent
        width: gauge.gaugeSize
        height: gauge.gaugeSize

        onPaint: {
            const context = getContext("2d")
            context.reset()
            context.lineWidth = Math.max(2, gauge.gaugeSize * 0.08)
            context.lineCap = "round"
            const center = width / 2
            const radius = Math.max(1, center - context.lineWidth)
            context.beginPath()
            context.strokeStyle = gauge.faded(Kirigami.Theme.textColor, gauge.selected ? 0.24 : 0.14)
            context.arc(center, center, radius, 0, Math.PI * 2)
            context.stroke()
            if (gauge.percentage >= 0) {
                context.beginPath()
                context.strokeStyle = gauge.accentColor
                context.arc(
                    center,
                    center,
                    radius,
                    -Math.PI / 2,
                    -Math.PI / 2 + Math.PI * 2 * Math.min(100, Math.max(0, gauge.percentage)) / 100
                )
                context.stroke()
            }
        }

        Connections {
            target: gauge
            function onPercentageChanged() { ring.requestPaint() }
            function onAccentColorChanged() { ring.requestPaint() }
            function onSelectedChanged() { ring.requestPaint() }
        }
    }

    PlasmaComponents.Label {
        anchors.centerIn: parent
        text: gauge.percentage >= 0 ? Math.round(gauge.percentage) + "%" : "—"
        font.pixelSize: Math.max(8, gauge.gaugeSize * 0.28)
        font.weight: Font.DemiBold
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: gauge.activated()
    }

    PlasmaComponents.ToolTip {
        visible: mouse.containsMouse
        text: gauge.primaryLimit
            ? i18n("%1: %2% used · %3", gauge.provider.provider.name, Math.round(gauge.percentage), gauge.primaryLimit.label)
            : i18n("%1: limits unavailable", gauge.provider.provider.name)
    }
}
