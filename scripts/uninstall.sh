#!/usr/bin/env bash
set -euo pipefail

kpackagetool6 --type Plasma/Applet --remove com.github.dean.aiusage || true

# Clean up leftovers from installs before the collector was bundled into the
# plasmoid package itself.
bin_dir="${XDG_BIN_HOME:-${HOME}/.local/bin}"
lib_path="${XDG_DATA_HOME:-${HOME}/.local/share}/ai-usage-widget"
rm -f -- "$bin_dir/ai-usage" "$bin_dir/ai-usage-codex" "$bin_dir/ai-usage-claude"
rm -rf -- "$lib_path"

echo "Uninstalled AI Usage."
