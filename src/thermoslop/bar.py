"""`thermoslop bar`: the thermostats for any status bar.

Reads only the watcher's state file (no network), so bars can run it often:

  --format text      one line (i3blocks, polybar, tmux)
  --format waybar    JSON: text, tooltip, class (Waybar `return-type: json`)
  --format swiftbar  title + dropdown with actions (SwiftBar/xbar on macOS)

`--follow` prints again whenever the state changes, for Waybar's continuous
`exec` mode. The icon and staleness rules match the Omarchy widget.
"""

from __future__ import annotations

import json
import sys
import time

from thermoslop.homekit import STATE_FILE, read_cache, slugify

STALE_SECONDS = 600  # same as the widget: older readings mean the watcher stopped
GLYPHS = {"heating": "󰈸", "cooling": "󰜗", "away": "󰜷", "idle": "󰔏", "stale": "󰔏", "empty": "󰔏"}
SF_SYMBOLS = {"heating": "flame", "cooling": "snowflake", "away": "figure.walk", "idle": "thermometer.medium",
              "stale": "thermometer.medium.slash", "empty": "thermometer.medium.slash"}


def select(cache: dict, thermostat: str | None = None, house: str | None = None) -> list[dict]:
    states = sorted(cache.get("thermostats", {}).values(), key=lambda s: (s.get("house") or "", s["alias"]))
    if house:
        states = [s for s in states if s.get("house") == house]
    if thermostat:
        key = slugify(thermostat)
        states = [s for s in states if s["alias"] == key] or [s for s in states if s["alias"].startswith(key)]
    return states


def live(states: list[dict], now: float) -> list[dict]:
    return [s for s in states if s.get("available") and now - s.get("updated_at", 0) < STALE_SECONDS]


def condition(states: list[dict], now: float) -> str:
    """heating, cooling, away, idle, stale (no fresh readings) or empty (nothing at all)."""
    if not states:
        return "empty"
    fresh = live(states, now)
    if not fresh:
        return "stale"
    if any(s.get("action") == "heating" for s in fresh):
        return "heating"
    if any(s.get("action") == "cooling" for s in fresh):
        return "cooling"
    if all(s.get("comfort") == "away" for s in fresh):
        return "away"
    return "idle"


def _deg(value) -> str:
    return "?" if value is None else f"{round(value)}°"


def temperatures(states: list[dict]) -> str:
    """68° 71° │ 55°: grouped by house."""
    groups: dict[str, list[str]] = {}
    for s in states:
        groups.setdefault(s.get("house") or "", []).append(_deg(s.get("temperature")) if s.get("available") else "?")
    return " │ ".join(" ".join(g) for g in groups.values())


def describe(s: dict) -> str:
    if not s.get("available"):
        return f"{s.get('name', s['alias'])}: unavailable"
    u = s.get("units", "F")
    if s.get("mode") == "auto":
        setpoint = f"{_deg(s.get('heat_setpoint'))}–{_deg(s.get('cool_setpoint'))}"
    else:
        setpoint = _deg(s.get("target")) if s.get("target") is not None else "—"
    parts = [f"{s['name']} {s['temperature']:.1f}°{u}", s.get("action", "?"), f"set {setpoint} ({s.get('mode')})"]
    if s.get("comfort"):
        parts.append(s["comfort"])
    return " · ".join(parts)


def text(states: list[dict], now: float) -> str:
    cond = condition(states, now)
    if cond == "empty":
        return ""
    return f"{GLYPHS[cond]} {temperatures(states)}" + (" (stale)" if cond == "stale" else "")


EMPTY = "No thermostat data. Is the watcher running? Try: thermoslop setup"
NO_MATCH = "No thermostats match that thermostat/house filter"
WATCHER_OFFLINE = "Readings are over 10 minutes old: the watcher looks offline (thermoslop setup)"
UNREACHABLE = "The watcher can't reach these thermostats; it keeps retrying"


def watcher_live(cache: dict, now: float) -> bool:
    """The watcher rewrites the file every few minutes even while it can't reach a thermostat."""
    return now - cache.get("updated_at", 0) < STALE_SECONDS


def stale_reason(watcher: bool) -> str:
    return UNREACHABLE if watcher else WATCHER_OFFLINE


def waybar(states: list[dict], now: float, filtered: bool = False, watcher: bool = False) -> str:
    cond = condition(states, now)
    if cond == "empty":
        tooltip = NO_MATCH if filtered else EMPTY
    else:
        lines = [describe(s) for s in states]
        if cond == "stale":
            lines.append(stale_reason(watcher))
        tooltip = "\n".join(lines)
    return json.dumps({"text": text(states, now), "tooltip": tooltip, "class": [cond], "alt": cond}, ensure_ascii=False)


def swiftbar(states: list[dict], now: float, binary: str, filtered: bool = False, watcher: bool = False) -> str:
    cond = condition(states, now)

    def action(label: str, *args: str) -> str:
        params = " ".join(f"param{i}={a}" for i, a in enumerate(args, 1))
        path = f'"{binary}"' if " " in binary else binary
        return f"{label} | bash={path} {params} terminal=false refresh=true"

    title = temperatures(states) if states else "–"
    lines = [f"{title} | sfimage={SF_SYMBOLS[cond]}", "---"]
    if cond == "empty":
        lines.append(NO_MATCH if filtered else EMPTY)
    # Every action names one thermostat or one house: nothing spans houses.
    def house_actions(house: str | None, indent: str) -> list[str]:
        live_here = [x for x in states if x.get("house") == house and x.get("available")]
        if len(live_here) < 2:
            return []
        scope = ["--all", "--house", house] if house else ["--all"]
        where = f" at {house.title()}" if house else ""
        return [action(f"{indent}Away (all {len(live_here)}{where})", "away", *scope),
                action(f"{indent}Resume schedule (all {len(live_here)}{where})", "resume", *scope)]

    houses = len({s.get("house") for s in states}) > 1
    current = None
    for s in states:
        if houses and s.get("house") != current:
            current = s.get("house")
            lines.append(f"{(current or 'other').title()} | size=11 color=gray")
            lines += house_actions(current, "--") if current else []
        lines.append(describe(s))
        if s.get("available"):
            if s.get("mode") in ("heat", "cool", "auto"):
                lines.append(action("--Raise 1°", "set", "+1", "-t", s["alias"]))
                lines.append(action("--Lower 1°", "set", "-1", "-t", s["alias"]))
            lines.append(action("--Away", "away", "-t", s["alias"]))
            lines.append(action("--Resume schedule", "resume", "-t", s["alias"]))
    if states and not houses and (extra := house_actions(states[0].get("house"), "")):
        lines += ["---", *extra]
    if cond == "stale":
        lines.append(f"{stale_reason(watcher)} | color=red")
    lines += ["---", "Refresh | refresh=true"]
    return "\n".join(lines)


def render(fmt: str, states: list[dict], now: float, binary: str = "thermoslop", filtered: bool = False,
           watcher: bool = False) -> str:
    if fmt == "waybar":
        return waybar(states, now, filtered, watcher)
    if fmt == "swiftbar":
        return swiftbar(states, now, binary, filtered, watcher)
    return text(states, now)


def run(fmt: str, thermostat: str | None, house: str | None, follow: bool, binary: str) -> None:
    def emit() -> None:
        cache = read_cache()
        states = select(cache, thermostat, house)
        filtered = bool(cache.get("thermostats")) and not states
        now = time.time()
        out = render(fmt, states, now, binary, filtered, watcher_live(cache, now))
        print(out, flush=True)
        if not out and sys.stdout.isatty():  # bars hide an empty module; a person wants to know why
            print(NO_MATCH if filtered else EMPTY, file=sys.stderr)

    emit()
    if not follow:
        return
    seen, last = _mtime(), time.monotonic()
    while True:  # Ctrl-C (or the bar closing the pipe) ends it
        time.sleep(2)
        now_mtime = _mtime()
        if now_mtime != seen or time.monotonic() - last >= 60:  # also re-check staleness each minute
            seen, last = now_mtime, time.monotonic()
            try:
                emit()
            except BrokenPipeError:
                sys.exit(0)


def _mtime() -> float:
    try:
        return STATE_FILE.stat().st_mtime
    except FileNotFoundError:
        return 0.0
