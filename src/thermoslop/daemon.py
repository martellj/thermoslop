"""`thermoslop watch`: keep the state cache fresh for the bar widget.

Subscribes to HomeKit events so changes show up instantly, and polls every
`poll_interval` seconds in case an event was missed. Reconnects (and
rediscovers a moved thermostat) with backoff when a connection drops.

Also logs setting changes that ThermoSlop didn't make (the thermostat's
screen, the ecobee app, its schedule) to the change log as source "external".

Returns when pairing.json changes so systemd restarts it with the new set.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from thermoslop import audit
from thermoslop.config import AUDIT_FILE, PAIRING_FILE
from thermoslop.homekit import Home, read_cache, thermostat_state, unavailable_state, write_cache

log = logging.getLogger(__name__)


# A change counts as ThermoSlop's when one of its own log entries for that
# thermostat falls between LOOKBACK seconds before the watcher saw it (a poll
# can lag the write by a minute) and DELAY seconds after (the CLI logs once the
# thermostat has settled, up to ~10 s later). Changes are judged DELAY seconds
# after they're seen, so those entries have time to land.
ATTRIBUTION_LOOKBACK = 70
ATTRIBUTION_DELAY = 20


class ChangeTracker:
    """Logs a thermostat's setting changes that didn't come from ThermoSlop."""

    def __init__(self, alias: str, audit_file: Path = AUDIT_FILE, delay: float = ATTRIBUTION_DELAY) -> None:
        self.alias = alias
        self.audit_file = audit_file
        self.delay = delay
        self.last: dict | None = None
        self._pending: set[asyncio.Task] = set()

    def observe(self, state: dict) -> None:
        if not state.get("available"):
            return
        current = audit.snapshot(state)
        if self.last is None or current == self.last:
            self.last = current
            return
        before, self.last = self.last, current
        task = asyncio.get_running_loop().create_task(self._attribute(before, current, time.time()))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _attribute(self, before: dict, after: dict, seen: float) -> None:
        await asyncio.sleep(self.delay)
        ours = any(
            e["source"] != "external" and e.get("outcome") == "ok" and self.alias in e.get("thermostats", [])
            and e["time"] <= seen + self.delay
            for e in audit.entries(self.audit_file, since=seen - ATTRIBUTION_LOOKBACK)
        )
        if not ours:
            log.info("%s: changed outside ThermoSlop", self.alias)
            audit.record(
                "external", "external_change", {}, "thermostat, app or schedule", "ok", [self.alias],
                {self.alias: before}, {self.alias: after}, path=self.audit_file, now=seen,
            )


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
    trend_hours = home.config.trend_hours
    tracker = ChangeTracker(alias)
    backoff = 5
    while True:
        unsubscribe = None
        try:
            accessories = await home.fetch(alias)
            pairing = home.controller.aliases[alias]

            def publish() -> None:
                state = thermostat_state(alias, accessories, units, house)
                write_cache([state], trend_hours=trend_hours)
                tracker.observe(state)

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
