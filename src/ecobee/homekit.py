"""Paired thermostats: connecting, reading plain state, and writing changes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from aiohomekit import Controller
from aiohomekit.characteristic_cache import CharacteristicCacheFile
from aiohomekit.controller import TransportType
from aiohomekit.controller.ip.discovery import IpDiscovery
from aiohomekit.exceptions import AuthenticationError, HomeKitException
from aiohomekit.model import Accessories, Accessory
from aiohomekit.model.characteristics import CharacteristicsTypes as CT
from aiohomekit.model.services import ServicesTypes as ST
from aiohomekit.zeroconf import ZeroconfServiceListener
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

from ecobee import discovery
from ecobee.config import CHARMAP_FILE, PAIRING_FILE, STATE_FILE, Config

log = logging.getLogger(__name__)

HVAC_MODES = {0: "off", 1: "heat", 2: "cool", 3: "auto"}
HVAC_ACTIONS = {0: "idle", 1: "heating", 2: "cooling"}
# ecobee's vendor characteristics number comfort settings this way.
COMFORT = {0: "home", 1: "sleep", 2: "away"}

CONNECT_ERRORS = (OSError, TimeoutError, asyncio.TimeoutError)


class EcobeeError(Exception):
    pass


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "thermostat"


# ---- units -----------------------------------------------------------------


def from_c(celsius: float | None, units: str) -> float | None:
    if celsius is None:
        return None
    return celsius * 9 / 5 + 32 if units == "F" else celsius


def to_c(value: float, units: str) -> float:
    return round((value - 32) * 5 / 9, 2) if units == "F" else value


def _reading(celsius: float | None, units: str) -> float | None:
    v = from_c(celsius, units)
    return None if v is None else round(v, 1)


def _setpoint(celsius: float | None, units: str) -> float | None:
    v = from_c(celsius, units)
    if v is None:
        return None
    return round(v) if units == "F" else round(v * 2) / 2


# ---- reading state -----------------------------------------------------------


def _thermostat_accessory(accessories: Accessories) -> Accessory:
    for acc in accessories.accessories:
        if acc.services.first(service_type=ST.THERMOSTAT):
            return acc
    raise EcobeeError("no thermostat service on this accessory")


def _find(acc: Accessory, char_type: str):
    """First characteristic of a type on any of the accessory's services."""
    for service in acc.services:
        if service.has(char_type):
            return service[char_type]
    return None


def _value(acc: Accessory, char_type: str) -> Any:
    char = _find(acc, char_type)
    return None if char is None else char.value


def _sensors(accessories: Accessories, units: str) -> list[dict]:
    sensors = []
    for acc in accessories.accessories:
        temp = occupied = None
        for service in acc.services:
            if service.type == ST.TEMPERATURE_SENSOR:
                temp = service.value(CT.TEMPERATURE_CURRENT)
            elif service.type == ST.OCCUPANCY_SENSOR:
                occupied = service.value(CT.OCCUPANCY_DETECTED)
            elif service.type == ST.MOTION_SENSOR and occupied is None:
                occupied = service.value(CT.MOTION_DETECTED)
        if temp is None and occupied is None:
            continue
        sensors.append(
            {
                "name": acc.name,
                "temperature": _reading(temp, units),
                "occupied": None if occupied is None else bool(occupied),
            }
        )
    return sensors


def thermostat_state(alias: str, accessories: Accessories, units: str | None = None) -> dict:
    acc = _thermostat_accessory(accessories)
    svc = acc.services.first(service_type=ST.THERMOSTAT)
    units = units or ("F" if svc.value(CT.TEMPERATURE_UNITS) == 1 else "C")
    mode = HVAC_MODES.get(svc.value(CT.HEATING_COOLING_TARGET), "unknown")
    action = HVAC_ACTIONS.get(svc.value(CT.HEATING_COOLING_CURRENT), "unknown")
    if mode == "off":
        action = "off"
    comfort = _value(acc, CT.VENDOR_ECOBEE_CURRENT_MODE)
    humidity = svc.value(CT.RELATIVE_HUMIDITY_CURRENT)
    return {
        "alias": alias,
        "name": acc.name,
        "available": True,
        "units": units,
        "temperature": _reading(svc.value(CT.TEMPERATURE_CURRENT), units),
        "humidity": None if humidity is None else round(humidity),
        "mode": mode,
        "action": action,
        "target": _setpoint(svc.value(CT.TEMPERATURE_TARGET), units) if mode in ("heat", "cool") else None,
        "heat_setpoint": _setpoint(svc.value(CT.TEMPERATURE_HEATING_THRESHOLD), units),
        "cool_setpoint": _setpoint(svc.value(CT.TEMPERATURE_COOLING_THRESHOLD), units),
        "comfort": COMFORT.get(comfort) if comfort is not None else None,
        "sensors": _sensors(accessories, units),
        "updated_at": time.time(),
    }


def unavailable_state(alias: str, error: str, previous: dict | None = None) -> dict:
    state = dict(previous or {"alias": alias, "name": alias})
    state.update(available=False, error=error)
    return state


# ---- state cache shared with the bar widget ----------------------------------


def read_cache() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"thermostats": {}}


def write_cache(states: list[dict], remove: list[str] = ()) -> None:
    cache = read_cache()
    thermostats = cache.setdefault("thermostats", {})
    for state in states:
        thermostats[state["alias"]] = state
    for alias in remove:
        thermostats.pop(alias, None)
    cache["updated_at"] = time.time()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cache, indent=1))
    tmp.replace(STATE_FILE)  # atomic, so the widget never reads half a file


# ---- the controller ----------------------------------------------------------


class Home:
    """All saved pairings, loaded into one aiohomekit controller."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._zc: AsyncZeroconf | None = None
        self.controller: Controller | None = None

    async def __aenter__(self) -> Home:
        self._zc = AsyncZeroconf()
        # aiohomekit's IP transport looks for an existing browser on the zeroconf
        # instance. On a LAN it also keeps addresses fresh via multicast.
        self._browser = AsyncServiceBrowser(
            self._zc.zeroconf, ["_hap._tcp.local.", "_hap._udp.local."], listener=ZeroconfServiceListener()
        )
        self.controller = Controller(
            async_zeroconf_instance=self._zc,
            char_cache=CharacteristicCacheFile(CHARMAP_FILE),
        )
        await self.controller.__aenter__()
        self.controller.load_data(str(PAIRING_FILE))
        return self

    async def __aexit__(self, *exc) -> None:
        for pairing in list(self.controller.aliases.values()):
            try:
                await pairing.close()
            except Exception:
                pass
        await self.controller.__aexit__(*exc)
        await self._browser.async_cancel()
        await self._zc.async_close()

    def _save(self) -> None:
        self.controller.save_data(str(PAIRING_FILE))
        os.chmod(PAIRING_FILE, 0o600)  # holds the controller's private key

    def aliases(self) -> list[str]:
        return sorted(self.controller.aliases)

    def pick(self, name: str | None, *, single: bool = False) -> list[str]:
        """Resolve -t NAME (case-insensitive, prefix ok) to aliases."""
        aliases = self.aliases()
        if not aliases:
            raise EcobeeError("no thermostats paired yet; run `ecobee discover` then `ecobee pair NAME`")
        if name is None:
            if not single or len(aliases) == 1:
                return aliases
            if self.config.default in aliases:
                return [self.config.default]
            raise EcobeeError(
                f"several thermostats paired ({', '.join(aliases)}); pick one with -t or set `default` in config"
            )
        key = slugify(name)
        if key in aliases:
            return [key]
        matches = [a for a in aliases if a.startswith(key)]
        if len(matches) == 1:
            return matches
        raise EcobeeError(f"no single thermostat matches {name!r} (have: {', '.join(aliases)})")

    # -- pairing --

    async def pair(self, device: discovery.Device, alias: str, pin: str) -> None:
        if alias in self.controller.aliases:
            raise EcobeeError(f"{alias!r} is already paired")
        ip = self.controller.transports[TransportType.IP]
        try:
            finish = await IpDiscovery(ip, device.to_service()).async_start_pairing(alias)
            pairing = await finish(pin)
        except AuthenticationError:
            raise EcobeeError(f"{device.name} rejected the HomeKit code {pin}; check the digits and try again") from None
        except HomeKitException as e:
            raise EcobeeError(f"pairing with {device.name} failed: {e.__class__.__name__}: {e}") from None
        self.controller.aliases[alias] = pairing
        self.controller.pairings[pairing.pairing_data["AccessoryPairingID"].lower()] = pairing
        self._save()

    async def unpair(self, alias: str) -> None:
        await self.controller.remove_pairing(alias)
        self._save()
        write_cache([], remove=[alias])

    # -- reading --

    async def _relocate(self, alias: str) -> bool:
        """The thermostat moved (new IP or HAP port): find it and reload the pairing."""
        old = self.controller.aliases[alias]
        data = dict(old.pairing_data)
        dev = await discovery.locate(data["AccessoryPairingID"], data.get("AccessoryIP"), self.config.subnets)
        if dev is None or (dev.address == data.get("AccessoryIP") and dev.port == data.get("AccessoryPort")):
            return False
        log.info("%s moved to %s:%s", alias, dev.address, dev.port)
        data.update(AccessoryIP=dev.address, AccessoryIPs=[dev.address], AccessoryPort=dev.port)
        try:
            await old.close()
        except Exception:
            pass
        self.controller.load_pairing(alias, data)
        self._save()
        return True

    async def fetch(self, alias: str) -> Accessories:
        for attempt in range(2):
            pairing = self.controller.aliases[alias]
            try:
                data = await asyncio.wait_for(pairing.list_accessories_and_characteristics(), 15)
                return Accessories.from_list(data)
            except Exception as e:
                if attempt == 0 and await self._relocate(alias):
                    continue
                raise EcobeeError(f"{alias}: can't reach thermostat ({e.__class__.__name__}: {e})") from e
        raise AssertionError("unreachable")

    async def state(self, alias: str) -> dict:
        return thermostat_state(alias, await self.fetch(alias), self.config.units)

    # -- writing --

    async def write(self, alias: str, accessories: Accessories, values: dict[str, Any]) -> None:
        acc = _thermostat_accessory(accessories)
        updates = []
        for char_type, value in values.items():
            char = _find(acc, char_type)
            if char is None:
                raise EcobeeError(f"{alias}: thermostat doesn't expose characteristic {char_type}")
            updates.append((acc.aid, char.iid, value))
        result = await self.controller.aliases[alias].put_characteristics(updates)
        if failed := [r.get("description", r) for r in (result or {}).values() if r.get("status")]:
            raise EcobeeError(f"{alias}: thermostat rejected the change: {failed}")

    async def set_temperature(
        self,
        alias: str,
        value: float | None = None,
        *,
        relative: bool = False,
        heat: float | None = None,
        cool: float | None = None,
    ) -> dict:
        accessories = await self.fetch(alias)
        st = thermostat_state(alias, accessories, self.config.units)
        units, mode = st["units"], st["mode"]
        values: dict[str, Any] = {}
        if heat is not None:
            values[CT.TEMPERATURE_HEATING_THRESHOLD] = to_c(heat, units)
        if cool is not None:
            values[CT.TEMPERATURE_COOLING_THRESHOLD] = to_c(cool, units)
        if value is not None:
            if mode in ("heat", "cool"):
                target = st["target"] + value if relative else value
                values[CT.TEMPERATURE_TARGET] = to_c(target, units)
            elif mode == "auto" and relative:
                values[CT.TEMPERATURE_HEATING_THRESHOLD] = to_c(st["heat_setpoint"] + value, units)
                values[CT.TEMPERATURE_COOLING_THRESHOLD] = to_c(st["cool_setpoint"] + value, units)
            elif mode == "auto":
                raise EcobeeError(f"{alias} is in auto mode; use --heat/--cool, or a relative change like +1")
            else:
                raise EcobeeError(f"{alias} is off; set a mode first (`ecobee mode heat`)")
        if not values:
            raise EcobeeError("nothing to set")
        await self.write(alias, accessories, values)
        return await self._settled(alias)

    async def set_mode(self, alias: str, mode: str) -> dict:
        code = {v: k for k, v in HVAC_MODES.items()}[mode]
        await self.write(alias, await self.fetch(alias), {CT.HEATING_COOLING_TARGET: code})
        return await self._settled(alias)

    async def set_comfort(self, alias: str, comfort: str) -> dict:
        code = {v: k for k, v in COMFORT.items()}[comfort]
        await self.write(alias, await self.fetch(alias), {CT.VENDOR_ECOBEE_SET_HOLD_SCHEDULE: code})
        return await self._settled(alias)

    async def resume(self, alias: str) -> dict:
        await self.write(alias, await self.fetch(alias), {CT.VENDOR_ECOBEE_CLEAR_HOLD: True})
        return await self._settled(alias)

    async def _settled(self, alias: str) -> dict:
        # The thermostat takes a moment to reflect holds in its read values.
        await asyncio.sleep(1)
        state = await self.state(alias)
        write_cache([state])
        return state
