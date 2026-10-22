"""The MCP server against fake thermostats, through an in-process MCP client."""

import asyncio
import json

import pytest
from mcp.client.client import Client

import thermoslop.homekit
from thermoslop.config import Config, McpConfig
from thermoslop.guard import Guard
from thermoslop.homekit import Home, plan_setpoints
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

    async def set_temperature(self, alias, value=None, *, relative=False, heat=None, cool=None, check=None):
        if alias in self.busy:
            self.overlaps += 1
        self.busy.add(alias)
        try:
            st = self.thermostats[alias]
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
    return [json.loads(line) for line in path.read_text().splitlines()]


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
    (entry,) = audit_lines(audit)
    assert entry["thermostats"] == ["main-floor", "upstairs"]
    assert entry["after"]["upstairs"]["comfort"] == "away"


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
