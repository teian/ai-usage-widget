import QtQuick
import org.kde.kirigami as Kirigami

Rectangle {
    id: icon
    required property string providerId
    property int iconSize: Kirigami.Units.iconSizes.medium

    implicitWidth: iconSize
    implicitHeight: iconSize
    radius: width / 2
    color: providerId === "claude" ? "#D97757" : "#10A37F"

    Image {
        anchors.centerIn: parent
        width: parent.width * 0.58
        height: parent.height * 0.58
        source: Qt.resolvedUrl("../assets/" + icon.providerId + ".svg")
        fillMode: Image.PreserveAspectFit
        smooth: true
    }
}
