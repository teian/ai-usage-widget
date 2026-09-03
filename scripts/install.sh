#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
package_dir="$project_dir/plasmoid/package"

# Bundle the collector into the plasmoid package itself so the widget is
# self-contained - nothing gets installed outside kpackagetool's own
# applet directory.
rm -rf "$package_dir/contents/collector" "$package_dir/contents/bin"
cp -R "$project_dir/collector" "$package_dir/contents/collector"
find "$package_dir/contents/collector" -name '__pycache__' -type d -prune -exec rm -rf {} +
mkdir -p "$package_dir/contents/bin"
install -m 755 "$project_dir/bin/ai-usage" "$package_dir/contents/bin/ai-usage"

kpackagetool6 --type Plasma/Applet --upgrade "$package_dir" 2>/dev/null || \
  kpackagetool6 --type Plasma/Applet --install "$package_dir"

echo "Installed AI Usage. Add it from Plasma's widget picker."
