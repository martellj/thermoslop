"""`thermoslop watch`: keep the state cache fresh for the bar widget.

Subscribes to HomeKit events so changes show up instantly, and polls every
`poll_interval` seconds in case an event was missed. Reconnects (and
rediscovers a moved thermostat) with backoff when a connection drops.

Returns when pairing.json changes so systemd restarts it with the new set.
"""

from __future__ import annotations

import asyncio
import logging

from thermoslop.config import PAIRING_FILE
from thermoslop.homekit import Home, read_cache, thermostat_state, unavailable_state, write_cache

log = logging.getLogger(__name__)


def _pairing_mtime() -> float:
    try:
        return PAIRING_FILE.stat().st_mtime
    except FileNotFoundError:
        return 0


async def _pairings_changed() -> None:
    start = _pairing_mtime()
    while _pairing_mtime() == start:
        await asyncio.sleep(10)


async def watch(home: Home) -> None:
    aliases = home.aliases()
    if not aliases:
        log.warning("no thermostats paired yet; waiting for `thermoslop pair`")
    watchers = [asyncio.create_task(_watch_one(home, alias)) for alias in aliases]
    try:
        await _pairings_changed()
        log.info("pairings changed; exiting so the service restarts with them")
    finally:
        for task in watchers:
            task.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)


async def _watch_one(home: Home, alias: str) -> None:
    units, house = home.config.units, home.house(alias)
    backoff = 5
    while True:
        unsubscribe = None
        try:
            accessories = await home.fetch(alias)
            pairing = home.controller.aliases[alias]

            def publish() -> None:
                write_cache([thermostat_state(alias, accessories, units, house)])

            def on_event(changes: dict) -> None:
                if accessories.process_changes(changes):
                    publish()

            publish()
            readable, evented = [], []
            for acc in accessories.accessories:
                for service in acc.services:
                    for char in service.characteristics:
                        if "pr" in char.perms:
                            readable.append((acc.aid, char.iid))
                        if "ev" in char.perms:
                            evented.append((acc.aid, char.iid))
            unsubscribe = pairing.dispatcher_connect(on_event)
            await pairing.subscribe(evented)
            log.info("%s: watching %d characteristics", alias, len(evented))
            backoff = 5

            while True:
                await asyncio.sleep(home.config.poll_interval)
                values = await asyncio.wait_for(pairing.get_characteristics(readable), 15)
                accessories.process_changes(values)
                publish()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("%s: %s; retrying in %ss", alias, e, backoff)
            previous = read_cache().get("thermostats", {}).get(alias)
            write_cache([unavailable_state(alias, str(e), previous, house)])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)
        finally:
            if unsubscribe:
                unsubscribe()
