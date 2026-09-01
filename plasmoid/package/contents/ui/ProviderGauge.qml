import QtQuick
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import "ProviderTheme.js" as ProviderTheme
import "ProviderLimits.js" as ProviderLimits

Item {
    id: gauge

    required property var provider
    property bool selected: false
    property bool showLabel: true
    property bool popupOpen: false
    property int gaugeSize: Kirigami.Units.iconSizes.medium
    // 0: first available, 1: short window, 2: weekly
    property int limitPreference: 0
    readonly property var primaryLimit: selectedLimit()
    readonly property real percentage: primaryLimit ? Number(primaryLimit.usedPercent || 0) : -1
    readonly property color accentColor: ProviderTheme.accentColor(provider ? provider.provider.id : "")
    readonly property color ringColor: percentage >= 90 ? Kirigami.Theme.negativeTextColor
        : percentage >= 75 ? Kirigami.Theme.neutralTextColor
        : accentColor
    signal activated()

    implicitWidth: gaugeSize
    implicitHeight: gaugeSize

    function faded(color, alpha) {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    function selectedLimit() {
        return ProviderLimits.selectedLimit(provider, limitPreference)
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
                context.strokeStyle = gauge.ringColor
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
            function onRingColorChanged() { ring.requestPaint() }
            function onSelectedChanged() { ring.requestPaint() }
        }
    }

    PlasmaComponents.Label {
        visible: gauge.showLabel
        anchors.centerIn: parent
        text: gauge.percentage >= 0 ? Math.round(gauge.percentage) + "%" : "—"
        font.pixelSize: Math.max(9, gauge.gaugeSize * 0.36)
        font.weight: Font.DemiBold
        color: gauge.percentage >= 75 ? gauge.ringColor : Kirigami.Theme.textColor
    }

    BrandIcon {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: -2
        anchors.bottomMargin: -2
        providerId: gauge.provider.provider.id
        iconSize: 14
        border.width: 1
        border.color: Kirigami.Theme.backgroundColor
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: gauge.activated()

        PlasmaComponents.ToolTip.visible: containsMouse && !gauge.popupOpen
        PlasmaComponents.ToolTip.text: gauge.primaryLimit
            ? i18n("%1 · %2% used", gauge.provider.provider.name, Math.round(gauge.percentage))
            : i18n("%1: limits unavailable", gauge.provider.provider.name)
    }
}
