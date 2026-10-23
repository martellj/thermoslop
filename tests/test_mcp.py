"""The MCP server against fake thermostats, through an in-process MCP client."""

import asyncio
import json

import pytest
from mcp.client.client import Client

import thermoslop.homekit
from thermoslop.config import Config, McpConfig
from thermoslop.guard import Guard
from thermoslop.homekit import Home, ThermoSlopError, convert_request, plan_setpoints
from thermoslop.mcp_server import ThermostatServer

HOUSES = {"home": ["192.168.1.0/24"], "cabin": ["192.168.2.0/24"]}


class FakeHome(Home):
    """Home.pick and selection logic, with thermostats held in memory."""

    def __init__(self, ignores_comfort=()):
        super().__init__(Config(houses=HOUSES))
        self.thermostats = {
            "main-floor": self._state("main-floor", "home"),
            "upstairs": self._state("upstairs", "home"),
            "cabin-main-floor": self._state("cabin-main-floor", "cabin"),
        }
        self.ignores_comfort = set(ignores_comfort)
        self.busy: set[str] = set()
        self.overlaps = 0

    @staticmethod
    def _state(alias, house):
        return {
            "alias": alias, "name": alias, "house": house, "available": True, "units": "F", "temperature": 68.0,
            "humidity": 50, "mode": "heat", "action": "idle", "target": 66, "heat_setpoint": 66,
            "cool_setpoint": 75, "comfort": "hold", "sensors": [], "updated_at": 0,
        }

    def aliases(self):
        return sorted(self.thermostats)

    def house(self, alias):
        return self.thermostats[alias]["house"]

    async def state(self, alias):
        return dict(self.thermostats[alias])

    async def set_temperature(self, alias, value=None, *, relative=False, heat=None, cool=None, check=None, unit=None):
        if alias in self.busy:
            self.overlaps += 1
        self.busy.add(alias)
        try:
            st = self.thermostats[alias]
            value, heat, cool = convert_request(st, value, relative, heat, cool, unit)
            plan = plan_setpoints(st, value, relative=relative, heat=heat, cool=cool)
            if check:
                check(st, plan)
            await asyncio.sleep(0.05)
            st.update({{"target": "target", "heat": "heat_setpoint", "cool": "cool_setpoint"}[k]: v for k, v in plan.items()})
            return dict(st)
        finally:
            self.busy.discard(alias)

    async def set_mode(self, alias, mode):
        self.thermostats[alias]["mode"] = mode
        return dict(self.thermostats[alias])

    async def set_comfort(self, alias, comfort):
        if alias not in self.ignores_comfort:
            self.thermostats[alias]["comfort"] = comfort
        return dict(self.thermostats[alias])

    async def resume(self, alias):
        self.thermostats[alias]["comfort"] = "home"
        return dict(self.thermostats[alias])


@pytest.fixture(autouse=True)
def state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(thermoslop.homekit, "STATE_FILE", tmp_path / "state.json")


@pytest.fixture
def audit(tmp_path):
    return tmp_path / "changes.jsonl"


def run(server, *calls):
    async def go():
        async with Client(server.mcp) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return asyncio.run(go())


def body(result):
    return result.structured_content.get("result", result.structured_content)


def audit_lines(path):
    """Change-log entries, without the rate limit's internal reservations."""
    return [e for e in map(json.loads, path.read_text().splitlines()) if e["outcome"] != "reserved"]


def test_read_only_lists_only_read_tools(audit):
    server = ThermostatServer(FakeHome(), Guard(McpConfig(), audit), read_only=True)
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"list_thermostats", "get_status"}


def test_all_tools_and_no_pairing(audit):
    server = ThermostatServer(FakeHome(), Guard(McpConfig(), audit))
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {
        "list_thermostats", "get_status", "set_temperature", "adjust_temperature",
        "set_mode", "set_comfort", "resume_schedule",
    }


def test_status_matches_cli_shape(audit):
    home = FakeHome()
    (result,) = run(ThermostatServer(home, Guard(McpConfig(), audit)), ("get_status", {"house": "cabin"}))
    assert body(result) == [home.thermostats["cabin-main-floor"]]


def test_ambiguous_write_is_refused_and_logged(audit):
    home = FakeHome()
    (result,) = run(ThermostatServer(home, Guard(McpConfig(), audit)), ("set_temperature", {"target": 70}))
    assert result.is_error and "`thermostat` argument" in result.content[0].text
    assert all(s["target"] == 66 for s in home.thermostats.values())
    (entry,) = audit_lines(audit)
    assert (entry["outcome"], entry["tool"], entry["thermostats"]) == ("failed", "set_temperature", [])


def test_out_of_range_refused(audit):
    home = FakeHome()
    (result,) = run(
        ThermostatServer(home, Guard(McpConfig(), audit)),
        ("adjust_temperature", {"thermostat": "upstairs", "delta": 5}),  # 66 + 5 fine
        ("set_temperature", {"thermostat": "upstairs", "target": 90}),
    )[1:]
    assert result.is_error and "55–80°F" in result.content[0].text
    assert home.thermostats["upstairs"]["target"] == 71
    assert [e["outcome"] for e in audit_lines(audit)] == ["ok", "refused"]


def test_house_wide_comfort_with_verification(audit):
    home = FakeHome(ignores_comfort={"main-floor"})
    (result,) = run(ThermostatServer(home, Guard(McpConfig(), audit)), ("set_comfort", {"comfort": "away", "house": "home"}))
    applied = {r["alias"]: (r["applied"], r["reported"]) for r in body(result)}
    assert applied == {"main-floor": (False, "hold"), "upstairs": (True, "away")}
    assert home.thermostats["cabin-main-floor"]["comfort"] == "hold"
    entries = audit_lines(audit)
    assert [e["thermostats"] for e in entries] == [["main-floor"], ["upstairs"]]
    assert entries[1]["after"]["upstairs"]["comfort"] == "away"


def test_audit_records_client_name(audit):
    run(ThermostatServer(FakeHome(), Guard(McpConfig(), audit)), ("set_temperature", {"thermostat": "up", "target": 68}))
    (entry,) = audit_lines(audit)
    assert entry["caller"].startswith("local:")
    assert entry["before"]["upstairs"]["target"] == 66 and entry["after"]["upstairs"]["target"] == 68


def test_concurrent_writes_to_one_thermostat_are_serialized(audit):
    home = FakeHome()
    server = ThermostatServer(home, Guard(McpConfig(), audit))

    async def go():
        async with Client(server.mcp) as a, Client(server.mcp) as b:
            await asyncio.gather(
                a.call_tool("adjust_temperature", {"thermostat": "upstairs", "delta": 1}),
                b.call_tool("adjust_temperature", {"thermostat": "upstairs", "delta": 1}),
            )

    asyncio.run(go())
    assert home.overlaps == 0
    assert home.thermostats["upstairs"]["target"] == 68


def test_rate_limit_over_mcp(audit):
    home = FakeHome()
    server = ThermostatServer(home, Guard(McpConfig(max_changes_per_hour=1), audit))
    results = run(
        server,
        ("set_temperature", {"thermostat": "upstairs", "target": 67}),
        ("set_temperature", {"thermostat": "upstairs", "target": 68}),
    )
    assert not results[0].is_error and results[1].is_error
    assert "rate limit" in results[1].content[0].text
    assert home.thermostats["upstairs"]["target"] == 67



# ---- audit fixes (add-mcp-server group 6)

def test_partial_house_wide_failure_keeps_the_successes(audit):
    class FlakyHome(FakeHome):
        async def set_comfort(self, alias, comfort):
            if alias == "upstairs":
                raise ThermoSlopError("upstairs: can't reach thermostat")
            return await super().set_comfort(alias, comfort)

    home = FlakyHome()
    guard = Guard(McpConfig(max_changes_per_hour=5), audit)
    (result,) = run(ThermostatServer(home, guard), ("set_comfort", {"comfort": "away", "house": "home"}))
    assert not result.is_error
    by_alias = {r["alias"]: r for r in body(result)}
    assert by_alias["main-floor"]["applied"] is True and "can't reach" in by_alias["upstairs"]["error"]
    ok, failed = audit_lines(audit)
    assert (ok["outcome"], ok["thermostats"], ok["after"]["main-floor"]["comfort"]) == ("ok", ["main-floor"], "away")
    assert (failed["outcome"], failed["thermostats"]) == ("failed", ["upstairs"])
    guard.check_rate(4)  # one change counted: four more fit under five
    with pytest.raises(Exception):
        guard.check_rate(5)


def test_units_are_explicit_not_guessed(audit):
    home = FakeHome()
    home.thermostats["upstairs"].update(units="C", target=18, heat_setpoint=18, cool_setpoint=24)
    server = ThermostatServer(home, Guard(McpConfig(), audit))  # nothing in the cache: still °F
    assert "°F" in server._instructions()
    run(server, ("set_temperature", {"thermostat": "upstairs", "target": 68}))  # 68 °F
    assert round(home.thermostats["upstairs"]["target"], 1) == 20.0  # written as 20 °C
    run(server, ("set_temperature", {"thermostat": "upstairs", "target": 21, "unit": "C"}))
    assert home.thermostats["upstairs"]["target"] == 21
    (result,) = run(server, ("set_temperature", {"thermostat": "upstairs", "target": 30, "unit": "C"}))
    assert result.is_error and "outside the allowed range" in result.content[0].text  # 30 °C > 80 °F


def test_quota_is_reserved_across_processes(tmp_path):
    """Two separate processes race at a limit of 1: exactly one gets the quota."""
    import multiprocessing as mp

    path = tmp_path / "changes.jsonl"
    ctx = mp.get_context("spawn")
    with ctx.Pool(2) as pool:
        results = pool.map(_reserve_one, [str(path)] * 2)
    assert sorted(results) == ["refused", "reserved"]


def _reserve_one(path):
    from pathlib import Path

    from thermoslop.config import McpConfig
    from thermoslop.guard import Guard, Refused

    try:
        Guard(McpConfig(max_changes_per_hour=1), Path(path)).reserve(1)
        return "reserved"
    except Refused:
        return "refused"


def test_failed_change_gives_quota_back_uncertain_keeps_it(audit):
    guard = Guard(McpConfig(max_changes_per_hour=1), audit)
    token = guard.reserve(1)
    guard.record("set_temperature", {}, "local:test", "failed", ["upstairs"], error="unreachable", reservation=token)
    token = guard.reserve(1)  # the failed one was released
    guard.record("set_temperature", {}, "local:test", "uncertain", ["upstairs"], error="timeout", reservation=token)
    with pytest.raises(Exception, match="rate limit"):
        guard.reserve(1)


def test_concurrent_calls_at_the_limit_make_one_change(audit):
    """The audit's reproduction: two simultaneous adjustments at a limit of one."""
    home = FakeHome()
    server = ThermostatServer(home, Guard(McpConfig(max_changes_per_hour=1), audit))

    async def go():
        async with Client(server.mcp) as a, Client(server.mcp) as b:
            return await asyncio.gather(
                a.call_tool("adjust_temperature", {"thermostat": "upstairs", "delta": 1}),
                b.call_tool("adjust_temperature", {"thermostat": "main-floor", "delta": 1}),
            )

    results = asyncio.run(go())
    assert sorted(r.is_error for r in results) == [False, True]
    assert sum(t["target"] == 67 for t in home.thermostats.values()) == 1
