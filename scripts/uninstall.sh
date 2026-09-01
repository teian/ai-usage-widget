#!/usr/bin/env bash
set -euo pipefail

bin_path="${XDG_BIN_HOME:-${HOME}/.local/bin}/ai-usage-codex"
lib_path="${XDG_DATA_HOME:-${HOME}/.local/share}/ai-usage-widget"

kpackagetool6 --type Plasma/Applet --remove com.github.dean.aiusage || true
rm -f -- "$bin_path"
rm -rf -- "$lib_path"

echo "Uninstalled AI Usage."
