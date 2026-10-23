"""thermoslop: command line for ecobee thermostats over local HomeKit (unofficial).

Every command takes --json for machine-readable output (scripts, AI tools).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time

from thermoslop import APP, __version__, audit, discovery, ops
from thermoslop.config import CONFIG_FILE, PAIRING_FILE, load_config, migrate_legacy, secure_existing
from thermoslop.homekit import (
    COMFORT,
    HVAC_MODES,
    ThermoSlopError,
    Home,
    read_cache,
    slugify,
    write_cache,
)

ACTION_ARROW = {"heating": "▲ heating", "cooling": "▼ cooling", "idle": "idle", "off": "off"}


# ---- output ------------------------------------------------------------------


def _deg(value, units: str) -> str:
    if value is None:
        return "—"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text}°{units}"


def format_state(st: dict) -> str:
    if not st.get("available", True):
        return f"{st.get('name', st['alias'])}: unavailable ({st.get('error', 'unknown error')})"
    u = st["units"]
    if st["mode"] == "auto":
        setpoint = f"{_deg(st['heat_setpoint'], u)}–{_deg(st['cool_setpoint'], u)}"
    elif st["target"] is not None:
        setpoint = _deg(st["target"], u)
    else:
        setpoint = "—"
    parts = [
        f"{st['name']}: {_deg(st['temperature'], u)}",
        f"{ACTION_ARROW.get(st['action'], st['action'])}",
        f"set {setpoint} ({st['mode']})",
    ]
    if st.get("comfort"):
        parts.append(st["comfort"])
    if st.get("humidity") is not None:
        parts.append(f"{st['humidity']}% RH")
    lines = [" · ".join(parts)]
    for sensor in st.get("sensors", []):
        bits = [_deg(sensor["temperature"], u)] if sensor["temperature"] is not None else []
        if sensor["occupied"] is not None:
            bits.append("occupied" if sensor["occupied"] else "empty")
        lines.append(f"    {sensor['name']}: {', '.join(bits)}")
    return "\n".join(lines)


def format_states(states: list[dict]) -> str:
    """One block per thermostat, under a heading per house when there are several."""
    houses = list(dict.fromkeys(s.get("house") for s in states))
    if len(houses) < 2:
        return "\n".join(format_state(s) for s in states)
    blocks = []
    for house in houses:
        lines = [format_state(s) for s in states if s.get("house") == house]
        blocks.append(f"{(house or 'other').title()}\n" + "\n".join("  " + l.replace("\n", "\n  ") for l in lines))
    return "\n\n".join(blocks)


def emit(args, payload, text: str) -> None:
    print(json.dumps(payload, indent=1) if args.json else text)


# ---- change log --------------------------------------------------------------


def _source() -> tuple[str, str]:
    """(source, caller) for the change log: the bar widget sets THERMOSLOP_SOURCE."""
    if os.environ.get("THERMOSLOP_SOURCE") == "widget":
        return "widget", "bar widget"
    return "cli", f"terminal ({os.environ.get('USER', '?')})"


def _logged_args(args) -> dict:
    keys = ("temperature", "heat", "cool", "mode", "comfort", "thermostat", "house", "all", "device", "alias")
    return {k: getattr(args, k) for k in keys if getattr(args, k, None) not in (None, False)}


async def logged(args, tool: str, change, thermostats: list[str] = ()):
    """Run a change from the CLI or widget and record it in the change log.

    `thermostats` names the target when it's known up front, so a failure is
    logged against it.
    """
    source, caller = _source()
    before = {alias: audit.snapshot(s) for alias, s in read_cache().get("thermostats", {}).items()}
    try:
        result = await change()
    except ThermoSlopError as e:
        audit.record(source, tool, _logged_args(args), caller, "failed", thermostats, error=str(e))
        raise
    states = result if isinstance(result, list) else [result]
    aliases = [s["alias"] for s in states if "alias" in s]
    after = {s["alias"]: audit.snapshot(s) for s in states if "mode" in s}
    outcome = "unconfirmed" if any(s.get("confirmed") is False for s in states) else "ok"
    audit.record(source, tool, _logged_args(args), caller, outcome, aliases,
                 {a: before.get(a) for a in aliases}, after or None)
    return result


def unconfirmed(states: list[dict]) -> int:
    """Warn about changes the thermostat didn't confirm; the exit code to use (2 or 0)."""
    missed = [s for s in states if s.get("confirmed") is False]
    for s in missed:
        print(f"{APP}: {s['alias']}: sent, but it still reads: {format_state(s)}", file=sys.stderr)
    return 2 if missed else 0


# ---- commands ----------------------------------------------------------------


def _paired_here() -> dict[str, str]:
    """Device id (lower case) -> alias, for thermostats paired with this machine."""
    try:
        pairings = json.loads(PAIRING_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {p.get("AccessoryPairingID", "").lower(): alias for alias, p in pairings.items()}


def _discovered(d, here: dict[str, str]) -> dict:
    alias = here.get(d.id.lower())
    status = "paired here" if alias else "paired elsewhere" if d.paired else "ready to pair"
    return {**d.to_dict(), "status": status, "alias": alias}


async def cmd_discover(args, config) -> int:
    subnets = args.subnet or config.subnets
    if args.demo:
        from thermoslop import demo

        devices = demo.devices()
    else:
        devices = await discovery.discover(subnets, timeout=args.timeout)
    if not args.all:
        devices = [d for d in devices if d.is_thermostat]
    here = _paired_here()
    found = [_discovered(d, here) for d in devices]
    if args.demo:
        # Show your real pairings too, so the list looks like it would.
        listed = {f["alias"] for f in found if f["alias"]}
        cached = read_cache().get("thermostats", {})
        found += [{"name": cached.get(a, {}).get("name", a), "id": "", "model": "", "address": "", "port": 0,
                   "status": "paired here", "alias": a, "paired": True, "thermostat": True}
                  for a in sorted(set(here.values()) - listed)]
    rows = [(f["name"], f["model"], f"{f['address']}:{f['port']}" if f["address"] else "",
             f"paired here as {f['alias']!r}" if f["alias"] else f["status"]) for f in found]
    widths = [max((len(r[i]) for r in rows), default=0) for i in range(3)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r[:3], widths)) + "  " + r[3] for r in rows]
    if not found:
        hint = "" if subnets else f" (behind NAT? set `subnets` in {CONFIG_FILE} or pass --subnet)"
        lines = [f"no HomeKit thermostats found{hint}"]
    emit(args, found, "\n".join(lines))
    return 0


async def read_line() -> str:
    """One line of stdin, without blocking shutdown.

    asyncio.to_thread would put the read on the default executor, and
    asyncio.run waits for that on exit: Ctrl-C at the code prompt then hung until
    stdin closed. A daemon thread is simply abandoned.
    """
    loop = asyncio.get_running_loop()
    line = loop.create_future()

    def read() -> None:
        text = sys.stdin.readline()
        try:
            loop.call_soon_threadsafe(lambda: line.done() or line.set_result(text))
        except RuntimeError:
            pass  # the loop is gone: we were interrupted

    threading.Thread(target=read, daemon=True).start()
    return (await line).strip()


def _code_needed(args, device, hint: str = "") -> None:
    """Tell the person (or, with --json, the panel) that the code is wanted now."""
    if args.json:
        event = {"event": "code_needed", "device": device.name, "hint": hint}
        print(json.dumps(event), file=sys.stderr, flush=True)
        return
    if hint:
        print(f"({hint})", file=sys.stderr)
    print(f"Pairing started. Enter the HomeKit code {device.name} shows now", file=sys.stderr)
    print("(it may have just changed; check the screen, Menu → Settings → HomeKit).", file=sys.stderr)
    # Piped input doesn't echo a newline, so end the prompt line ourselves.
    print("HomeKit code: ", end="" if sys.stdin.isatty() else "\n", file=sys.stderr, flush=True)


async def cmd_pair(args, config) -> int:
    async def read_pin() -> str:
        return args.pin or await read_line()

    if args.demo:
        from thermoslop import demo

        state = await demo.pair(args.device, args.alias, read_pin, lambda d, hint: _code_needed(args, d, hint))
        emit(args, state, f"Paired {state['name']} as {state['alias']!r} (demo: nothing was saved).\n{format_state(state)}")
        return 0

    devices = await discovery.discover(args.subnet or config.subnets)
    device = discovery.choose(devices, args.device)
    if alias := _paired_here().get(device.id.lower()):
        raise ThermoSlopError(f"{device.name} is already paired with this machine, as {alias!r}")
    if device.paired:
        raise ThermoSlopError(
            f"{device.name} is already paired with another controller (Apple Home?). Remove it there first."
        )
    async def get_pin() -> str:
        if not args.pin:
            _code_needed(args, device)
        return await read_pin()

    async with Home(config) as home:
        alias = args.alias or slugify(device.name)
        if not args.alias and alias in home.aliases() and (house := config.house_of(device.address)):
            alias = f"{house}-{alias}"  # e.g. a second house's "Main Floor"
        async def pair() -> dict:
            await home.pair(device, alias, get_pin)
            return await home.state(alias)

        state = await logged(args, "pair", pair)
    write_cache([state])
    emit(args, state, f"Paired {device.name} as {alias!r}.\n{format_state(state)}")
    return 0


async def cmd_unpair(args, config) -> int:
    async with Home(config) as home:
        (alias,) = home.pick(args.thermostat, args.house, single=True)

        async def unpair() -> dict:
            await home.unpair(alias)
            return {"alias": alias}

        await logged(args, "unpair", unpair)
    emit(args, {"unpaired": alias}, f"Unpaired {alias}.")
    return 0


async def cmd_status(args, config) -> int:
    async with Home(config) as home:
        states = await ops.status(home, args.thermostat, args.house, live=args.live)
    emit(args, states, format_states(states))
    return 0 if all(s["available"] for s in states) else 1


def _parse_temp(text: str) -> tuple[float, bool]:
    """'70' -> (70, absolute); '+1' / '-1.5' -> (delta, relative)."""
    try:
        return float(text), text[0] in "+-"
    except ValueError:
        raise ThermoSlopError(f"not a temperature: {text!r}") from None


async def cmd_set(args, config) -> int:
    value, relative = _parse_temp(args.temperature) if args.temperature else (None, False)
    async with Home(config) as home:
        state = await logged(args, "set_temperature", lambda: ops.set_temperature(
            home, args.thermostat, args.house, value, relative=relative, heat=args.heat, cool=args.cool
        ))
    emit(args, state, format_state(state))
    return unconfirmed([state])


async def cmd_mode(args, config) -> int:
    async with Home(config) as home:
        state = await logged(args, "set_mode", lambda: ops.set_mode(home, args.mode, args.thermostat, args.house))
    emit(args, state, format_state(state))
    return unconfirmed([state])


async def _each(args, tool: str, home: Home, change) -> int:
    """Apply `change(alias)` to every selected thermostat, even if one fails.

    Each is logged on its own. Output lists a state per success and
    {"alias", "error"} per failure; exit 1 if any failed, 2 if any is unconfirmed.
    """
    results, failed = [], False
    for alias in ops.targets(home, args.thermostat, args.house, args.all):
        try:
            results.append(await logged(args, tool, lambda: change(alias), [alias]))
        except ThermoSlopError as e:
            results.append({"alias": alias, "error": str(e)})
            failed = True
    states = [r for r in results if "error" not in r]
    text = "\n".join([format_states(states)] * bool(states) + [f"{r['alias']}: {r['error']}" for r in results if "error" in r])
    emit(args, results, text)
    return 1 if failed else unconfirmed(states)


async def cmd_comfort(args, config) -> int:
    async with Home(config) as home:
        return await _each(args, "set_comfort", home, lambda alias: home.set_comfort(alias, args.comfort))


async def cmd_resume(args, config) -> int:
    async with Home(config) as home:
        return await _each(args, "resume_schedule", home, home.resume)


FIELD_NAMES = {"target": "target", "heat_setpoint": "heat", "cool_setpoint": "cool", "mode": "mode", "comfort": "comfort"}


def _changes(before: dict | None, after: dict | None) -> str:
    """'target 60→61, comfort hold→away' for one thermostat."""
    if not after:
        return ""
    before = before or {}
    parts = []
    for key, label in FIELD_NAMES.items():
        old, new = before.get(key), after.get(key)
        if old != new:
            parts.append(f"{label} {_fmt(old)}→{_fmt(new)}")
    return ", ".join(parts) or "no change"


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return "—" if value is None else str(value)


def format_entry(e: dict) -> list[str]:
    when = time.strftime("%b %d %H:%M:%S", time.localtime(e.get("time", 0)))
    outcome = "" if e.get("outcome") == "ok" else f" [{e.get('outcome')}]"
    head = f"{when}  {e['source']:<8} {e.get('tool', '?')}{outcome}  by {e.get('caller', '?')}"
    lines = [head]
    for alias in e.get("thermostats") or []:
        detail = _changes((e.get("before") or {}).get(alias), (e.get("after") or {}).get(alias))
        lines.append(f"    {alias}: {detail}" if detail else f"    {alias}")
    if e.get("error"):
        lines.append(f"    {e['error']}")
    return lines


async def cmd_log(args, config) -> int:
    found = audit.entries(since=time.time() - args.hours * 3600)
    if args.thermostat:
        key = slugify(args.thermostat)
        found = [e for e in found if any(a.startswith(key) for a in e.get("thermostats", []))]
    if args.source:
        found = [e for e in found if e["source"] == args.source]
    found = found[-args.limit:]
    lines = [line for e in found for line in format_entry(e)] or [f"no changes in the last {args.hours:g} hours"]
    emit(args, found, "\n".join(lines))
    return 0


async def cmd_watch(args, config) -> int:
    from thermoslop.daemon import watch

    async with Home(config) as home:
        await watch(home)
    return 0


async def cmd_mcp(args, config) -> int:
    from thermoslop import mcp_server

    if args.http:
        await mcp_server.serve_http(config, read_only=args.read_only, bind=args.bind, port=args.port)
    else:
        await mcp_server.serve_stdio(config, read_only=args.read_only)
    return 0


async def cmd_bar(args, config) -> int:
    from thermoslop import bar
    from thermoslop.setup import executable

    bar.run(args.format, args.thermostat, args.house, args.follow, executable())
    return 0


async def cmd_setup(args, config) -> int:
    from thermoslop.setup import setup

    for line in setup(remove=args.remove, assume_yes=args.yes, plugin=not args.no_plugin):
        print(f"→ {line}")
    return 0


async def cmd_dump(args, config) -> int:
    async with Home(config) as home:
        (alias,) = home.pick(args.thermostat, args.house, single=True)
        accessories = await home.fetch(alias)
    print(json.dumps(accessories.serialize(), indent=1, default=str))
    return 0


# ---- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("-t", "--thermostat", help="thermostat name/alias (prefix ok)")
    common.add_argument("--house", help="only thermostats in this house (from [houses] in config)")
    common.add_argument("-v", "--verbose", action="count", default=0)

    p = argparse.ArgumentParser(prog=APP, description=__doc__, parents=[common])
    p.add_argument("--version", action="version", version=f"{APP} {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", parents=[common], help="current temperature, setpoints, sensors")
    s.add_argument("--live", action="store_true", help="skip the watch cache, ask the thermostat")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("set", parents=[common], help="set target temperature: 70, +1, -2, or --heat/--cool")
    s.add_argument("temperature", nargs="?", help="absolute (70) or relative (+1, -1)")
    s.add_argument("--heat", type=float, help="heat setpoint (auto mode)")
    s.add_argument("--cool", type=float, help="cool setpoint (auto mode)")
    s.set_defaults(func=cmd_set)

    s = sub.add_parser("mode", parents=[common], help="HVAC mode")
    s.add_argument("mode", choices=list(HVAC_MODES.values()))
    s.set_defaults(func=cmd_mode)

    for comfort in COMFORT.values():
        s = sub.add_parser(comfort, parents=[common], help=f"hold the {comfort} comfort setting")
        s.add_argument("--all", action="store_true", help="every paired thermostat (or every one in --house)")
        s.set_defaults(func=cmd_comfort, comfort=comfort)

    s = sub.add_parser("resume", parents=[common], help="clear holds and resume the schedule")
    s.add_argument("--all", action="store_true", help="every paired thermostat (or every one in --house)")
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("discover", parents=[common], help="find HomeKit thermostats on the network")
    s.add_argument("--subnet", action="append", help="also scan this subnet by unicast (repeatable)")
    s.add_argument("--timeout", type=float, default=3.0)
    s.add_argument("--all", action="store_true", help="show every HomeKit accessory, not just thermostats")
    s.add_argument("--demo", action="store_true", help="pretend thermostats, to preview pairing (no network)")
    s.set_defaults(func=cmd_discover)

    s = sub.add_parser("pair", parents=[common], help="pair with a thermostat using its HomeKit code")
    s.add_argument("device", help="device id, IP, or name from `thermoslop discover` (use the id if names repeat)")
    s.add_argument("--pin", help="HomeKit code XXX-XX-XXX (prompted if omitted)")
    s.add_argument("--alias", help="short name to use (default: slug of the device name)")
    s.add_argument("--subnet", action="append")
    s.add_argument("--demo", action="store_true", help="pair with a pretend thermostat; nothing is saved")
    s.set_defaults(func=cmd_pair)

    s = sub.add_parser("unpair", parents=[common], help="remove a pairing")
    s.set_defaults(func=cmd_unpair)

    s = sub.add_parser("watch", parents=[common], help="daemon: keep the bar widget's state fresh")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("mcp", parents=[common], help="MCP server for AI clients (stdio, or --http on the tailnet)")
    s.add_argument("--read-only", action="store_true", help="offer only the status tools")
    s.add_argument("--http", action="store_true", help="serve streamable HTTP on this machine's Tailscale address")
    s.add_argument("--bind", help="Tailscale address to listen on (default: `tailscale ip -4`)")
    s.add_argument("--port", type=int, help="port (default: [mcp] http_port, 8765)")
    s.set_defaults(func=cmd_mcp)

    s = sub.add_parser("log", parents=[common], help="recent changes, from any source (terminal, widget, MCP, thermostat/app)")
    s.add_argument("--hours", type=float, default=24, help="how far back (default 24)")
    s.add_argument("-n", "--limit", type=int, default=50, help="at most this many entries (newest)")
    s.add_argument("--source", choices=audit.SOURCES, help="only changes from this source")
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("bar", parents=[common], help="status-bar output from the watcher's state (Waybar, SwiftBar, i3blocks…)")
    s.add_argument("--format", choices=["text", "waybar", "swiftbar"], default="text")
    s.add_argument("--follow", action="store_true", help="print again whenever the state changes")
    s.set_defaults(func=cmd_bar)

    s = sub.add_parser("setup", parents=[common], help="install the background services (systemd or launchd)")
    s.add_argument("--remove", action="store_true", help="stop and remove them (keeps pairings and history)")
    s.add_argument("--yes", action="store_true", help="don't ask; also adds the Omarchy plugin when on Omarchy")
    s.add_argument("--no-plugin", action="store_true", help="don't offer the Omarchy plugin")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("dump", parents=[common], help="raw HomeKit accessory data (debugging)")
    s.set_defaults(func=cmd_dump)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.verbose > 1 else logging.INFO if args.verbose or args.command == "watch" else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    migrate_legacy()
    secure_existing()
    try:
        config = load_config()
    except ValueError as e:
        print(f"{APP}: {CONFIG_FILE}: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        code = asyncio.run(args.func(args, config))
    except ThermoSlopError as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"{APP}: {e}", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
