# Other status bars

`thermoslop bar` prints the thermostats for any status bar. It reads only the
watcher's state file and never contacts a thermostat, so it's cheap to run
often, and it takes `-t` and `--house`.

| Format | Output |
|---|---|
| `--format text` (default) | `󰔏 68° 71° │ 55°` |
| `--format waybar` | JSON: `text`, `tooltip`, and `class`: `heating`, `cooling`, `away`, `idle`, `stale` or `empty` |
| `--format swiftbar` | A title, and a dropdown with ±1°, away and resume for each thermostat (and each house) |

`--follow` prints again whenever the state changes, instead of polling. Run in
a terminal with nothing to show, it says why on stderr.

## Waybar (Hyprland, Sway)

In `~/.config/waybar/config.jsonc`:

```jsonc
"custom/thermoslop": {
  "exec": "thermoslop bar --format waybar --follow",
  "return-type": "json",
  "restart-interval": 30,
  "on-click": "notify-send ThermoSlop \"$(thermoslop status)\"",
  "on-click-right": "thermoslop away -t upstairs",
  "on-click-middle": "thermoslop resume -t upstairs",
  "on-scroll-up": "thermoslop set +1 -t upstairs",
  "on-scroll-down": "thermoslop set -1 -t upstairs"
}
```

```css
#custom-thermoslop.heating { color: #faa968; }
#custom-thermoslop.cooling { color: #6cb6d9; }
#custom-thermoslop.stale   { opacity: 0.5; }
```

## i3blocks and polybar

```ini
# i3blocks
[thermoslop]
command=thermoslop bar
interval=60

# polybar
[module/thermoslop]
type = custom/script
exec = thermoslop bar --follow
tail = true
```

## XFCE

Add a *Generic Monitor* panel item with the command `thermoslop bar` and a
period of 60 seconds.

## SwiftBar (macOS)

Save this as `thermoslop.30s.sh` in your SwiftBar plugin folder and make it
executable. SwiftBar runs plugins without your shell's PATH, so use the full
path:

```sh
#!/bin/bash
exec "$HOME/.local/bin/thermoslop" bar --format swiftbar
```

Get SwiftBar with `brew install --cask swiftbar`, or the signed app from
[its releases](https://github.com/swiftbar/SwiftBar/releases). On a notched
MacBook a full menu bar can hide new items behind the notch, and macOS 26 may
ask you to allow SwiftBar under System Settings → Menu Bar.
