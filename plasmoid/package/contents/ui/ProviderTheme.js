.pragma library

var colors = {
    claude: "#D97757",
    codex: "#10A37F"
}

var fallbackColor = "#7F7F7F"

function accentColor(providerId) {
    return colors[providerId] || fallbackColor
}
