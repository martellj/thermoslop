# Changelog

All notable changes to ThermoSlop. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (0.x: anything may still change).
The Python package, the CLI, the MCP server and the Omarchy plugin share one
version.

## [Unreleased]

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
