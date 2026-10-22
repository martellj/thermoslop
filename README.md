# ecobee

Local control of ecobee thermostats over HomeKit: a CLI (`ecobee`) for the
terminal, scripts and AI tools, plus an Omarchy bar widget. No cloud and no
ecobee developer key. It works while the internet is down.

```
$ ecobee status
Main Floor: 69.8°F · ▲ heating · set 68°F (heat) · home · 42% RH
    Bedroom: 67.1°F, occupied
Upstairs: 71.2°F · idle · set 67°F–75°F (auto) · home · 40% RH
```

## Install

```bash
./install.sh          # venv + ~/.local/bin/ecobee + ecobee-watch.service + bar widget
ecobee discover       # lists thermostats and whether they're ready to pair
ecobee pair "Main Floor"   # asks for the HomeKit code shown on the thermostat
ecobee pair Upstairs
```

The HomeKit code is on the thermostat under **Menu → Settings → HomeKit**
(the exact menu path varies with firmware). ecobee shows a **new code once
pairing starts**, so `ecobee pair` starts first and then asks for the code
on the screen at that moment; a code read beforehand is rejected. An ecobee pairs with **one**
HomeKit controller, so it has to be removed from Apple Home before pairing
here, and pairing it back to Apple Home takes it away from this box.

The watcher service restarts on its own when `pairing.json` changes, so
newly paired thermostats show up in the bar without a manual restart.

## Commands

All of them take `--json` (machine-readable; errors come back as
`{"error": ...}` with exit code 1) and `-t NAME` (alias, prefix ok).

| Command | What it does |
|---|---|
| `ecobee status [--live]` | Temperature, humidity, mode, setpoints, comfort setting, sensors. Uses the watcher's cache when fresh; `--live` asks the thermostat. |
| `ecobee set 70` / `set +1` / `set -2` | Target temperature in heat/cool mode. Relative changes also shift both setpoints in auto mode. |
| `ecobee set --heat 68 --cool 75` | Auto-mode setpoints. |
| `ecobee mode heat\|cool\|auto\|off` | HVAC mode. |
| `ecobee home\|away\|sleep [--all]` | Hold a comfort setting. |
| `ecobee resume [--all]` | Clear holds and go back to the schedule. |
| `ecobee discover [--all]` | Find HomeKit thermostats (or every HomeKit accessory with `--all`). |
| `ecobee pair NAME`, `ecobee unpair -t NAME` | Manage pairings. |
| `ecobee watch` | The daemon behind the widget (run by `ecobee-watch.service`). |
| `ecobee dump -t NAME` | Raw HomeKit accessory data, for debugging. |

When more than one thermostat is paired, commands that change something need
`-t`, `--all`, or `default = "alias"` in the config.

Writing a setpoint creates a hold, just like changing it on the thermostat.
`ecobee resume` clears it.

## Bar widget (`omarchy/john.ecobee`)

Shows an icon (flame while heating, snowflake while cooling, away icon when
every thermostat is away) and each thermostat's temperature. Hover for details.

- **left click**: notification with full status
- **right click**: away hold on all thermostats, or resume the schedule if any is away
- **middle click**: resume the schedule
- **scroll**: setpoint ±1° on the first thermostat, sent once scrolling stops

It reads `~/.cache/ecobee/state.json`, which `ecobee watch` keeps current with
HomeKit event subscriptions. It never polls the thermostats itself, and dims
when the data is more than 10 minutes old.

To show or control just one thermostat, set `"thermostat": "upstairs"` on its
entry in `~/.config/omarchy/shell.json`. `allowMultiple` is on, so you can
add one widget per thermostat.

The plugin directory is symlinked into `~/.config/omarchy/plugins/`, and the
shell doesn't hot-reload through that symlink. After editing the QML, run
`omarchy-shell shell rescanPlugins`.

## Configuration: `~/.config/ecobee/config.toml`

```toml
subnets = ["192.168.1.0/24"]  # unicast discovery fallback (see below)
default = "main-floor"         # thermostat for commands without -t
units = "F"                    # override each thermostat's display units
poll_interval = 60             # watcher's full refresh, between events
```

## Networking notes

HomeKit discovery normally uses multicast mDNS, which doesn't cross NAT. This
Omarchy box is a VM behind NAT (`10.0.2.x`), so `discover` also sends
**unicast DNS-SD queries** to every host in `subnets`, and those do get
through. Connections then go straight to the stored IP:port.

If a thermostat's IP or HAP port changes, the next failed connection
re-locates it by device id (first at its last IP, then by scanning `subnets`)
and updates `pairing.json`. A DHCP reservation for each thermostat on the
router makes this rarely needed.

## Files

| Path | Contents |
|---|---|
| `~/.local/share/ecobee/pairing.json` | HomeKit pairing keys (mode 600; treat it like an SSH key) |
| `~/.local/share/ecobee/charmap.json` | aiohomekit accessory cache |
| `~/.cache/ecobee/state.json` | Latest state, written atomically by the watcher and CLI |

## Development

```bash
~/.local/share/ecobee/venv/bin/pip install -e '.[test]'
~/.local/share/ecobee/venv/bin/python -m pytest
```

Built on [aiohomekit](https://github.com/Jc2k/aiohomekit), the library behind
Home Assistant's HomeKit Controller. ecobee's comfort settings and hold
handling use vendor characteristics, written the same way Home Assistant
writes them.
