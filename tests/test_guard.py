import json

import pytest

from thermoslop.config import McpConfig
from thermoslop.guard import Guard, Refused
from thermoslop.homekit import ThermoSlopError, plan_setpoints


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def _state(mode="heat", target=79, units="F"):
    return {"alias": "upstairs", "units": units, "mode": mode, "target": target, "heat_setpoint": 68, "cool_setpoint": 75}


@pytest.fixture
def guard(tmp_path):
    return Guard(McpConfig(), tmp_path / "changes.jsonl", Clock())


def test_setpoint_in_range(guard):
    guard.check_setpoints(_state(), plan_setpoints(_state(), 70))


def test_setpoint_too_hot(guard):
    with pytest.raises(Refused, match=r"target 90°F is outside the allowed range 55–80°F"):
        guard.check_setpoints(_state(), plan_setpoints(_state(), 90))


def test_relative_change_crossing_limit(guard):
    st = _state(target=79)
    with pytest.raises(Refused, match="82°F"):
        guard.check_setpoints(st, plan_setpoints(st, 3, relative=True))


def test_auto_mode_shift_checks_both_setpoints(guard):
    st = _state(mode="auto")
    guard.check_setpoints(st, plan_setpoints(st, 5, relative=True))  # 73–80
    with pytest.raises(Refused, match="cool setpoint 81°F"):
        guard.check_setpoints(st, plan_setpoints(st, 6, relative=True))


def test_limits_in_celsius(tmp_path):
    guard = Guard(McpConfig(), tmp_path / "c.jsonl", Clock())
    st = _state(units="C", target=20)
    assert guard.limits("C") == (12.8, 26.7)
    guard.check_setpoints(st, {"target": 26.5})
    with pytest.raises(Refused, match="27°C"):
        guard.check_setpoints(st, {"target": 27})


def test_heat_cool_planning_errors_pass_through():
    with pytest.raises(ThermoSlopError, match="auto mode"):
        plan_setpoints(_state(mode="auto"), 70)


def test_off_needs_opt_in(tmp_path, guard):
    with pytest.raises(Refused, match="allow_off"):
        guard.check_mode("off")
    guard.check_mode("heat")
    Guard(McpConfig(allow_off=True), tmp_path / "x.jsonl", Clock()).check_mode("off")


def test_rate_limit_window(tmp_path):
    clock = Clock()
    guard = Guard(McpConfig(max_changes_per_hour=3), tmp_path / "a.jsonl", clock)
    for _ in range(3):
        guard.check_rate()
        guard.record("set_temperature", {}, "test", "ok", ["upstairs"])
        clock.now += 60
    with pytest.raises(Refused, match="next change allowed in 57 min"):
        guard.check_rate()
    clock.now += 3600 - 180 + 1  # the first change ages out
    guard.check_rate()


def test_rate_limit_counts_each_thermostat(tmp_path):
    guard = Guard(McpConfig(max_changes_per_hour=3), tmp_path / "a.jsonl", Clock())
    guard.record("set_comfort", {}, "test", "ok", ["a", "b"])
    guard.check_rate(1)
    with pytest.raises(Refused):
        guard.check_rate(2)


def test_rate_limit_survives_restart_and_ignores_refusals(tmp_path):
    path, clock = tmp_path / "a.jsonl", Clock()
    first = Guard(McpConfig(max_changes_per_hour=2), path, clock)
    first.record("set_temperature", {}, "test", "ok", ["upstairs"])
    first.record("set_temperature", {"target": 90}, "test", "refused", ["upstairs"], error="too hot")
    first.record("set_temperature", {}, "test", "failed", ["upstairs"], error="unreachable")
    second = Guard(McpConfig(max_changes_per_hour=2), path, clock)
    second.check_rate(1)
    with pytest.raises(Refused):
        second.check_rate(2)


def test_audit_line(tmp_path):
    path = tmp_path / "a.jsonl"
    guard = Guard(McpConfig(), path, Clock())
    guard.record(
        "set_temperature", {"target": 68}, "alice@ on alices-laptop", "ok", ["upstairs"],
        before={"upstairs": {"target": 70}}, after={"upstairs": {"target": 68}},
    )
    entry = json.loads(path.read_text())
    assert entry["caller"] == "alice@ on alices-laptop"
    assert (entry["tool"], entry["outcome"], entry["thermostats"]) == ("set_temperature", "ok", ["upstairs"])
    assert entry["before"]["upstairs"]["target"] == 70 and entry["after"]["upstairs"]["target"] == 68


def test_audit_rotation(tmp_path, monkeypatch):
    import thermoslop.audit

    monkeypatch.setattr(thermoslop.audit, "ROTATE_BYTES", 100)
    path = tmp_path / "a.jsonl"
    guard = Guard(McpConfig(), path, Clock())
    for _ in range(3):
        guard.record("set_temperature", {"target": 68}, "test", "ok", ["upstairs"])
    assert path.with_suffix(".jsonl.1").exists()
    assert len(path.read_text().splitlines()) < 3
