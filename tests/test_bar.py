"""`thermoslop bar`: formats, staleness, filters."""

import json
import subprocess
import sys

from thermoslop.bar import condition, render, select

NOW = 1_000_000.0


def _s(alias, temp, house="home", action="idle", comfort="hold", age=30, available=True, mode="heat"):
    return {"alias": alias, "name": alias.replace("-", " ").title(), "house": house, "available": available,
            "units": "F", "temperature": temp, "mode": mode, "action": action, "target": 61,
            "heat_setpoint": 61, "cool_setpoint": 75, "comfort": comfort, "updated_at": NOW - age}


CACHE = {"thermostats": {
    "main-floor": _s("main-floor", 67.6, action="heating"),
    "upstairs": _s("upstairs", 70.9),
    "cabin-main-floor": _s("cabin-main-floor", 55.2, house="cabin"),
}}


def test_waybar_two_houses_heating():
    out = json.loads(render("waybar", select(CACHE), NOW))
    assert out["text"] == "󰈸 55° │ 68° 71°"  # cabin sorts before home
    assert out["class"] == ["heating"]
    assert "Main Floor 67.6°F · heating · set 61° (heat) · hold" in out["tooltip"]


def test_text_and_filters():
    assert render("text", select(CACHE, house="home"), NOW) == "󰈸 68° 71°"
    assert render("text", select(CACHE, thermostat="up"), NOW) == "󰔏 71°"


def test_stale_and_empty():
    stale = {"thermostats": {"upstairs": _s("upstairs", 70.9, age=900)}}
    out = json.loads(render("waybar", select(stale), NOW))
    assert out["class"] == ["stale"] and "offline" in out["tooltip"] and out["text"].endswith("(stale)")
    empty = json.loads(render("waybar", [], NOW))
    assert empty == {"text": "", "tooltip": empty["tooltip"], "class": ["empty"], "alt": "empty"}
    assert "watcher" in empty["tooltip"]
    assert "match" in json.loads(render("waybar", [], NOW, filtered=True))["tooltip"]


def test_all_away():
    away = {"thermostats": {a: _s(a, 64, comfort="away") for a in ("main-floor", "upstairs")}}
    assert condition(select(away), NOW) == "away"


def test_swiftbar_actions_use_absolute_quoted_path():
    out = render("swiftbar", select(CACHE, house="home"), NOW, binary="/Users/a b/.local/bin/thermoslop")
    lines = out.splitlines()
    assert lines[0] == "68° 71° | sfimage=flame" and lines[1] == "---"
    raise_upstairs = next(l for l in lines if "Raise" in l and "upstairs" in l)
    assert raise_upstairs.startswith("--Raise 1° | bash=\"/Users/a b/.local/bin/thermoslop\" param1=set param2=+1")
    assert "terminal=false refresh=true" in raise_upstairs
    assert any(l.startswith("Away (all) |") for l in lines)


def test_swiftbar_groups_by_house():
    lines = render("swiftbar", select(CACHE), NOW, binary="/x/thermoslop").splitlines()
    assert "Cabin | size=11 color=gray" in lines and "Home | size=11 color=gray" in lines


def test_cli_without_state_file(tmp_path):
    import os

    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache"), "XDG_CONFIG_HOME": str(tmp_path / "c"),
           "XDG_DATA_HOME": str(tmp_path / "d"), "XDG_STATE_HOME": str(tmp_path / "s")}
    out = subprocess.run([sys.executable, "-m", "thermoslop", "bar", "--format", "waybar"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["class"] == ["empty"]
