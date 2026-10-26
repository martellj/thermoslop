"""--plain / THERMOSLOP_PLAIN=1: words instead of symbols, for screen readers."""

import json
from types import SimpleNamespace

import pytest

from thermoslop import cli

SYMBOLS = "·—→▲▼"
STATE = {"alias": "upstairs", "name": "Upstairs", "house": None, "available": True, "units": "F",
         "temperature": 70.9, "humidity": 58, "mode": "heat", "action": "heating", "target": 61,
         "heat_setpoint": 61, "cool_setpoint": 75, "comfort": "hold", "sensors": []}
AUTO = {**STATE, "mode": "auto", "action": "idle", "target": None}
ENTRY = {"time": 0, "source": "cli", "tool": "set_temperature", "outcome": "ok", "caller": "terminal",
         "thermostats": ["upstairs"], "before": {"upstairs": {"target": None, "mode": "heat"}},
         "after": {"upstairs": {"target": 61, "mode": "heat"}}}


@pytest.fixture
def plain(monkeypatch):
    monkeypatch.setattr(cli, "PLAIN", True)


def test_status_reads_as_words(plain):
    assert cli.human(cli.format_state(STATE)) == "Upstairs: 70.9°F, heating, set 61°F (heat), hold, 58% RH"
    assert "61°F to 75°F" in cli.human(cli.format_state(AUTO))


def test_log_reads_as_words(plain):
    text = cli.human("\n".join(cli.format_entry(ENTRY)))
    assert "target none to 61" in text and not set(SYMBOLS) & set(text)


def test_errors_are_plain(capsys, monkeypatch, tmp_path):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var))

    async def fails(args, config):
        raise cli.ThermoSlopError("wrong code; check the screen, Menu → Settings → HomeKit")

    monkeypatch.setattr(cli, "cmd_status", fails)
    monkeypatch.setattr(cli, "PLAIN", False)
    with pytest.raises(SystemExit):
        cli.main(["status", "--plain"])
    err = capsys.readouterr().err
    assert "Menu to Settings to HomeKit" in err and "→" not in err
    monkeypatch.setenv("THERMOSLOP_PLAIN", "1")
    with pytest.raises(SystemExit):
        cli.main(["status"])
    assert "→" not in capsys.readouterr().err


def test_default_output_keeps_symbols():
    assert " · " in cli.human(cli.format_state(STATE))


def test_json_is_unchanged(plain, capsys):
    cli.emit(SimpleNamespace(json=True), STATE, cli.format_state(STATE))
    assert json.loads(capsys.readouterr().out) == STATE


def test_flag_and_environment_switch_it_on(monkeypatch):
    parser = cli.build_parser()
    assert parser.parse_args(["status", "--plain"]).plain
    assert not parser.parse_args(["status"]).plain
