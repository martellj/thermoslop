#!/bin/bash
# Install the ecobee CLI (editable, from this checkout), the watcher service,
# and the Omarchy bar widget. Safe to re-run.
set -euo pipefail

repo="$(cd "$(dirname "$0")" && pwd)"
venv="${XDG_DATA_HOME:-$HOME/.local/share}/ecobee/venv"
plugins="$HOME/.config/omarchy/plugins"

echo "→ venv $venv"
[[ -x $venv/bin/python ]] || python3 -m venv "$venv"
"$venv/bin/pip" install -q --upgrade -e "$repo"

mkdir -p "$HOME/.local/bin"
ln -sfn "$venv/bin/ecobee" "$HOME/.local/bin/ecobee"
echo "→ ~/.local/bin/ecobee"

mkdir -p "$HOME/.config/systemd/user"
ln -sfn "$repo/systemd/ecobee-watch.service" "$HOME/.config/systemd/user/ecobee-watch.service"
systemctl --user daemon-reload
systemctl --user enable --now ecobee-watch.service
echo "→ ecobee-watch.service enabled"
# Installed but off: serving MCP over the tailnet is opt-in.
ln -sfn "$repo/systemd/ecobee-mcp.service" "$HOME/.config/systemd/user/ecobee-mcp.service"
systemctl --user daemon-reload
echo "→ ecobee-mcp.service installed (off; enable with: systemctl --user enable --now ecobee-mcp)"

if [[ -d $plugins ]]; then
  ln -sfn "$repo/omarchy/john.ecobee" "$plugins/john.ecobee"
  if ! grep -q '"john.ecobee"' "$HOME/.config/omarchy/shell.json" 2>/dev/null; then
    omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
    sleep 1
    omarchy plugin enable john.ecobee --before omarchy.weather || omarchy plugin enable john.ecobee
  fi
  echo "→ bar widget john.ecobee"
fi

if [[ ! -s ${XDG_DATA_HOME:-$HOME/.local/share}/ecobee/pairing.json ]]; then
  echo
  echo "Next: ecobee discover, then ecobee pair \"<name>\" for each thermostat."
fi
