"""ecobee: command line for ecobee thermostats over local HomeKit.

Every command takes --json for machine-readable output (scripts, AI tools).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ecobee import discovery, ops
from ecobee.config import CONFIG_FILE, load_config
from ecobee.homekit import (
    COMFORT,
    HVAC_MODES,
    EcobeeError,
    Home,
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


# ---- commands ----------------------------------------------------------------


async def cmd_discover(args, config) -> int:
    subnets = args.subnet or config.subnets
    devices = await discovery.discover(subnets, timeout=args.timeout)
    if not args.all:
        devices = [d for d in devices if d.is_thermostat]
    lines = [
        f"{d.name:<20} {d.model:<16} {d.address}:{d.port}  id={d.id}  {'paired elsewhere' if d.paired else 'ready to pair'}"
        for d in devices
    ]
    if not devices:
        hint = "" if subnets else f" (behind NAT? set `subnets` in {CONFIG_FILE} or pass --subnet)"
        lines = [f"no HomeKit thermostats found{hint}"]
    emit(args, [d.to_dict() for d in devices], "\n".join(lines))
    return 0


async def cmd_pair(args, config) -> int:
    devices = await discovery.discover(args.subnet or config.subnets)
    want = args.device.lower()
    matches = [d for d in devices if want in (d.id, d.address) or slugify(d.name) == slugify(args.device)]
    if not matches:
        raise EcobeeError(f"no device named {args.device!r} found; run `ecobee discover`")
    device = matches[0]
    if device.paired:
        raise EcobeeError(
            f"{device.name} is already paired with another controller (Apple Home?). Remove it there first."
        )
    async def get_pin() -> str:
        if args.pin:
            return args.pin
        print(f"Pairing started. Enter the HomeKit code {device.name} shows now", file=sys.stderr)
        print("(it may have just changed; check the screen, Menu → Settings → HomeKit).", file=sys.stderr)
        print("HomeKit code: ", end="", file=sys.stderr, flush=True)
        return (await asyncio.to_thread(sys.stdin.readline)).strip()

    async with Home(config) as home:
        alias = args.alias or slugify(device.name)
        if not args.alias and alias in home.aliases() and (house := config.house_of(device.address)):
            alias = f"{house}-{alias}"  # e.g. a second house's "Main Floor"
        await home.pair(device, alias, get_pin)
        state = await home.state(alias)
    write_cache([state])
    emit(args, state, f"Paired {device.name} as {alias!r}.\n{format_state(state)}")
    return 0


async def cmd_unpair(args, config) -> int:
    async with Home(config) as home:
        (alias,) = home.pick(args.thermostat, args.house, single=True)
        await home.unpair(alias)
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
        raise EcobeeError(f"not a temperature: {text!r}") from None


async def cmd_set(args, config) -> int:
    value, relative = _parse_temp(args.temperature) if args.temperature else (None, False)
    async with Home(config) as home:
        state = await ops.set_temperature(
            home, args.thermostat, args.house, value, relative=relative, heat=args.heat, cool=args.cool
        )
    emit(args, state, format_state(state))
    return 0


async def cmd_mode(args, config) -> int:
    async with Home(config) as home:
        state = await ops.set_mode(home, args.mode, args.thermostat, args.house)
    emit(args, state, format_state(state))
    return 0


async def cmd_comfort(args, config) -> int:
    async with Home(config) as home:
        states = await ops.set_comfort(home, args.comfort, args.thermostat, args.house, all=args.all)
    emit(args, states, format_states(states))
    return 0


async def cmd_resume(args, config) -> int:
    async with Home(config) as home:
        states = await ops.resume(home, args.thermostat, args.house, all=args.all)
    emit(args, states, format_states(states))
    return 0


async def cmd_watch(args, config) -> int:
    from ecobee.daemon import watch

    async with Home(config) as home:
        await watch(home)
    return 0


async def cmd_mcp(args, config) -> int:
    from ecobee import mcp_server

    await mcp_server.serve_stdio(config, read_only=args.read_only)
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

    p = argparse.ArgumentParser(prog="ecobee", description=__doc__, parents=[common])
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
    s.set_defaults(func=cmd_discover)

    s = sub.add_parser("pair", parents=[common], help="pair with a thermostat using its HomeKit code")
    s.add_argument("device", help="name, IP, or device id from `ecobee discover`")
    s.add_argument("--pin", help="HomeKit code XXX-XX-XXX (prompted if omitted)")
    s.add_argument("--alias", help="short name to use (default: slug of the device name)")
    s.add_argument("--subnet", action="append")
    s.set_defaults(func=cmd_pair)

    s = sub.add_parser("unpair", parents=[common], help="remove a pairing")
    s.set_defaults(func=cmd_unpair)

    s = sub.add_parser("watch", parents=[common], help="daemon: keep the bar widget's state fresh")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("mcp", parents=[common], help="MCP server for AI clients (stdio)")
    s.add_argument("--read-only", action="store_true", help="offer only the status tools")
    s.set_defaults(func=cmd_mcp)

    s = sub.add_parser("dump", parents=[common], help="raw HomeKit accessory data (debugging)")
    s.set_defaults(func=cmd_dump)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.verbose > 1 else logging.INFO if args.verbose or args.command == "watch" else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = load_config()
    except ValueError as e:
        print(f"ecobee: {CONFIG_FILE}: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        code = asyncio.run(args.func(args, config))
    except EcobeeError as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"ecobee: {e}", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
