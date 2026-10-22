#!/bin/bash
# Install ThermoSlop (editable, from this checkout): the thermoslop CLI, the
# watcher service, the MCP service (off by default), and the Omarchy bar
# widget. Safe to re-run, and upgrades an install from before the rename
# (when it was called "ecobee") in place.
set -euo pipefail

repo="$(cd "$(dirname "$0")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
venv="$data/thermoslop/venv"
units="$HOME/.config/systemd/user"
plugins="$HOME/.config/omarchy/plugins"
shell_json="$HOME/.config/omarchy/shell.json"
plugin_id=martellj.thermoslop

# -- before the rename: stop the old services so the files can move --
mcp_was_enabled=false
for old in ecobee-watch ecobee-mcp; do
  # -L too: the unit is a symlink into the checkout, which dangles once the repo file is renamed.
  if [[ -e $units/$old.service || -L $units/$old.service ]]; then
    [[ $old == ecobee-mcp && -L $units/default.target.wants/$old.service ]] && mcp_was_enabled=true
    systemctl --user stop "$old.service" 2>/dev/null || true
    rm -f "$units/$old.service" "$units/default.target.wants/$old.service"
    echo "→ removed $old.service"
  fi
done
if [[ -L $HOME/.local/bin/ecobee && $(readlink "$HOME/.local/bin/ecobee") == "$data/ecobee/venv/"* ]]; then
  rm "$HOME/.local/bin/ecobee"
  echo "→ removed ~/.local/bin/ecobee"
fi

echo "→ venv $venv"
[[ -x $venv/bin/python ]] || python3 -m venv "$venv"
"$venv/bin/pip" install -q --upgrade -e "$repo"

mkdir -p "$HOME/.local/bin"
ln -sfn "$venv/bin/thermoslop" "$HOME/.local/bin/thermoslop"
echo "→ ~/.local/bin/thermoslop"

# Moves config, pairings, cache and audit log over from the old name (no-op otherwise).
"$venv/bin/python" -c 'from thermoslop.config import migrate_legacy; migrate_legacy()'

mkdir -p "$units"
ln -sfn "$repo/systemd/thermoslop-watch.service" "$units/thermoslop-watch.service"
# Installed but off: serving MCP over the tailnet is opt-in.
ln -sfn "$repo/systemd/thermoslop-mcp.service" "$units/thermoslop-mcp.service"
systemctl --user daemon-reload
systemctl --user enable --now thermoslop-watch.service
systemctl --user restart thermoslop-watch.service  # pick up new code on re-runs
echo "→ thermoslop-watch.service enabled"
if $mcp_was_enabled; then
  systemctl --user enable --now thermoslop-mcp.service
  echo "→ thermoslop-mcp.service enabled (ecobee-mcp was)"
else
  echo "→ thermoslop-mcp.service installed (off; enable with: systemctl --user enable --now thermoslop-mcp)"
fi

if [[ -d $plugins ]]; then
  rm -f "$plugins/john.ecobee"
  ln -sfn "$repo/omarchy/$plugin_id" "$plugins/$plugin_id"
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
  sleep 1
  if grep -q '"john.ecobee"' "$shell_json" 2>/dev/null; then
    # Rename the bar entry in place, so it keeps its slot and settings.
    cp "$shell_json" "$shell_json.bak-thermoslop"
    tmp=$(mktemp)
    jq --arg id "$plugin_id" 'walk(if type == "object" and .id == "john.ecobee" then .id = $id else . end)' \
      "$shell_json" >"$tmp"
    jq -e . "$tmp" >/dev/null && mv "$tmp" "$shell_json"
    echo "→ bar entry john.ecobee renamed to $plugin_id (backup: shell.json.bak-thermoslop)"
  elif ! grep -q "\"$plugin_id\"" "$shell_json" 2>/dev/null; then
    omarchy plugin enable "$plugin_id" --before omarchy.weather || omarchy plugin enable "$plugin_id"
  fi
  echo "→ bar widget $plugin_id"
fi

if [[ -d $data/ecobee/venv ]]; then
  rm -rf "$data/ecobee/venv"
  rmdir "$data/ecobee" 2>/dev/null || true
  echo "→ removed the old venv"
fi

if [[ ! -s $data/thermoslop/pairing.json ]]; then
  echo
  echo "Next: thermoslop discover, then thermoslop pair \"<name>\" for each thermostat."
fi
