# macOS

- **Supported:** the CLI, the watcher (`thermoslop setup` installs launchd
  agents), and the MCP server; Claude Desktop and Claude Code can use it locally
  over stdio.
- **Not supported:** the Omarchy bar widget. For the menu bar, use
  [SwiftBar](status-bars.md#swiftbar-macos).

Install with `uv tool install --managed-python thermoslop`: on an Apple Silicon
Mac with an old Intel Homebrew, uv otherwise picks an x86_64 Python and building
`cryptography` fails.

## One controller per thermostat

A thermostat pairs with **one** HomeKit controller. If it's in the Apple Home
app, the Mac can't also pair it with ThermoSlop. Two setups work:

1. **ThermoSlop is the controller:** remove the thermostat from Apple Home (or
   reset HomeKit on it) and pair it with `thermoslop pair`. Siri and the Home
   app no longer see it.
2. **The Mac is a client of another ThermoSlop machine** (a Linux box that
   holds the pairings): run `thermoslop mcp --http` there (see
   [MCP over the tailnet](mcp.md#from-other-machines-on-your-tailnet)) and point
   Claude on the Mac at it. Nothing is paired on the Mac.

If both machines are yours and on Tailscale, option 2 keeps one source of truth
for pairings and the change log.

## Local Network permission

macOS asks before a process can use the local network, and the launchd watcher
has no window to ask from. Discovery from Terminal works once Terminal is
allowed. If the watcher on a Mac that holds pairings logs `No route to host`
for your LAN, allow it under **System Settings → Privacy & Security → Local
Network**. It needs the LAN only to find a thermostat again after its address
changes.

Logs are in `~/Library/Logs/thermoslop/`.
