.pragma library

// limitPreference: 0 = first available, 1 = short window, 2 = weekly
function selectedLimit(provider, limitPreference) {
    var limits = provider && provider.account && provider.account.limits ? provider.account.limits : []
    if (limits.length === 0) return null
    if (limitPreference === 2) {
        for (var i = 0; i < limits.length; i++) {
            if (Number(limits[i].windowMinutes) === 10080) return limits[i]
        }
    } else if (limitPreference === 1) {
        for (var j = 0; j < limits.length; j++) {
            var minutes = Number(limits[j].windowMinutes)
            if (minutes > 0 && minutes < 10080) return limits[j]
        }
    }
    return limits[0]
}
