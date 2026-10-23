"""Regression tests for the audit findings (openspec/AUDIT-RESULTS.md)."""

import argparse
import asyncio
import json

import pytest

import thermoslop.config
import thermoslop.homekit
from thermoslop.config import Config
from thermoslop.homekit import Home, ThermoSlopError

from test_state import _ecobee


@pytest.fixture(autouse=True)
def private_files(tmp_path, monkeypatch):
    monkeypatch.setattr(thermoslop.config, "AUDIT_FILE", tmp_path / "changes.jsonl")
    monkeypatch.setattr(thermoslop.homekit, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.delenv("THERMOSLOP_SOURCE", raising=False)


def _state(alias="upstairs", target=60, comfort="hold", mode="heat"):
    return {"alias": alias, "name": alias, "house": None, "available": True, "units": "F", "temperature": 70.0,
            "humidity": 50, "mode": mode, "action": "idle", "target": target, "heat_setpoint": target,
            "cool_setpoint": 75, "comfort": comfort, "sensors": [], "updated_at": 0}


class ScriptedHome(Home):
    """A thermostat whose read-backs follow a script; writes are recorded."""

    def __init__(self, readings, read_delay=0.0):
        super().__init__(Config())
        self.readings = list(readings)
        self.read_delay = read_delay
        self.written = []

    def house(self, alias):
        return None

    async def fetch(self, alias):
        return _ecobee()  # heat mode, target 20 °C (68 °F)

    async def write(self, alias, accessories, values):
        self.written.append(values)

    async def state(self, alias):
        await asyncio.sleep(self.read_delay)
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


def _fast_sleep(monkeypatch):
    real = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda s, *a: real(min(s, 0.01)))


# ---- 1.1 setpoint confirmation (finding 5)

def test_setpoint_confirmed_when_value_reads_back(monkeypatch):
    _fast_sleep(monkeypatch)
    home = ScriptedHome([_state(target=68), _state(target=62)])
    state = asyncio.run(home.set_temperature("upstairs", 62))
    assert state["confirmed"] is True and state["target"] == 62


def test_existing_hold_without_new_value_is_unconfirmed(monkeypatch):
    _fast_sleep(monkeypatch)
    home = ScriptedHome([_state(target=60, comfort="hold")])  # already on hold, never changes

    async def go():
        return await home._settled("upstairs", lambda s: s["target"] == 62, timeout=0.2)

    state = asyncio.run(go())
    assert state["confirmed"] is False and state["target"] == 60


def test_slow_reads_cannot_overrun_the_deadline():
    home = ScriptedHome([_state(target=60)], read_delay=5)

    async def go():
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(ThermoSlopError, match="couldn't be read back"):
            await home._settled("upstairs", lambda s: True, timeout=1.5)
        return loop.time() - start

    assert asyncio.run(go()) < 2.5


def test_cli_exit_code_2_when_unconfirmed(capsys):
    from thermoslop.cli import unconfirmed

    assert unconfirmed([{**_state(target=60), "confirmed": False}]) == 2
    assert "sent, but it still reads" in capsys.readouterr().err
    assert unconfirmed([{**_state(), "confirmed": True}]) == 0


# ---- 1.2 house-wide partial failure (finding 3, CLI side)

class TwoThermostats(Home):
    def __init__(self):
        super().__init__(Config())

    def aliases(self):
        return ["main-floor", "upstairs"]

    def house(self, alias):
        return None

    async def set_comfort(self, alias, comfort):
        if alias == "upstairs":
            raise ThermoSlopError("upstairs: can't reach thermostat")
        return {**_state("main-floor", comfort=comfort), "confirmed": True}


def test_partial_house_wide_failure_reports_logs_and_exits_1(tmp_path, capsys):
    from thermoslop.cli import _each

    thermoslop.homekit.write_cache([_state("main-floor", comfort="hold"), _state("upstairs")])
    home = TwoThermostats()
    args = argparse.Namespace(json=True, thermostat=None, house=None, all=True, comfort="away")
    code = asyncio.run(_each(args, "set_comfort", home, lambda a: home.set_comfort(a, "away")))
    results = json.loads(capsys.readouterr().out)
    assert code == 1
    assert results[0]["alias"] == "main-floor" and results[0]["comfort"] == "away"
    assert results[1] == {"alias": "upstairs", "error": "upstairs: can't reach thermostat"}
    ok, failed = [json.loads(line) for line in (tmp_path / "changes.jsonl").read_text().splitlines()]
    assert (ok["outcome"], ok["thermostats"]) == ("ok", ["main-floor"])
    assert ok["before"]["main-floor"]["comfort"] == "hold" and ok["after"]["main-floor"]["comfort"] == "away"
    assert (failed["outcome"], failed["thermostats"]) == ("failed", ["upstairs"])


# ---- 2.1 pairing by id (finding 6)

def test_ambiguous_names_list_candidates_and_ids_work():
    from aiohomekit.model.categories import Categories

    from thermoslop.discovery import Device, choose

    home = Device("Main Floor", "68:18:08:7F:0D:BD", "ecobee3 lite", "192.168.1.186", 52602, status_flags=0, category=Categories.THERMOSTAT)
    cabin = Device("Main Floor", "AA:BB:CC:DD:EE:01", "ecobee3 lite", "192.168.2.20", 51826, status_flags=1, category=Categories.THERMOSTAT)
    with pytest.raises(ThermoSlopError) as err:
        choose([home, cabin], "Main Floor")
    assert "2 devices are named" in str(err.value) and "AA:BB:CC:DD:EE:01" in str(err.value)
    assert choose([home, cabin], "aa:bb:cc:dd:ee:01") is cabin
    assert choose([home, cabin], "192.168.2.20") is cabin
    assert choose([home], "main floor") is home


# ---- 2.2 interrupting the code prompt (finding 12)

def test_ctrl_c_at_the_code_prompt_exits_at_once(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time

    env = {**os.environ, **{v: str(tmp_path / v) for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")}}
    proc = subprocess.Popen([sys.executable, "-m", "thermoslop", "pair", "Basement", "--demo", "--json"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    line = proc.stderr.readline()  # wait for the code_needed event: it's now blocked on stdin
    assert b"code_needed" in line
    start = time.monotonic()
    proc.send_signal(signal.SIGINT)
    assert proc.wait(timeout=5) == 130
    assert time.monotonic() - start < 2
    proc.stdin.close()
