"""Guardrails for changes made through the MCP server.

Limits come from `[mcp]` in the config. Every attempted change, refused or
not, is appended to the audit log; the rate limit counts successful changes in
that log, so restarting the server doesn't reset it.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from ecobee.config import AUDIT_FILE, McpConfig, degrees_in
from ecobee.homekit import EcobeeError

WINDOW = 3600
ROTATE_BYTES = 1_000_000
SETPOINT_NAMES = {"target": "target", "heat": "heat setpoint", "cool": "cool setpoint"}


class Refused(EcobeeError):
    """A change the guardrails won't make. Nothing was written."""


def _num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def snapshot(state: dict) -> dict:
    """The parts of a state the audit log records before and after a change."""
    keys = ("mode", "target", "heat_setpoint", "cool_setpoint", "comfort")
    return {k: state.get(k) for k in keys}


class Guard:
    def __init__(self, config: McpConfig, audit_file: Path = AUDIT_FILE, clock: Callable[[], float] = time.time):
        self.config = config
        self.audit_file = audit_file
        self.clock = clock
        self._changes: deque[float] = deque(self._logged_changes())

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

    def check_rate(self, count: int = 1) -> None:
        now = self.clock()
        while self._changes and self._changes[0] <= now - WINDOW:
            self._changes.popleft()
        limit = self.config.max_changes_per_hour
        if len(self._changes) + count > limit:
            # The oldest changes have to age out of the window first.
            needed = len(self._changes) + count - limit
            wait = self._changes[needed - 1] + WINDOW - now if needed <= len(self._changes) else WINDOW
            raise Refused(
                f"rate limit: {len(self._changes)} changes in the last hour (max {limit}, "
                f"[mcp] max_changes_per_hour); next change allowed in {max(1, round(wait / 60))} min"
            )

    # -- audit log --

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
    ) -> None:
        """outcome: "ok", "refused" or "failed". Only "ok" counts toward the rate limit."""
        now = self.clock()
        entry = {
            "time": now,
            "tool": tool,
            "args": args,
            "caller": caller,
            "outcome": outcome,
            "thermostats": list(thermostats),
            "before": before,
            "after": after,
        }
        if error:
            entry["error"] = error
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        if self.audit_file.exists() and self.audit_file.stat().st_size > ROTATE_BYTES:
            self.audit_file.replace(self.audit_file.with_suffix(".jsonl.1"))
        with self.audit_file.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        if outcome == "ok":
            self._changes.extend([now] * max(1, len(thermostats)))

    def _logged_changes(self) -> list[float]:
        since = self.clock() - WINDOW
        times: list[float] = []
        for path in (self.audit_file.with_suffix(".jsonl.1"), self.audit_file):
            try:
                lines = path.read_text().splitlines()
            except FileNotFoundError:
                continue
            for line in lines:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("outcome") == "ok" and entry.get("time", 0) > since:
                    times += [entry["time"]] * max(1, len(entry.get("thermostats", [])))
        return sorted(times)
