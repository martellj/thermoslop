# Configuration

`~/.config/thermoslop/config.toml` (every setting is optional):

```toml
default = "main-floor"         # thermostat for commands without -t
units = "F"                    # override each thermostat's display units
poll_interval = 60             # the watcher's full refresh, between events (s)
trend_hours = 24               # the widget's trend window, up to 168; 0 = off
subnets = ["203.0.113.0/24"]   # extra subnets to scan by unicast (see Networking)

[houses]                       # optional; their subnets are scanned too
home = ["192.0.2.0/24"]
cabin = ["198.51.100.0/24"]

[mcp]                          # see the MCP page
read_only = false
min_setpoint = "55F"
max_setpoint = "80F"
```

The [MCP guardrails](mcp.md#guardrails) and the
[tailnet allow-list](mcp.md#from-other-machines-on-your-tailnet) are under
`[mcp]`.

## Files

| Path | Contents |
|---|---|
| `~/.config/thermoslop/config.toml` | This file |
| `~/.local/share/thermoslop/pairing.json` | HomeKit pairing keys. Treat it like an SSH key (see [Security](security.md)) |
| `~/.local/share/thermoslop/charmap.json` | The accessory cache |
| `~/.cache/thermoslop/state.json` | Latest readings and the trend, written by the watcher. It reveals occupancy, so it's private too |
| `~/.local/state/thermoslop/changes.jsonl` | The [change log](concepts.md#the-change-log) |

Files are mode 600 in 700 directories. The `XDG_CONFIG_HOME`,
`XDG_DATA_HOME`, `XDG_CACHE_HOME` and `XDG_STATE_HOME` variables move them.

## Environment

| Variable | Effect |
|---|---|
| `THERMOSLOP_PLAIN=1` | Words instead of symbols in output, like `--plain` (screen readers) |
| `THERMOSLOP_SOURCE` | Who a change is logged as (`cli`, `widget`, `mcp`); the bar widget sets `widget` |
