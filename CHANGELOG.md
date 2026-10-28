# Changelog

All notable changes to ThermoSlop. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (0.x: anything may still change).
The Python package, the CLI, the MCP server and the Omarchy plugin share one
version.

## [Unreleased]

### Fixed

- In the panel, AWAY ALL and RESUME ALL for thermostats with no house (the
  OTHER group) ran `--all`, which also reached thermostats in the named
  houses. They now act on just the thermostats the confirmation counts, one
  `-t` at a time. Reported in the Omarchy marketplace review.

## [0.3.0] - 2026-10-27

### Security

- `thermoslop bar` treats thermostat names as untrusted: Waybar output
  escapes Pango markup, and SwiftBar output removes `|` and line breaks from
  names, so a name can't add a menu action or item. The redesigned panel
  keeps every label plain text (as in 0.2.3).

### Fixed

- mDNS no longer runs on loopback and VPN/Tailscale interfaces, where it
  can't send and zeroconf logged a traceback for every attempt (seen on
  macOS's utun).
- `thermoslop discover` columns line up with long model names.
- With piped input, the pairing prompt ends its line, so the result starts
  on a new one.
- `thermoslop bar` says why it printed nothing when run in a terminal.
- The panel said "watcher offline" whenever no thermostat could be reached,
  for example when you're away from home. It now says it can't reach them and
  keeps retrying, and saves "watcher offline" for a watcher that has really
  stopped. `thermoslop bar` makes the same distinction, and the zones pill
  says OFFLINE rather than IDLE.
- A long status line in the panel header no longer runs under the zones pill.
- Setpoint − / + in the panel (and scrolling on the bar) could start from a
  stale cached value and overshoot. They sent relative changes, which the
  thermostat applied to the value it still reported from before the last
  change. Each card now reads its thermostat before you can change it, sends
  the exact value it shows, and takes the result from that command's own
  reply (with a note if the thermostat took a different value). Presses made
  while a change is saving are sent next, never dropped.
- Changes to one thermostat from several ThermoSlop processes (panel, CLI,
  SwiftBar, MCP) now run one at a time, each starting from a confirmed value.
- `thermoslop setup` on distributions without a systemd user session
  (Alpine/OpenRC, Void/runit, containers) crashed with `FileNotFoundError`.
  It now explains how to run `thermoslop watch` under your own service
  manager or autostart.
- `thermoslop discover --house cabin` and `thermoslop log --house cabin`
  ignored `--house`; they now scan only that house's subnets and show only
  its thermostats' changes.
- Under `python -m thermoslop`, `setup` now points services at the installed
  `thermoslop` command.

### Changed

- `-t`/`--thermostat` and `--house` are gone from the help of commands that
  never used them (`pair`, `setup`, `watch`, `mcp`; `-t` on `discover`).
  They're still accepted, and ignored, until the next minor release.
- **BREAKING (panel):** the mode bar that changed every thermostat at once
  is gone. Each card has its own HEAT, COOL, OFF, AWAY and RESUME, acting on
  that thermostat only. A house with several thermostats gets AWAY ALL and
  RESUME ALL, which ask to confirm with a second press. To switch a whole
  house's mode, use `thermoslop mode heat --all --house home`.
- The bar widget's right and middle click act on the one thermostat or the
  one house it shows; with several houses shown they open the panel instead
  of changing every thermostat. Scrolling works only when the widget shows a
  single thermostat (it used to pick the first one, which with two houses
  was a cabin thermostat).
- SwiftBar: away and resume are per thermostat, plus per house for a house
  with several thermostats; the "(all)" items that spanned houses are gone.

### Added

- The panel works from the keyboard, the Omarchy way: the first arrow key
  shows a cursor, arrows (or h/j/k/l) move it over each card's −/+ and mode
  chips, Enter or Space presses, and + / - adjust the card it's on. Every
  control has a screen-reader name that says which thermostat it acts on,
  and the gauge and trend line have text alternatives.
- The panel's colors are readable in every Omarchy theme: dim, accent,
  green, blue and red text reach 4.5:1 and button outlines 3:1 (WCAG AA).
  A theme's own color is kept when it passes, and otherwise moved just
  enough. Before, outlines failed in all 22 themes, accent text in 5 and the
  cooling blue on light themes.
- The panel's "Target Δ +1.2°F" line now says it in words ("Room 1.2°F
  above target", "Room within range"), so it doesn't depend on its color.
- Informational text in the panel (status, notes, pairing hints, device
  details) is at body size; captions are only used for headings and button
  labels. The pairing spinner rests after 5 seconds and says "Still
  working…".
- `--plain` (or `THERMOSLOP_PLAIN=1`) prints words instead of symbols
  (`·`, `→`, `▲`, `—`), so output reads well in a screen reader:
  `Upstairs: 70.9°F, heating, set 61°F (heat), hold, 58% RH`. `--json` is
  unchanged.
- Better built-in help. `thermoslop --help` groups the commands, shows the
  first steps, and says where the config and data files live. Each command's
  help explains what it acts on without `-t`, has examples, and documents
  every option. New: `thermoslop help COMMAND`, and
  `thermoslop completion bash|zsh|fish` (completes commands, options, modes,
  houses and your thermostats' aliases).
- A `"demo": true` widget setting: pretend thermostats in the bar and panel,
  whose controls respond without reading or sending anything. The plugin
  preview image is taken with it.
- `thermoslop bar` for other status bars: `text` (i3blocks, polybar),
  `waybar` (JSON with heating/cooling/away/stale classes) and `swiftbar`
  (macOS menu bar with actions). `--follow` updates on every state change.
  It reads only the watcher's state file.

## [0.2.3] - 2026-10-25

### Security

- The Omarchy panel no longer lets device text render as rich text. Qt
  guessed "rich text" from content, so a device on the LAN could advertise
  a name or model with `<img src="http://…">`, and opening Add thermostat
  fetched that URL before anything was paired. Every label in the plugin is
  now plain text, and a test keeps it that way. Reported in the Omarchy
  plugin marketplace review.
- Text from devices (discovery names, models and fields, thermostat names)
  is cleaned where it enters: control characters (terminal escape
  sequences) and bidirectional overrides are removed, and it's cut to 64
  characters. This protects terminal output, the state file and MCP results.

### Documentation

- `SECURITY.md` lists the untrusted text sources and how each display
  handles them; `RELEASING.md` has a security checklist for marketplace
  submissions, and how to cut a patch from a maintenance branch.

## [0.2.2] - 2026-10-22

### Changed

- The panel's "watcher offline" hint now says `run: thermoslop setup`, which
  works on Linux and macOS and also covers a watcher that was never
  installed (it said `systemctl --user start thermoslop-watch`).

## [0.2.1] - 2026-10-22

### Added

- A preview image of the panel for the Omarchy plugin marketplace.

### Documentation

- Removal instructions and a dependencies section in the plugin README
  (what it needs, and the commands it runs), and an uninstall section in the
  main README.

## [0.2.0] - 2026-10-22

The first public release. Everything below is new compared with the
unpublished 0.1.0.

### Added

- **CLI** (`thermoslop`): `status`, `set` (absolute, relative, heat/cool),
  `mode`, `home`/`away`/`sleep`, `resume`, `discover`, `pair`, `unpair`,
  `watch`, `log`, `dump`, `mcp` and `--version`. `--json` on everything.
- **Local HomeKit control of ecobee thermostats:** no cloud, no ecobee
  developer key.
  - Discovery reaches across NAT, VLANs and Tailscale via unicast DNS-SD.
  - Pairing asks for the code after pair-setup starts, because ecobee shows
    a fresh one.
  - A thermostat is found again by device id when its IP changes.
- **Several houses:** houses are named subnets in the config; `--house`
  selects one; output and the widget group thermostats by house.
- **Watcher service** (`thermoslop-watch`): keeps a state file live from
  HomeKit events, and records a temperature trend (`trend_hours`, 24 by
  default).
- **Change log** (`~/.local/state/thermoslop/changes.jsonl`, shown by
  `thermoslop log`): every change, tagged `mcp`, `cli`, `widget` or
  `external`. The watcher logs changes made outside ThermoSlop (the
  thermostat, the ecobee app, its schedule), including ones made while it
  was stopped.
- **MCP server** (`thermoslop mcp`): over stdio, or streamable HTTP on
  Tailscale addresses only, with callers identified by `tailscale whois`.
  Guardrails:
  - a setpoint range, and `off` only on opt-in
  - a rate limit shared by every server process
  - read-only mode
  - per-thermostat results for house-wide changes
  - explicit temperature units
- **Omarchy bar widget** (`martellj.thermoslop`): temperatures in the bar,
  and a panel with:
  - per-thermostat cards: ring gauge, setpoint − / +, trend
  - a mode bar
  - pairing from the panel, with a demo mode
  - IPC commands (`omarchy-shell thermoslop open|add|pair`)
  - a banner when the CLI is missing or older than the plugin
- **Installs from PyPI:** `uv tool install thermoslop`, then `thermoslop
  setup` installs the background services. Linux gets systemd user units,
  macOS gets launchd agents (CLI, watcher and MCP server; the bar widget is
  Omarchy-only), and on Omarchy it offers to add the plugin.
  `setup --remove` keeps your data.
- The Omarchy plugin is published on its own at
  [martellj/thermoslop-omarchy](https://github.com/martellj/thermoslop-omarchy)
  for `omarchy plugin add`.
- The ThermoSlop logo (`assets/`).

### Security

- Pairing keys, config, the change log and the state cache are readable only
  by you: mode 600 files in 700 directories.
- MCP HTTP: exact-login or stable-device allow-list entries only, DNS-
  rebinding protection, failed lookups never cached. See `SECURITY.md`.
- Independent review findings fixed before release:
  - the rate-limit race
  - weak allow-list entries
  - setpoint confirmation that didn't check the value
  - ambiguous pairing by name
  - unit inference from the cache
  - Ctrl-C hanging at the pairing prompt
  - attribution gaps

## 0.1.0

Unpublished development version.
