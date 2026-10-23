<p align="center"><img src="assets/thermoslop-logo.svg" alt="ThermoSlop" width="420"></p>

# ThermoSlop

Your thermostats in the terminal, the status bar, and your AI agents' hands.
ThermoSlop controls ecobee thermostats locally over HomeKit:

- `thermoslop`, a CLI for the terminal, scripts and AI tools
- an MCP server, with guardrails
- an Omarchy bar widget

No cloud and no ecobee developer key, and it works while the internet is down.

> **Unofficial.** ThermoSlop is an independent project. It is not affiliated
> with, endorsed by, or supported by ecobee Inc. or Apple Inc. "ecobee" and
> "HomeKit" are trademarks of their respective owners, and are used here only
> to say what this works with. It talks to your thermostat over the local
> HomeKit protocol. Use it at your own risk (see [LICENSE](LICENSE)).

```
$ thermoslop status
Main Floor: 69.8°F · ▲ heating · set 68°F (heat) · home · 42% RH
    Bedroom: 67.1°F, occupied
Upstairs: 71.2°F · idle · set 67°F–75°F (auto) · home · 40% RH
```

## Install

```bash
uv tool install thermoslop    # or: pipx install thermoslop
thermoslop setup              # starts the watcher service; on Omarchy, offers the bar widget
thermoslop discover           # lists thermostats and whether they're ready to pair
thermoslop pair <device id>   # asks for the HomeKit code shown on the thermostat
```

- **Linux:** `setup` installs systemd user services.
- **macOS:** `setup` installs launchd agents. The CLI, watcher and MCP server
  work there; the bar widget is Omarchy-only.
- **Removing the services:** `thermoslop setup --remove` takes them out and
  keeps your pairings and history.
- **The Omarchy plugin** can also be added on its own:
  `omarchy plugin add https://github.com/martellj/thermoslop-omarchy --enable`.

**Uninstalling:**

```bash
thermoslop setup --remove        # stop and remove the services
uv tool uninstall thermoslop     # or: pipx uninstall thermoslop
omarchy plugin remove martellj.thermoslop   # on Omarchy
```

Your pairings, config and history stay in `~/.config/thermoslop`,
`~/.local/share/thermoslop` and `~/.local/state/thermoslop` until you delete
them.

From a checkout instead (for development), `./install.sh` makes an editable
venv, runs `thermoslop setup`, and symlinks the widget from `omarchy/`.

The HomeKit code is on the thermostat under **Menu → Settings → HomeKit**
(the exact menu path varies with firmware). ecobee shows a **new code once
pairing starts**, so `thermoslop pair` starts first and then asks for the code
on the screen at that moment; a code read beforehand is rejected. An ecobee pairs with **one**
HomeKit controller, so it has to be removed from Apple Home before pairing
here, and pairing it back to Apple Home takes it away from this box.

Upgrading from before the rename (when the project was called `ecobee`):
rerun `./install.sh`. It moves the config, pairings, cache and change log to
the `thermoslop` locations, swaps the services, and renames the bar entry in
place, so nothing has to be paired again.

The watcher service restarts on its own when `pairing.json` changes, so
newly paired thermostats show up in the bar without a manual restart.

## Commands

All of them take `--json` (machine-readable; errors come back as
`{"error": ...}` with exit code 1) and `-t NAME` (alias, prefix ok).

Changes return once the thermostat reads back what was asked. If it hasn't
within 8 seconds, the command prints what it does read and exits **2** ("sent
but not confirmed"). Exit 0 means confirmed.

House-wide `home|away|sleep|resume` tries every thermostat even if one fails,
reports each, and exits 1 if any failed. With `--json`, failures appear as
`{"alias": ..., "error": ...}` beside the states.

`pair` takes a device id, an address or a name. If two devices share the name
(a "Main Floor" in each house), it lists them so you can pair by id.

| Command | What it does |
|---|---|
| `thermoslop status [--live]` | Temperature, humidity, mode, setpoints, comfort setting, sensors. Uses the watcher's cache when fresh; `--live` asks the thermostat. |
| `thermoslop set 70` / `set +1` / `set -2` | Target temperature in heat/cool mode. Relative changes also shift both setpoints in auto mode. |
| `thermoslop set --heat 68 --cool 75` | Auto-mode setpoints. |
| `thermoslop mode heat\|cool\|auto\|off` | HVAC mode. |
| `thermoslop home\|away\|sleep [--all]` | Hold a comfort setting. |
| `thermoslop resume [--all]` | Clear holds and go back to the schedule. |
| `thermoslop discover [--all]` | Find HomeKit thermostats (or every HomeKit accessory with `--all`). |
| `thermoslop pair NAME [--demo]`, `thermoslop unpair -t NAME` | Manage pairings (`--demo`: a pretend thermostat, nothing saved). |
| `thermoslop watch` | The daemon behind the widget (run by `thermoslop-watch.service`). |
| `thermoslop bar [--format text\|waybar\|swiftbar] [--follow]` | Status-bar output for Waybar, polybar, i3blocks or SwiftBar (see below). |
| `thermoslop log [--hours 24] [--source S]` | Recent changes and where they came from (see [Change log](#change-log)). |
| `thermoslop mcp [--read-only]` | MCP server for AI clients (see below). |
| `thermoslop dump -t NAME` | Raw HomeKit accessory data, for debugging. |

When more than one thermostat is paired, commands that change something need
`-t`, `--all`, or `default = "alias"` in the config.

Writing a setpoint creates a hold, just like changing it on the thermostat.
`thermoslop resume` clears it.

## MCP server for AI clients

`thermoslop mcp` serves the thermostats as MCP tools over stdio:

| Tool | Does |
|---|---|
| `list_thermostats`, `get_status` | Read-only. Same JSON as `thermoslop status --json`. |
| `set_temperature` | Absolute setpoint (`target`, or `heat`/`cool` in auto mode). |
| `adjust_temperature` | Relative change, −5 to +5. |
| `set_mode` | heat / cool / auto (off only if allowed). |
| `set_comfort`, `resume_schedule` | Per thermostat, or a whole `house`. Reports per thermostat whether it took effect. |

Pairing isn't exposed. Each tool takes `thermostat` (alias or prefix) and/or `house`.

**Claude Code:**

```bash
claude mcp add --scope user thermoslop -- ~/.local/bin/thermoslop mcp
```

**Claude Desktop**, or any client that takes a JSON config:

```json
{ "mcpServers": { "thermoslop": { "command": "/home/you/.local/bin/thermoslop", "args": ["mcp"] } } }
```

### Other machines on your tailnet

`thermoslop mcp --http` serves streamable HTTP for MCP clients on other machines
(a Mac, a laptop). Nothing is reachable from the LAN or the internet:

- It listens only on this machine's Tailscale addresses, and refuses
  `--bind 0.0.0.0` or any non-Tailscale address.
- Each request's source is looked up with `tailscale whois`. It's answered only
  if the caller is in `[mcp] allow`, which defaults to this node's owner.
  Anyone else gets 403, and the refusal is logged. There are no tokens: the
  tailnet already vouches for the device. A lookup is reused for up to 30
  seconds; failures never are.
- Requests must be addressed to this node's tailnet names, and requests carrying
  a browser `Origin` are refused, so a web page can't reach it by rebinding a
  domain to this address.

```bash
systemctl --user enable --now thermoslop-mcp    # installed by install.sh, off by default
```

```toml
[mcp]
http_port = 8765
allow = [
  "alice@example.com",                          # everyone signed in as this exact login
  "node:nAbC123DEF4CNTRL@bob@example.com",      # or just one device, while bob owns it
]
```

A device's stable ID is `Node.StableID` in `tailscale whois --json <its tailnet IP>`.
Machine names and login prefixes aren't accepted: renaming a machine, or
registering a look-alike login, could otherwise get someone in.

On the other machine, point the client at `http://<node>:8765/mcp`, where
`<node>` is this machine's MagicDNS name:

```bash
claude mcp add --scope user --transport http thermoslop http://omarchy:8765/mcp
```

The change log records these callers as `login on node`.

### Guardrails

The CLI is unrestricted. Changes through MCP are checked against `[mcp]` in the
config:

```toml
[mcp]
read_only = false            # true (or `thermoslop mcp --read-only`) offers only the read tools
min_setpoint = "55F"         # setpoints outside this range are refused ("13C" works too)
max_setpoint = "80F"
allow_off = false            # set_mode off is refused unless true
max_changes_per_hour = 20    # each thermostat changed counts once; shared by all processes; survives restarts
units = "F"                  # unit of temperatures in tool calls that don't set `unit` (default: top-level units, else F)
```

Temperatures an agent sends are in `[mcp] units` unless the call sets
`unit: "C"` or `"F"`, and they're converted to each thermostat's own units
before the limits are checked. Readings come back in each thermostat's units
(its `units` field).

Comfort holds and resuming the schedule switch to the thermostat's own preset
temperatures, which the setpoint range doesn't cover. A house-wide comfort or
resume reports, logs and counts each thermostat separately, so one that fails
doesn't hide the others.

Refusals come back as tool errors that explain why, so the agent can tell you
instead of retrying. Every attempted change, refusals and failures included,
goes to the [change log](#change-log) with source `mcp`. The rate limit counts
only MCP changes.

Comfort changes are verified by reading the thermostat back. An ecobee3 lite
(firmware 4.8.70240) does apply away, home and resume, but takes 2–4 s to
report them. Writes wait up to 8 s for the thermostat to report the change.

## Change log

Every change to a thermostat is recorded in
`~/.local/state/thermoslop/changes.jsonl`, whatever made it, with the time, the
caller, the outcome, and the mode, setpoints and comfort setting before and
after. `thermoslop log` shows it:

```
$ thermoslop log
Oct 22 19:55:04  cli      set_temperature  by terminal (alice)
    upstairs: target 60→61, heat 60→61
Oct 22 19:58:40  external external_change  by thermostat, app or schedule
    upstairs: target 61→62, heat 61→62
```

| Source | Where the change came from |
|---|---|
| `mcp` | An AI client through `thermoslop mcp` (caller: the local client, or `login on node` over the tailnet) |
| `cli` | `thermoslop` in a terminal or script |
| `widget` | The bar widget's panel buttons, scroll or clicks |
| `external` | Not ThermoSlop: the thermostat's screen, the ecobee app, or its schedule |

`external` entries come from the watcher, which compares each thermostat's
settings on every update.
- **Attribution:** a change counts as ThermoSlop's only if a ThermoSlop entry
  for that thermostat, from about a minute before to 20 seconds after it,
  explains the new values. So an app change made right after a widget change
  is still caught.
- **No source detail:** HomeKit doesn't say who made a change, so a screen,
  app or schedule change all show as `external`, logged with the time the
  watcher saw them.
- **Restarts:** when the watcher starts, it compares its first reading with
  the last cached state. A change made while it was stopped is logged then,
  unless a ThermoSlop change since that cached reading explains it.

This is a heuristic for your own records, not forensic proof.

## Bar widget (`omarchy/martellj.thermoslop`)

The bar shows an icon (flame while heating, snowflake while cooling, away icon
when every thermostat is away) and each thermostat's temperature.

- **left click**: the ThermoSlop panel, with one card per thermostat:
  - temperature on a ring gauge, and humidity
  - a SET box with − / + (presses are batched and sent together)
  - a trend line (24 hours by default), and how far the room is from its target

  The mode bar along the bottom (heat, cool, eco = away, hold = resume the
  schedule) acts on every thermostat the panel shows. Colors come from your
  Omarchy theme.
- **+ ADD THERMOSTAT** (in the panel): pair a new thermostat without a terminal.
  1. It scans the network and lists HomeKit thermostats as ready, paired here or
     paired elsewhere.
  2. PAIR starts pairing.
  3. It asks for the code the thermostat shows *now*, which changes once pairing
     starts.
  4. It shows success, or the error with Try Again.

  It runs the same `thermoslop discover` / `thermoslop pair` as the terminal.
- **right click**: away hold on all thermostats, or resume the schedule if any is away
- **middle click**: resume the schedule
- **scroll**: setpoint ±1° on the first thermostat, sent once scrolling stops

It reads `~/.cache/thermoslop/state.json`, which `thermoslop watch` keeps
current with HomeKit event subscriptions. The watcher also records one
temperature per thermostat every 5 minutes for the trend line, kept for
`trend_hours` (24 by default; 0 turns the trend off). Each point is a real
reading, not an average, and gaps while a thermostat is unreachable are drawn
straight across. The widget never polls the thermostats itself, and dims when the data
is more than 10 minutes old.

To try the pairing flow without touching your pairings, set
`"pairingDemo": true` on the widget's entry in `~/.config/omarchy/shell.json`.
"Add thermostat" then uses `--demo`: a pretend "Basement" thermostat that shows
code `314-15-926` (any other code is rejected) and a "Garage" paired elsewhere.
Nothing is paired, saved or logged. The same works from a terminal:
`thermoslop discover --demo` and `thermoslop pair Basement --demo`.

From scripts or a keybinding: `omarchy-shell thermoslop open` opens the panel,
`omarchy-shell thermoslop add` opens it on "Add thermostat", and
`omarchy-shell thermoslop pair NAME` starts pairing with a discovered device.

To show or control just one thermostat, set `"thermostat": "upstairs"` on its
entry in `~/.config/omarchy/shell.json`. `allowMultiple` is on, so you can
add one widget per thermostat.

The plugin directory is symlinked into `~/.config/omarchy/plugins/`, and the
shell doesn't hot-reload through that symlink. A rescan keeps the compiled
widget, so after editing the QML restart the shell with `omarchy restart shell`.
`omarchy-shell shell summon martellj.thermoslop` then opens the panel.

## Other status bars

`thermoslop bar` prints the thermostats for any bar. It reads only the
watcher's state file and never contacts the thermostats, so it's cheap to run
often. It uses the same icon and staleness rules as the Omarchy widget, and
takes `-t` and `--house` filters.

| Format | Output |
|---|---|
| `--format text` (default) | `󰔏 68° 71° │ 55°` |
| `--format waybar` | JSON: `text`, `tooltip`, and `class`, one of `heating`, `cooling`, `away`, `idle`, `stale`, `empty` |
| `--format swiftbar` | A title plus a dropdown with actions (±1°, away, resume) |

Add `--follow` to print again whenever the state changes, instead of polling.

**Waybar** (Hyprland, Sway), in `~/.config/waybar/config.jsonc`:

```jsonc
"custom/thermoslop": {
  "exec": "thermoslop bar --format waybar --follow",
  "return-type": "json",
  "restart-interval": 30,
  "on-click": "notify-send ThermoSlop \"$(thermoslop status)\"",
  "on-click-right": "thermoslop away --all",
  "on-click-middle": "thermoslop resume --all",
  "on-scroll-up": "thermoslop set +1 -t upstairs",
  "on-scroll-down": "thermoslop set -1 -t upstairs"
}
```

```css
#custom-thermoslop.heating { color: #faa968; }
#custom-thermoslop.cooling { color: #6cb6d9; }
#custom-thermoslop.stale   { opacity: 0.5; }
```

**i3blocks / polybar:**

```ini
# i3blocks
[thermoslop]
command=thermoslop bar
interval=60

# polybar
[module/thermoslop]
type = custom/script
exec = thermoslop bar --follow
tail = true
```

**SwiftBar (macOS):** save as `thermoslop.30s.sh` in your SwiftBar plugin
folder and make it executable. SwiftBar runs plugins without your shell's
PATH, so use the full path:

```sh
#!/bin/bash
exec "$HOME/.local/bin/thermoslop" bar --format swiftbar
```

## Configuration: `~/.config/thermoslop/config.toml`

```toml
subnets = ["192.168.1.0/24"]  # unicast discovery fallback (see below)
default = "main-floor"         # thermostat for commands without -t
units = "F"                    # override each thermostat's display units
poll_interval = 60             # watcher's full refresh, between events
trend_hours = 24               # widget trend line window, up to 168; 0 = off

[houses]                       # optional; subnets here are scanned too
home = ["192.168.1.0/24"]
cabin = ["192.168.2.0/24"]
```

## Several houses

A thermostat belongs to the house whose subnet holds its IP. One controller
can run every house as long as it can route to each house's LAN. Here that's
Tailscale, with each house's OpenWrt router advertising its LAN as a subnet
route, and `tailscale set --accept-routes` on this machine.

- `thermoslop status` groups thermostats under a heading per house.
- `--house cabin` limits any command to one house; `thermoslop away --house cabin`
  holds away on all of them.
- When a thermostat's name is already taken (two "Main Floor"s), `pair`
  prefixes the alias with its house: `cabin-main-floor`.
- The widget groups temperatures per house (`68° 70° │ 55°`).
  `"house": "cabin"` on a widget entry limits it to one house.

If the tunnel drops, that house's thermostats show as unavailable and keep
running their own schedules.

## Networking notes

HomeKit discovery normally uses multicast mDNS, which doesn't cross NAT,
routers or VLANs. A machine that can't see the thermostats' multicast (a VM
behind NAT, another VLAN, another house over Tailscale) can list their subnets
in `subnets`. `discover` then also sends **unicast DNS-SD queries** to every
host there, and those do get through. Connections then go straight to the stored IP:port.

If a thermostat's IP or HAP port changes, the next failed connection
re-locates it by device id (first at its last IP, then by scanning `subnets`)
and updates `pairing.json`. A DHCP reservation for each thermostat on the
router makes this rarely needed.

## Files

| Path | Contents |
|---|---|
| `~/.local/share/thermoslop/pairing.json` | HomeKit pairing keys (mode 600 in a 700 directory; treat it like an SSH key, see [SECURITY.md](SECURITY.md)) |
| `~/.local/share/thermoslop/charmap.json` | aiohomekit accessory cache |
| `~/.local/state/thermoslop/changes.jsonl` | [Change log](#change-log): every change, from any source (mode 600) |
| `~/.cache/thermoslop/state.json` | Latest state and trend history, written atomically by the watcher and CLI (mode 600 in a 700 directory: it reveals occupancy and when you're away) |

## Development

```bash
~/.local/share/thermoslop/venv/bin/pip install -e '.[test]'
~/.local/share/thermoslop/venv/bin/python -m pytest
```

`./install.sh` sets up a development install from the checkout.
`scripts/check-version`, `scripts/check-dist` and `scripts/check-plugin` are
the release checks, which CI runs too. Releases are cut with
`scripts/release X.Y.Z`; see [RELEASING.md](RELEASING.md).

Built on [aiohomekit](https://github.com/Jc2k/aiohomekit), the library behind
Home Assistant's HomeKit Controller. ecobee's comfort settings and hold
handling use vendor characteristics, written the same way Home Assistant
writes them.
