# Concepts

## Houses

A **house** is a named set of subnets in the [configuration](configuration.md).
A thermostat belongs to the house whose subnet holds its address, so one
controller can run several houses as long as it can route to each house's LAN
(for example over Tailscale subnet routes; see
[Networking](networking.md#reaching-another-house-over-tailscale)).

- `thermoslop status` groups thermostats under a heading per house.
- `--house cabin` limits a command to one house: `thermoslop away --house cabin`
  holds away on every cabin thermostat; `thermoslop discover --house cabin`
  scans only the cabin's subnets.
- When a name is taken (two "Main Floor"s), `pair` prefixes the alias with the
  house: `cabin-main-floor`.
- If the route to a house drops, its thermostats show as unreachable and keep
  running their own schedules.

## The watcher

`thermoslop watch` (installed by `thermoslop setup`) subscribes to HomeKit
events from every paired thermostat and keeps a **state file**
(`~/.cache/thermoslop/state.json`) up to date. The bar widget and
`thermoslop bar` read only that file, so they never poll the thermostats.

- It refreshes fully every `poll_interval` seconds between events, and records
  one temperature per thermostat every 5 minutes for the trend line, kept for
  `trend_hours`.
- It rewrites the file every few minutes even while it can't reach a
  thermostat. So the widget can tell **"can't reach the thermostats"** (the
  watcher is fine, the thermostats are out of reach, e.g. you're away) from
  **"watcher offline"** (the file is old: the watcher stopped).
- If a thermostat's address or port changes, the next failed connection finds
  it again by device id and updates the pairing.
- It restarts itself when the pairing file changes, so a newly paired
  thermostat shows up on its own.

## Holds and the schedule

Changing a setpoint, from ThermoSlop or on the thermostat, creates a **hold**:
the thermostat keeps that value instead of following its schedule.
`thermoslop resume` clears it. `home`, `away` and `sleep` hold one of ecobee's
comfort settings, which use the thermostat's own preset temperatures.

## Confirmed changes

Every change returns once the thermostat reads back what was asked. If it
hasn't within 8 seconds, the command prints what it does read and exits
**2** ("sent but not confirmed"); 0 means confirmed. Changes to one thermostat
take turns across every ThermoSlop process (terminal, widget, MCP), so each
starts from a confirmed value.

## The change log

Every change is recorded in `~/.local/state/thermoslop/changes.jsonl` with the
time, the caller, the outcome, and the settings before and after.
`thermoslop log` shows it:

```text
$ thermoslop log
Oct 22 19:55:04  cli      set_temperature  by terminal (alice)
    upstairs: target 60→61, heat 60→61
Oct 22 19:58:40  external external_change  by thermostat, app or schedule
    upstairs: target 61→62, heat 61→62
```

| Source | Where the change came from |
|---|---|
| `mcp` | An AI client through `thermoslop mcp` (the local client, or `login on node` over the tailnet) |
| `cli` | `thermoslop` in a terminal or script |
| `widget` | The bar widget's panel, scroll or clicks |
| `external` | Not ThermoSlop: the thermostat's screen, the ecobee app, or its schedule |

`external` entries come from the watcher, which compares each thermostat's
settings on every update. A change counts as ThermoSlop's only if a ThermoSlop
entry for that thermostat, from about a minute before to 20 seconds after,
explains the new values. HomeKit doesn't say who made a change, so the screen,
the app and the schedule all show as `external`. Changes made while the watcher
was stopped are logged when it starts again. This is a heuristic for your own
records, not forensic proof.
