"""The change log: every change to a thermostat, wherever it came from.

One JSON line per change in ~/.local/state/thermoslop/changes.jsonl (mode 600,
rotated at about 1 MB). `source` says where it came from:

  mcp       an AI client through `thermoslop mcp` (caller: local client or tailnet user)
  cli       `thermoslop` in a terminal or script
  widget    the bar widget (it runs the CLI with THERMOSLOP_SOURCE=widget)
  external  the watcher saw a setting change that ThermoSlop didn't make:
            the thermostat's screen, the ecobee app, or its schedule

Lines from before `source` existed were all MCP.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from thermoslop import config
from thermoslop.config import private_dir

ROTATE_BYTES = 1_000_000
SOURCES = ("mcp", "cli", "widget", "external")
# Outcomes after which the thermostat may have changed: "unconfirmed" means it
# was written but didn't read back in time, "uncertain" that the write's result
# is unknown (e.g. a timeout after sending).
CHANGED = ("ok", "unconfirmed", "uncertain")


def snapshot(state: dict) -> dict:
    """The settings a change log entry records before and after."""
    keys = ("mode", "target", "heat_setpoint", "cool_setpoint", "comfort")
    return {k: state.get(k) for k in keys}


def explains(entry: dict, alias: str, observed: dict) -> bool:
    """Could this logged change have produced the settings the watcher saw?

    Every field must hold the entry's after-value or, while the thermostat is
    still catching up (an ecobee3 lite reports comfort a few seconds after the
    setpoint), its before-value. Entries without after-values (failed, refused)
    explain nothing.
    """
    after = (entry.get("after") or {}).get(alias)
    if not after:
        return False
    before = (entry.get("before") or {}).get(alias) or {}
    reached = False
    for key, value in observed.items():
        if value == after.get(key):
            reached = reached or after.get(key) != before.get(key, object())
            continue
        if key in before and value == before[key]:
            continue
        return False
    return reached or observed == after


def record(
    source: str,
    tool: str,
    args: dict,
    caller: str,
    outcome: str,
    thermostats: list[str] = (),
    before: dict | None = None,
    after: dict | None = None,
    error: str | None = None,
    path: Path | None = None,
    now: float | None = None,
) -> dict:
    """outcome: one of CHANGED, "refused" or "failed"."""
    path = path or config.AUDIT_FILE
    entry = {
        "time": time.time() if now is None else now,
        "source": source,
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
    private_dir(path.parent)
    if path.exists() and path.stat().st_size > ROTATE_BYTES:
        path.replace(path.with_suffix(".jsonl.1"))
    # 600: it records tailnet logins and node names.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def entries(path: Path | None = None, since: float | None = None) -> list[dict]:
    """Every entry (rotated file first), oldest first, optionally since a time."""
    path = path or config.AUDIT_FILE
    found = []
    for file in (path.with_suffix(".jsonl.1"), path):
        try:
            lines = file.read_text().splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry.setdefault("source", "mcp")
            if since is None or entry.get("time", 0) >= since:
                found.append(entry)
    return found
