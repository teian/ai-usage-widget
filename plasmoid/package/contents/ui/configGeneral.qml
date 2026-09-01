import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    property alias cfg_collectorCommand: collector.text
    property alias cfg_refreshMinutes: refresh.value
    property alias cfg_enableCodex: enableCodex.checked
    property alias cfg_enableClaude: enableClaude.checked

    Kirigami.Heading {
        text: i18n("Providers")
        level: 2
        Kirigami.FormData.isSection: true
    }

    Controls.CheckBox {
        id: enableCodex
        text: i18n("Codex")
    }

    Controls.CheckBox {
        id: enableClaude
        text: i18n("Claude Code")
    }

    Kirigami.Heading {
        text: i18n("Updates")
        level: 2
        Kirigami.FormData.isSection: true
    }

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

    Kirigami.Heading {
        text: i18n("Advanced")
        level: 2
        Kirigami.FormData.isSection: true
    }
}
