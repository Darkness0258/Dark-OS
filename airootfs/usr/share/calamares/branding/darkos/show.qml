/* DarkOS slideshow for Calamares — API 2 */
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: slideContainer
    width: 800
    height: 450

    function onActivate() {}
    function onLeave() {}

    Rectangle {
        anchors.fill: parent
        color: "#000000"

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 16

            Text {
                Layout.alignment: Qt.AlignCenter
                text: "DarkOS"
                font.pixelSize: 48
                font.family: "Space Grotesk, sans-serif"
                font.weight: Font.Bold
                color: "#00e5ff"
                style: Text.Raised
                styleColor: "#000000"
            }

            Text {
                Layout.alignment: Qt.AlignCenter
                text: "Control Everything"
                font.pixelSize: 20
                font.family: "Inter, sans-serif"
                color: "#9aa4ad"
            }

            Text {
                Layout.alignment: Qt.AlignCenter
                text: "Arch + BlackArch + Hyprland"
                font.pixelSize: 13
                font.family: "Inter, sans-serif"
                color: "#9aa4ad"
            }
        }
    }
}
