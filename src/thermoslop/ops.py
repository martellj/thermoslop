"""Thermostat operations shared by the CLI and the MCP server.

Each takes an open `Home` plus a selection (thermostat alias/prefix, house) and
returns state dicts like `thermoslop status --json`, raising `ThermoSlopError` for
anything the caller should report. Formatting and guardrails live in the
callers.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from thermoslop.homekit import ThermoSlopError, Home, read_cache, unavailable_state, write_cache


def _fresh_cache(aliases: list[str], max_age: float) -> list[dict] | None:
    cached = read_cache().get("thermostats", {})
    states = [cached.get(a) for a in aliases]
    now = time.time()
    if all(s and s.get("available") and now - s.get("updated_at", 0) < max_age for s in states):
        return states
    return None


def list_thermostats(home: Home, house: str | None = None) -> list[dict]:
    cached = read_cache().get("thermostats", {})
    return [
        {
            "alias": alias,
            "name": cached.get(alias, {}).get("name", alias),
            "house": home.house(alias),
            "available": cached.get(alias, {}).get("available"),
        }
        for alias in home.pick(None, house)
    ]


async def status(home: Home, thermostat: str | None = None, house: str | None = None, live: bool = False) -> list[dict]:
    """Uses the watcher's cache when every reading is fresh, else asks the thermostats."""
    aliases = home.pick(thermostat, house)
    states = None if live else _fresh_cache(aliases, max(2 * home.config.poll_interval, 150))
    if states is None:
        states = []
        for alias in aliases:
            try:
                states.append(await home.state(alias))
            except ThermoSlopError as e:
                states.append(unavailable_state(alias, str(e), house=home.house(alias)))
        write_cache([s for s in states if s["available"]])
    return states


async def set_temperature(
    home: Home,
    thermostat: str | None = None,
    house: str | None = None,
    value: float | None = None,
    *,
    relative: bool = False,
    heat: float | None = None,
    cool: float | None = None,
    check: Callable[[dict, dict[str, float]], None] | None = None,
) -> dict:
    (alias,) = home.pick(thermostat, house, single=True)
    return await home.set_temperature(alias, value, relative=relative, heat=heat, cool=cool, check=check)


async def set_mode(home: Home, mode: str, thermostat: str | None = None, house: str | None = None) -> dict:
    (alias,) = home.pick(thermostat, house, single=True)
    return await home.set_mode(alias, mode)


def _targets(home: Home, thermostat: str | None, house: str | None, all: bool) -> list[str]:
    # A whole house is as explicit as --all: `away --house cabin` means every cabin thermostat.
    return home.pick(thermostat, house, single=not (all or house))


async def set_comfort(
    home: Home, comfort: str, thermostat: str | None = None, house: str | None = None, all: bool = False
) -> list[dict]:
    return [await home.set_comfort(alias, comfort) for alias in _targets(home, thermostat, house, all)]


async def resume(home: Home, thermostat: str | None = None, house: str | None = None, all: bool = False) -> list[dict]:
    return [await home.resume(alias) for alias in _targets(home, thermostat, house, all)]
