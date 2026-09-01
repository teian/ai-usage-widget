import QtQuick
import org.kde.kirigami as Kirigami
import "ProviderTheme.js" as ProviderTheme

Rectangle {
    id: icon
    required property string providerId
    property int iconSize: Kirigami.Units.iconSizes.medium

    implicitWidth: iconSize
    implicitHeight: iconSize
    radius: width / 2
    color: ProviderTheme.accentColor(providerId)

    Image {
        anchors.centerIn: parent
        width: parent.width * 0.58
        height: parent.height * 0.58
        source: Qt.resolvedUrl("../assets/" + icon.providerId + ".svg")
        fillMode: Image.PreserveAspectFit
        smooth: true
    }
}
