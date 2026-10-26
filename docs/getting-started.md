# Getting started

You need a HomeKit-capable ecobee on a network this machine can reach, and
Linux or macOS.

## 1. Install

```bash
uv tool install --managed-python thermoslop    # or: pipx install thermoslop
```

`--managed-python` makes uv use its own Python for your CPU. On an Apple
Silicon Mac with an old Intel Homebrew, uv otherwise picks an x86_64 Python and
building `cryptography` fails.

## 2. Start the watcher

```bash
thermoslop setup
```

This installs the background services: systemd user units on Linux, launchd
agents on macOS. The **watcher** starts now and keeps the bar's readings fresh;
the **MCP HTTP server** is installed but left off. On Omarchy, `setup` also
offers to add the bar widget. Without systemd (Alpine, Void, containers) it
tells you the command to run under your own service manager.

## 3. Find your thermostat

```bash
thermoslop discover
```

```text
Main Floor  ecobee3 lite  192.0.2.40:51826  ready to pair
```

Each thermostat shows as **ready to pair**, **paired here**, or **paired
elsewhere**. A thermostat pairs with **one** HomeKit controller at a time, so
one that's in Apple Home shows as paired elsewhere: remove it from the Home
app first (or reset HomeKit on the thermostat).

Nothing found? See [Networking and discovery](networking.md).

## 4. Pair it

```bash
thermoslop pair 'Main Floor'
```

It starts pairing, then asks for the code on the thermostat's screen under
**Menu → Settings → HomeKit**. ecobee shows a **new code once pairing starts**,
so read it when asked, not before. If two devices share a name (a "Main
Floor" in each house), pair by the device id that `discover --json` shows.

To try this without touching anything: `thermoslop discover --demo`, then
`thermoslop pair Basement --demo` with code `314-15-926`.

## 5. Use it

```bash
thermoslop status
thermoslop set 68
thermoslop mode heat
thermoslop away
thermoslop resume
```

With several thermostats, pick one with `-t upstairs`, or set
`default = "upstairs"` in the [configuration](configuration.md).
`thermoslop --help` lists every command; `thermoslop help set` explains one.
Tab completion:

```bash
eval "$(thermoslop completion bash)"   # in ~/.bashrc
eval "$(thermoslop completion zsh)"    # in ~/.zshrc
thermoslop completion fish > ~/.config/fish/completions/thermoslop.fish
```

## Uninstalling

```bash
thermoslop setup --remove                   # stop and remove the services
uv tool uninstall thermoslop                # or: pipx uninstall thermoslop
omarchy plugin remove martellj.thermoslop   # on Omarchy
```

Your pairings, config and history stay in `~/.config/thermoslop`,
`~/.local/share/thermoslop` and `~/.local/state/thermoslop` until you delete
them. Delete `pairing.json` only after unpairing, or reset HomeKit on the
thermostat to free it.
