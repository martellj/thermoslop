# Security

ThermoSlop controls real heating and cooling equipment, so security reports are
welcome and taken seriously.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting**: the repository's
*Security* tab → *Report a vulnerability*. Don't open a public issue for
anything exploitable. Expect an acknowledgement within a week.

## What's sensitive on your machine

| File | Why it matters |
|---|---|
| `~/.local/share/thermoslop/pairing.json` | The controller's long-term HomeKit key. Anyone with this file and network access to the thermostat has **full control of it**. It's written mode 600 in a 700 directory. Back it up like an SSH key, and never commit or share it. |
| `~/.local/state/thermoslop/changes.jsonl` | Change log of every thermostat change, including tailnet logins and device names of MCP callers (mode 600). |
| `~/.config/thermoslop/config.toml` | Your subnets, houses and MCP allow-list (directory mode 700). |

`~/.cache/thermoslop/state.json` holds the latest readings and the trend
history. That reveals occupancy, when you're away, and the household's
temperature over time, so it's mode 600 in a 700 directory too. The bar widget
runs as you and needs no wider access.

**Revoking access:** if `pairing.json` leaks, reset HomeKit on the thermostat
(on ecobee: Menu → Settings → HomeKit → Reset). That invalidates every
pairing. Then pair again with `thermoslop pair`.

## MCP server threat model

The MCP server lets AI agents change your thermostats, so its defaults are
conservative:

- **stdio by default.** Clients on the same machine launch it; there is no
  network listener.
- **HTTP is opt-in and tailnet-only.** `thermoslop mcp --http` listens only on
  the machine's Tailscale addresses, and refuses wildcard, LAN or public binds.
- **Callers are identified with `tailscale whois`** and checked against
  `[mcp] allow`, which defaults to the node's owner.
  - Entries are exact logins, or a device's stable node ID tied to its
    owner's login. Login prefixes and machine names are refused at start-up,
    because renaming a machine or registering a look-alike login could match
    them.
  - Unknown or unresolvable sources get 403, and failed lookups aren't
    cached.
  - A successful lookup is reused for up to 30 seconds. In that window, a
    device just removed from the tailnet, or a `tailscaled` that has just
    stopped, can still be served.
- **DNS-rebinding protection.** Requests must be addressed to the node's
  tailnet names, and requests with a browser `Origin` header are refused.
- **Guardrails on every change:**
  - setpoint range (55–80°F by default)
  - `off` requires an explicit `allow_off`
  - rate limit: 20 changes/hour, reserved before each change under a lock
    shared by every ThermoSlop process, so simultaneous calls can't
    overshoot it. A change whose outcome is unknown keeps counting.
  - `read_only` mode
- **What the limits don't cover:**
  - Comfort holds (home, away, sleep) and resuming the schedule switch to the
    thermostat's own preset temperatures, which can sit outside the setpoint
    range.
  - An agent that can also run shell commands can use the `thermoslop` CLI,
    which has no guardrails: the limits constrain the MCP interface, not
    everything the agent can do.
- **Everything is logged.** Every attempted change, refused ones included, is
  recorded with its caller and before/after values.
- **No pairing over MCP.** Agents can't pair, unpair or discover devices.

Out of scope: an attacker who already has your user account, or control of a
device that's on your tailnet and in your allow-list. Restrict port 8765 in
your Tailscale ACLs as well, for defence in depth.

## Not affiliated

ThermoSlop is unofficial and not affiliated with ecobee Inc. or Apple Inc.
Vulnerabilities in thermostat firmware or HomeKit itself belong with those
vendors.
