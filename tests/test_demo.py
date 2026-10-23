"""Demo discovery and pairing: the preview flow touches nothing real."""

import json
import subprocess
import sys

import pytest

import thermoslop.demo as demo


def run(*args, stdin=""):
    return subprocess.run([sys.executable, "-m", "thermoslop", *args], input=stdin, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def fast(monkeypatch, tmp_path):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var))
    monkeypatch.setattr(demo, "STEP", 0)


def test_discover_demo_lists_ready_and_elsewhere():
    out = run("discover", "--demo", "--json")
    statuses = {d["name"]: d["status"] for d in json.loads(out.stdout)}
    assert statuses == {"Basement": "ready to pair", "Garage": "paired elsewhere"}


def test_pair_demo_announces_then_accepts_the_shown_code(tmp_path):
    out = run("pair", "Basement", "--demo", "--json", stdin="314 15 926\n")
    event = json.loads(out.stderr.splitlines()[0])
    assert event == {"event": "code_needed", "device": "Basement", "hint": "demo: Basement's screen shows 314-15-926"}
    state = json.loads(out.stdout)
    assert (out.returncode, state["alias"], state["demo"]) == (0, "basement", True)
    assert not any(tmp_path.rglob("pairing.json")) and not any(tmp_path.rglob("changes.jsonl"))


def test_pair_demo_rejects_a_wrong_code():
    out = run("pair", "Basement", "--demo", "--json", stdin="111-22-333\n")
    assert out.returncode == 1 and "rejected the HomeKit code 111-22-333" in json.loads(out.stdout)["error"]


def test_pair_demo_refuses_a_device_paired_elsewhere():
    out = run("pair", "Garage", "--demo", "--json")
    assert out.returncode == 1 and "already paired with another controller" in json.loads(out.stdout)["error"]
