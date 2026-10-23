<p align="center"><img src="assets/thermoslop-logo.svg" alt="ThermoSlop" width="380"></p>

# ThermoSlop for Omarchy

Your ecobee thermostats in the Omarchy bar, over local HomeKit: no cloud, no
ecobee account.

> **Unofficial.** Not affiliated with, endorsed by, or supported by ecobee
> Inc. or Apple Inc. "ecobee" and "HomeKit" are their trademarks, used here
> only to say what this works with.

This repo contains only the bar widget, and it updates when ThermoSlop
releases. The widget drives the `thermoslop` command, which does the actual
work. Source, issues and docs live at
[martellj/thermoslop](https://github.com/martellj/thermoslop).

![The ThermoSlop panel](preview.png)

## Dependencies

The widget runs the `thermoslop` command and reads the state file its watcher
keeps. It does nothing without them:

- **[thermoslop](https://pypi.org/project/thermoslop/)**, the Python package
  (CLI, watcher service, MCP server), installed with `uv` or `pipx`. It needs
  Python 3.11+ and pulls in `aiohomekit` and the `mcp` SDK. It must be the
  same version as this plugin or newer; the widget shows the upgrade command
  when it isn't.
- **HomeKit-capable ecobee thermostats** on a network this machine can reach.
- **Optional:** Tailscale, to reach thermostats in another house, or to use the
  MCP server from other machines.

The commands the widget runs:
- `thermoslop --version`, when it loads
- `thermoslop discover`, `thermoslop pair`, `thermoslop set`, `thermoslop mode`,
  `thermoslop away`/`resume`, only when you click or scroll

It never edits Omarchy or system configuration.

## Install

```bash
uv tool install --managed-python thermoslop   # the CLI, the watcher and the MCP server
thermoslop setup                # starts the watcher; on Omarchy offers to add this plugin
thermoslop discover             # find your thermostats
thermoslop pair <device id>     # or pair from the widget's panel: + ADD THERMOSTAT
```

To add the plugin by hand:

```bash
omarchy plugin add https://github.com/martellj/thermoslop-omarchy --enable
```

If the widget says "install thermoslop" or shows ↑, the CLI is missing or
older than the plugin. The panel shows the command to fix it.

## Remove

```bash
omarchy plugin remove martellj.thermoslop   # the bar widget
thermoslop setup --remove                   # stop and remove the background services
uv tool uninstall thermoslop                # the CLI (or: pipx uninstall thermoslop)
```

Removing the services or the CLI keeps your pairings, config and history in
`~/.config/thermoslop`, `~/.local/share/thermoslop` and
`~/.local/state/thermoslop`. Delete those folders too to remove everything.
Pairing data (`pairing.json`) holds the HomeKit key for your thermostats: to
revoke it on the thermostat itself, reset HomeKit there (Menu → Settings →
HomeKit).

## Using it

- **Bar:** an icon (heating, cooling, away) and each thermostat's
  temperature, grouped by house.
- **Left click:** the panel.
  - Per-thermostat cards: ring gauge, humidity, setpoint − / +, trend line.
  - A mode bar: heat, cool, eco (away), hold (resume the schedule).
  - **+ ADD THERMOSTAT** to pair.
- **Right click:** away on all thermostats, or resume if any is away.
- **Middle click:** resume the schedule.
- **Scroll:** setpoint ±1°.

Settings, on the widget's entry in `~/.config/omarchy/shell.json`:

| Setting | Effect |
|---|---|
| `"thermostat": "upstairs"` | Show and control only this thermostat |
| `"house": "cabin"` | Only this house's thermostats |
| `"pairingDemo": true` | "Add thermostat" pairs with a pretend thermostat; nothing is saved |

From scripts or keybindings:
- `omarchy-shell thermoslop open` opens the panel.
- `omarchy-shell thermoslop add` opens it on the pairing view.
- `omarchy-shell thermoslop pair <device id>` starts pairing with that device.

## License

MIT; see LICENSE.
