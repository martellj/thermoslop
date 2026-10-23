"""Guardrails for changes made through the MCP server.

Limits come from `[mcp]` in the config. Every attempted change, refused or
not, goes to the change log (audit.py) with source "mcp"; the rate limit counts
successful MCP changes in that log, so restarting the server doesn't reset it.
"""

from __future__ import annotations

import fcntl
import os
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from thermoslop import audit
from thermoslop.config import AUDIT_FILE, McpConfig, degrees_in, private_dir
from thermoslop.homekit import ThermoSlopError

WINDOW = 3600
SETPOINT_NAMES = {"target": "target", "heat": "heat setpoint", "cool": "cool setpoint"}


class Refused(ThermoSlopError):
    """A change the guardrails won't make. Nothing was written."""


def _num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


class Guard:
    def __init__(self, config: McpConfig, audit_file: Path = AUDIT_FILE, clock: Callable[[], float] = time.time):
        self.config = config
        self.audit_file = audit_file
        self.clock = clock

    # -- checks (raise Refused) --

    def limits(self, units: str) -> tuple[float, float]:
        return (
            round(degrees_in(self.config.min_setpoint, units), 1),
            round(degrees_in(self.config.max_setpoint, units), 1),
        )

    def check_setpoints(self, state: dict, plan: dict[str, float]) -> None:
        units = state["units"]
        low, high = self.limits(units)
        for key, value in plan.items():
            if not low <= round(value, 1) <= high:
                raise Refused(
                    f"{state['alias']}: {SETPOINT_NAMES[key]} {_num(value)}°{units} is outside the allowed range "
                    f"{_num(low)}–{_num(high)}°{units} ([mcp] min_setpoint / max_setpoint)"
                )

    def check_mode(self, mode: str) -> None:
        if mode == "off" and not self.config.allow_off:
            raise Refused("turning HVAC off over MCP is disabled; set `allow_off = true` under [mcp] to allow it")

    @contextmanager
    def _lock(self):
        """One lock for every ThermoSlop process, so quota can't be double-booked."""
        lock_file = self.audit_file.with_suffix(".lock")
        private_dir(lock_file.parent)
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _usage(self, now: float) -> list[float]:
        """When each change counted against the limit happened, oldest first.

        A reservation counts from when it's made until its change is resolved as
        failed or refused (nothing was written). Uncertain and unconfirmed
        outcomes keep counting. Entries from before reservations existed count
        when they changed something.
        """
        reserved: dict[str, tuple[float, int]] = {}
        released: set[str] = set()
        times: list[float] = []
        for entry in audit.entries(self.audit_file, since=now - WINDOW):
            if entry["source"] != "mcp":
                continue  # the limit is on agents, not the terminal, widget or thermostat
            token = entry.get("reservation")
            if entry.get("outcome") == "reserved":
                reserved[token] = (entry["time"], entry.get("count", 1))
            elif token:
                if entry.get("outcome") in ("failed", "refused"):
                    released.add(token)
            elif entry.get("outcome") in audit.CHANGED:
                times += [entry["time"]] * max(1, len(entry.get("thermostats", [])))
        times += [t for token, (t, n) in reserved.items() if token not in released for _ in range(n)]
        return sorted(times)

    def _refuse_over_limit(self, times: list[float], count: int, now: float) -> None:
        limit = self.config.max_changes_per_hour
        if len(times) + count > limit:
            # The oldest changes have to age out of the window first.
            needed = len(times) + count - limit
            wait = times[needed - 1] + WINDOW - now if needed <= len(times) else WINDOW
            raise Refused(
                f"rate limit: {len(times)} changes in the last hour (max {limit}, "
                f"[mcp] max_changes_per_hour); next change allowed in {max(1, round(wait / 60))} min"
            )

    def check_rate(self, count: int = 1) -> None:
        """Refuse if `count` more changes would exceed the limit (reserves nothing)."""
        now = self.clock()
        with self._lock():
            self._refuse_over_limit(self._usage(now), count, now)

    def reserve(self, count: int = 1) -> str:
        """Atomically claim quota for `count` thermostat changes; returns the reservation id.

        Pass it to record() with the outcome, so a failed or refused change gives
        its quota back.
        """
        now = self.clock()
        with self._lock():
            self._refuse_over_limit(self._usage(now), count, now)
            token = uuid.uuid4().hex[:12]
            audit.record("mcp", "reserve", {}, "rate limit", "reserved", path=self.audit_file, now=now,
                         extra={"reservation": token, "count": count})
        return token

    # -- change log --

    def record(
        self,
        tool: str,
        args: dict,
        caller: str,
        outcome: str,
        thermostats: list[str] = (),
        before: dict | None = None,
        after: dict | None = None,
        error: str | None = None,
        reservation: str | None = None,
    ) -> None:
        """Log an MCP change, resolving its reservation if it had one."""
        extra = {"reservation": reservation} if reservation else None
        audit.record("mcp", tool, args, caller, outcome, thermostats, before, after, error, self.audit_file,
                     self.clock(), extra)
