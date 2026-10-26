# ThermoSlop

![ThermoSlop](assets/logo.svg){ width="360" }

Your thermostats in the terminal, the status bar, and your AI agents' hands.
ThermoSlop controls ecobee thermostats **locally over HomeKit**: no cloud, no
ecobee developer key, and it keeps working while the internet is down.

- **`thermoslop`**, a CLI for the terminal, scripts and AI tools
- **an MCP server** with guardrails, for Claude and other AI clients, on this
  machine or across your tailnet
- **an Omarchy bar widget**, plus output for Waybar, polybar, i3blocks and
  SwiftBar
- **a change log** of every change and who made it, including changes at the
  thermostat or in the ecobee app

```text
$ thermoslop status
Main Floor: 69.8°F · ▲ heating · set 68°F (heat) · home · 42% RH
    Bedroom: 67.1°F, occupied
Upstairs: 71.2°F · idle · set 67°F–75°F (auto) · home · 40% RH
```

![The Omarchy panel, with pretend thermostats](assets/panel.png){ width="360" }

!!! warning "Unofficial"
    ThermoSlop is an independent project. It is not affiliated with, endorsed
    by, or supported by ecobee Inc. or Apple Inc. It talks to your thermostat
    over the local HomeKit protocol. Use it at your own risk.

**Start here:** [Getting started](getting-started.md) ·
[CLI reference](reference/control.md) ·
[MCP server](mcp.md) ·
[Something not showing up?](networking.md)
