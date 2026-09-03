import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    property alias cfg_refreshMinutes: refresh.value
    property alias cfg_enableCodex: enableCodex.checked
    property alias cfg_enableClaude: enableClaude.checked
    property alias cfg_codexDetected: codexDetected.value
    property alias cfg_claudeDetected: claudeDetected.value
    property alias cfg_codexGaugeLimit: codexGaugeLimit.currentIndex
    property alias cfg_claudeGaugeLimit: claudeGaugeLimit.currentIndex

    Kirigami.Heading {
        text: i18n("Providers")
        level: 2
        Kirigami.FormData.isSection: true
    }

    Controls.CheckBox {
        id: enableCodex
        text: codexDetected.value ? i18n("Codex") : i18n("Codex — not detected")
    }

    Controls.CheckBox {
        id: enableClaude
        text: claudeDetected.value ? i18n("Claude Code") : i18n("Claude Code — not detected")
    }

    QtObject {
        id: codexDetected
        property bool value: false
    }

    QtObject {
        id: claudeDetected
        property bool value: false
    }

    Kirigami.Heading {
        text: i18n("Panel gauges")
        level: 2
        Kirigami.FormData.isSection: true
    }

    Controls.ComboBox {
        id: codexGaugeLimit
        Kirigami.FormData.label: i18n("Codex allowance:")
        model: [
            i18n("First available"),
            i18n("Short-window allowance"),
            i18n("Weekly allowance")
        ]
    }

    Controls.ComboBox {
        id: claudeGaugeLimit
        Kirigami.FormData.label: i18n("Claude allowance:")
        model: [
            i18n("First available"),
            i18n("Short-window allowance"),
            i18n("Weekly allowance")
        ]
    }

    Kirigami.Heading {
        text: i18n("Updates")
        level: 2
        Kirigami.FormData.isSection: true
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
