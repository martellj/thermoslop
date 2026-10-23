"""Pretend thermostats for previewing discovery and pairing (`--demo`).

Nothing touches the network, nothing is paired, and nothing is written:
pairing.json, the state cache and the change log are left alone. The panel's
"Add thermostat" view uses this when the widget's `pairingDemo` setting is on.

The demo "Basement" thermostat shows DEMO_CODE once pairing starts, the way a
real ecobee shows a fresh code. Any other code is rejected, so the error path
can be tried too.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from aiohomekit.model.categories import Categories

from thermoslop.discovery import Device, choose
from thermoslop.homekit import ThermoSlopError, format_pin, slugify

DEMO_CODE = "314-15-926"
READY = Device("Basement", "AA:BB:CC:00:00:01", "ecobee3 lite", "192.0.2.10", 51826,
               status_flags=1, category=Categories.THERMOSTAT)
ELSEWHERE = Device("Garage", "AA:BB:CC:00:00:02", "ecobee Premium", "192.0.2.11", 51826,
                   status_flags=0, category=Categories.THERMOSTAT)
STEP = 1.5  # seconds: how long pretend pair-setup steps take


def devices() -> list[Device]:
    return [READY, ELSEWHERE]


async def pair(name: str, alias: str | None, get_pin: Callable[[], Awaitable[str]], on_code_needed) -> dict:
    """Walk through pairing with the pretend thermostat; returns its state."""
    device = choose(devices(), name)
    if device.paired:
        raise ThermoSlopError(f"{device.name} is already paired with another controller (Apple Home?). Remove it there first.")
    await asyncio.sleep(STEP)  # pair-setup starts; the thermostat shows a fresh code
    on_code_needed(device, f"demo: {device.name}'s screen shows {DEMO_CODE}")
    pin = format_pin(await get_pin())
    await asyncio.sleep(STEP)
    if pin != DEMO_CODE:
        raise ThermoSlopError(f"{device.name} rejected the HomeKit code {pin}; check the digits and try again")
    alias = alias or slugify(device.name)
    return {
        "alias": alias, "name": device.name, "house": None, "available": True, "units": "F",
        "temperature": 64.4, "humidity": 48, "mode": "heat", "action": "idle", "target": 62,
        "heat_setpoint": 62, "cool_setpoint": 75, "comfort": "home", "sensors": [],
        "updated_at": time.time(), "demo": True,
    }
