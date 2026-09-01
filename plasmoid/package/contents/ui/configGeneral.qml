import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    property alias cfg_collectorCommand: collector.text
    property alias cfg_refreshMinutes: refresh.value

    Controls.TextField {
        id: collector
        Kirigami.FormData.label: i18n("Collector command:")
    }

    Controls.SpinBox {
        id: refresh
        Kirigami.FormData.label: i18n("Refresh interval:")
        from: 1
        to: 120
        editable: true
        textFromValue: (value) => i18np("%1 minute", "%1 minutes", value)
        valueFromText: (text) => parseInt(text)
    }
}
