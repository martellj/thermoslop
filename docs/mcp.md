# MCP server for AI clients

`thermoslop mcp` serves the thermostats to AI clients over the
[Model Context Protocol](https://modelcontextprotocol.io).

| Tool | Does |
|---|---|
| `list_thermostats`, `get_status` | Read-only. The same JSON as `thermoslop status --json`. |
| `set_temperature` | An absolute setpoint (`target`, or `heat`/`cool` in auto mode). |
| `adjust_temperature` | A relative change, −5 to +5. |
| `set_mode` | heat, cool, auto (off only if allowed). |
| `set_comfort`, `resume_schedule` | One thermostat, or a whole `house`; reports each thermostat's result. |

Each tool takes `thermostat` (alias or prefix) and/or `house`. Pairing isn't
exposed.

## On this machine (stdio)

**Claude Code:**

```bash
claude mcp add --scope user thermoslop -- ~/.local/bin/thermoslop mcp
```

**Claude Desktop**, or any client with a JSON config:

```json
{ "mcpServers": { "thermoslop": { "command": "/home/you/.local/bin/thermoslop", "args": ["mcp"] } } }
```

## From other machines on your tailnet

`thermoslop mcp --http` serves MCP over streamable HTTP for clients on other machines
(a Mac, a laptop). Nothing is reachable from the LAN or the internet:

- It listens only on this machine's **Tailscale addresses**, and refuses
  `--bind 0.0.0.0` or any non-Tailscale address.
- Each request's source is looked up with `tailscale whois`, and answered only
  if the caller is in `[mcp] allow` (by default, this node's owner). Anyone else
  gets 403, and the refusal is logged. There are no tokens: the tailnet
  already vouches for the device.
- Requests must be addressed to this node's tailnet names, and requests with a
  browser `Origin` are refused, so a web page can't reach it by DNS rebinding.

Turn the service on (`thermoslop setup` installs it, off):

```bash
systemctl --user enable --now thermoslop-mcp                                              # Linux
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.martellj.thermoslop.mcp.plist   # macOS
```

```toml
[mcp]
http_port = 8765
allow = [
  "alice@example.com",                        # everyone signed in as this exact login
  "node:nAbC123DEF4CNTRL@bob@example.com",    # or one device, while bob owns it
]
```

A device's stable ID is `Node.StableID` in
`tailscale whois --json <its tailnet address>`. Machine names and login
prefixes aren't accepted: renaming a machine, or registering a look-alike
login, could otherwise get someone in.

On the other machine, point the client at this machine's MagicDNS name:

```bash
claude mcp add --scope user --transport http thermoslop http://myhost:8765/mcp
```

The change log records these callers as `login on node`.

## Guardrails

The CLI is unrestricted; changes through MCP are checked against `[mcp]`:

```toml
[mcp]
read_only = false            # true (or `thermoslop mcp --read-only`): only the read tools
min_setpoint = "55F"         # setpoints outside this range are refused ("13C" works too)
max_setpoint = "80F"
allow_off = false            # set_mode off is refused unless true
max_changes_per_hour = 20    # per thermostat changed; shared by all processes; survives restarts
units = "F"                  # unit for tool calls that don't set `unit`
```

- Temperatures an agent sends are in `[mcp] units` unless the call sets
  `unit: "C"` or `"F"`, and are converted to each thermostat's units before the
  limits are checked. Readings come back in each thermostat's units.
- Comfort holds and resuming use the thermostat's own presets, which the
  setpoint range doesn't cover. A house-wide change reports, logs and counts
  each thermostat separately.
- Refusals come back as tool errors that say why, so the agent can tell you
  instead of retrying. Every attempt, refusals included, goes to the
  [change log](concepts.md#the-change-log) with source `mcp`.

See [Security](security.md) for the threat model.
