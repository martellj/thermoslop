"""The change log: CLI/widget entries and changes made outside ThermoSlop."""

import asyncio
import json

import pytest

from thermoslop import audit
from thermoslop.cli import format_entry
from thermoslop.daemon import ChangeTracker


def _state(target=60, comfort="hold", available=True):
    return {"alias": "upstairs", "available": available, "mode": "heat", "target": target,
            "heat_setpoint": target, "cool_setpoint": 65, "comfort": comfort}


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _run(path, steps, delay=0.05):
    """Feed states to a tracker (None = pause), then let pending attributions finish."""
    async def go():
        tracker = ChangeTracker("upstairs", path, delay=delay)
        for step in steps:
            if callable(step):
                step()
            else:
                tracker.observe(step)
        await asyncio.sleep(delay * 3)
    asyncio.run(go())


def test_first_reading_is_not_a_change(tmp_path):
    path = tmp_path / "changes.jsonl"
    _run(path, [_state(), _state()])
    assert _lines(path) == []


def test_outside_change_is_logged_as_external(tmp_path):
    path = tmp_path / "changes.jsonl"
    _run(path, [_state(60), _state(61)])
    (entry,) = _lines(path)
    assert (entry["source"], entry["tool"], entry["thermostats"]) == ("external", "external_change", ["upstairs"])
    assert entry["before"]["upstairs"]["target"] == 60 and entry["after"]["upstairs"]["target"] == 61


def test_thermoslop_change_is_not_external(tmp_path):
    path = tmp_path / "changes.jsonl"
    ours = lambda: audit.record("widget", "set_temperature", {"temperature": "+1"}, "bar widget", "ok", ["upstairs"],
                                {"upstairs": audit.snapshot(_state(60))}, {"upstairs": audit.snapshot(_state(61))}, path=path)
    _run(path, [_state(60), _state(61), ours])  # logged after the watcher saw it, like the CLI does
    assert [e["source"] for e in _lines(path)] == ["widget"]


def test_failed_or_other_thermostat_entries_dont_count(tmp_path):
    path = tmp_path / "changes.jsonl"
    audit.record("cli", "set_temperature", {}, "terminal", "failed", ["upstairs"], path=path)
    audit.record("cli", "set_temperature", {}, "terminal", "ok", ["main-floor"], path=path)
    _run(path, [_state(60), _state(61)])
    assert [e["source"] for e in _lines(path)] == ["cli", "cli", "external"]


def test_unavailable_readings_are_ignored(tmp_path):
    path = tmp_path / "changes.jsonl"
    _run(path, [_state(60), _state(available=False), _state(60)])
    assert _lines(path) == []


def test_mcp_rate_limit_ignores_other_sources(tmp_path):
    from thermoslop.config import McpConfig
    from thermoslop.guard import Guard, Refused

    path = tmp_path / "changes.jsonl"
    for source in ("cli", "widget", "external"):
        audit.record(source, "set_temperature", {}, "x", "ok", ["upstairs"], path=path)
    guard = Guard(McpConfig(max_changes_per_hour=1), path)
    guard.check_rate()
    guard.record("set_temperature", {}, "local:test", "ok", ["upstairs"])
    with pytest.raises(Refused):
        guard.check_rate()


def test_legacy_lines_count_as_mcp(tmp_path):
    path = tmp_path / "changes.jsonl"
    path.write_text(json.dumps({"time": 1, "tool": "set_temperature", "outcome": "ok", "thermostats": ["upstairs"]}) + "\n")
    assert audit.entries(path)[0]["source"] == "mcp"


def test_log_formatting():
    entry = {"time": 0, "source": "external", "tool": "external_change", "caller": "thermostat, app or schedule",
             "outcome": "ok", "thermostats": ["upstairs"],
             "before": {"upstairs": _state(60.0)}, "after": {"upstairs": _state(61.0, comfort="hold")}}
    text = "\n".join(format_entry(entry))
    assert "external" in text and "upstairs: target 60→61, heat 60→61" in text


def test_cli_and_widget_changes_are_logged(tmp_path, monkeypatch):
    import argparse

    import thermoslop.config
    import thermoslop.homekit
    from thermoslop.cli import logged
    from thermoslop.homekit import ThermoSlopError

    path = tmp_path / "changes.jsonl"
    monkeypatch.setattr(thermoslop.config, "AUDIT_FILE", path)
    monkeypatch.setattr(thermoslop.homekit, "STATE_FILE", tmp_path / "state.json")
    thermoslop.homekit.write_cache([_state(60)])
    args = argparse.Namespace(temperature="+1", thermostat="upstairs", house=None)

    async def change():
        return _state(61)

    monkeypatch.delenv("THERMOSLOP_SOURCE", raising=False)
    asyncio.run(logged(args, "set_temperature", change))
    monkeypatch.setenv("THERMOSLOP_SOURCE", "widget")
    asyncio.run(logged(args, "set_temperature", change))

    async def broken():
        raise ThermoSlopError("upstairs: can't reach thermostat")

    with pytest.raises(ThermoSlopError):
        asyncio.run(logged(args, "set_temperature", broken))

    cli, widget, failed = _lines(path)
    assert (cli["source"], cli["caller"].startswith("terminal")) == ("cli", True)
    assert cli["args"] == {"temperature": "+1", "thermostat": "upstairs"}
    assert cli["before"]["upstairs"]["target"] == 60 and cli["after"]["upstairs"]["target"] == 61
    assert (widget["source"], widget["caller"]) == ("widget", "bar widget")
    assert (failed["outcome"], failed["error"]) == ("failed", "upstairs: can't reach thermostat")



# ---- audit fixes 3.2 / 3.3: attribution by values, and changes across watcher restarts

def _widget(path, before, after, when=None):
    audit.record("widget", "set_temperature", {}, "bar widget", "ok", ["upstairs"],
                 {"upstairs": audit.snapshot(before)}, {"upstairs": audit.snapshot(after)}, path=path, now=when)


def test_app_change_right_after_a_widget_change_is_external(tmp_path):
    path = tmp_path / "changes.jsonl"
    _run(path, [_state(60), lambda: _widget(path, _state(60), _state(61)), _state(61), _state(64)])
    entries = _lines(path)
    assert [e["source"] for e in entries] == ["widget", "external"]
    assert entries[1]["after"]["upstairs"]["target"] == 64


def test_lagging_comfort_is_still_ours(tmp_path):
    path = tmp_path / "changes.jsonl"
    # The widget's resume: comfort hold→home and target 61→65. The lite reports
    # the target first, then the comfort.
    _run(path, [_state(61, "hold"), lambda: _widget(path, _state(61, "hold"), _state(65, "home")),
                _state(65, "hold"), _state(65, "home")])
    assert [e["source"] for e in _lines(path)] == ["widget"]


def test_change_while_watcher_stopped_is_external(tmp_path):
    path = tmp_path / "changes.jsonl"

    async def go():
        tracker = ChangeTracker("upstairs", path, delay=0.05, baseline={**_state(60), "updated_at": 1000})
        tracker.observe(_state(63))  # first reading after the restart
        await asyncio.sleep(0.15)
    asyncio.run(go())
    (entry,) = _lines(path)
    assert entry["source"] == "external" and entry["before"]["upstairs"]["target"] == 60


def test_terminal_change_while_watcher_stopped_is_not_external(tmp_path):
    import time

    path = tmp_path / "changes.jsonl"
    baseline_time = time.time() - 3600  # the watcher stopped an hour ago
    audit.record("cli", "set_temperature", {}, "terminal", "ok", ["upstairs"],
                 {"upstairs": audit.snapshot(_state(60))}, {"upstairs": audit.snapshot(_state(62))},
                 path=path, now=baseline_time + 600)  # long outside the normal 70 s window

    async def go():
        tracker = ChangeTracker("upstairs", path, delay=0.05, baseline={**_state(60), "updated_at": baseline_time})
        tracker.observe(_state(62))
        await asyncio.sleep(0.15)
    asyncio.run(go())
    assert [e["source"] for e in _lines(path)] == ["cli"]



def test_unconfirmed_change_explains_the_late_value(tmp_path):
    """Seen live: the readback lagged, so the entry logged the old value (62)
    while the thermostat went on to 61. That's ThermoSlop's change, not external."""
    path = tmp_path / "changes.jsonl"

    def unconfirmed():
        audit.record("widget", "set_temperature", {"temperature": "-1"}, "bar widget", "unconfirmed", ["upstairs"],
                     {"upstairs": audit.snapshot(_state(62))}, {"upstairs": audit.snapshot(_state(62))}, path=path)

    _run(path, [_state(62), unconfirmed, _state(61)])
    assert [e["source"] for e in _lines(path)] == ["widget"]
