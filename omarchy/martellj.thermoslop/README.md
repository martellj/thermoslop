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

## Install

```bash
uv tool install thermoslop      # the CLI, the watcher and the MCP server
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
