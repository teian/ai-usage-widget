#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
bin_dir="${XDG_BIN_HOME:-${HOME}/.local/bin}"
lib_dir="${XDG_DATA_HOME:-${HOME}/.local/share}/ai-usage-widget"

mkdir -p "$bin_dir" "$lib_dir"
cp -R "$project_dir/collector" "$lib_dir/"
install -m 755 "$project_dir/bin/ai-usage-codex" "$bin_dir/ai-usage-codex"

# The installed launcher needs to import the installed collector package.
sed -i "s|PROJECT_ROOT = Path(__file__).resolve().parent.parent|PROJECT_ROOT = Path(\"$lib_dir\")|" "$bin_dir/ai-usage-codex"

kpackagetool6 --type Plasma/Applet --upgrade "$project_dir/plasmoid/package" 2>/dev/null || \
  kpackagetool6 --type Plasma/Applet --install "$project_dir/plasmoid/package"

echo "Installed AI Usage. Add it from Plasma's widget picker."
