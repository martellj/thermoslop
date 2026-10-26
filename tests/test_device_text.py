"""Device-supplied text is cleaned where it enters (see thermoslop.text)."""

import json

from thermoslop import cli, discovery
from thermoslop.discovery import Device, _device_from_txt
from thermoslop.text import clean

OSC52 = "Lobby\x1b]52;c;ZXZpbA==\x07"          # sets the clipboard on some terminals
BIDI = "Den‮gnp.exe"                       # displays as "Denexe.png"
IMG = '<img src="http://203.0.113.9/x.png">'    # Qt rich text would fetch this


def test_clean_drops_controls_and_bidi_and_caps_length():
    assert clean(OSC52) == "Lobby]52;c;ZXZpbA=="
    assert clean(BIDI) == "Dengnp.exe"
    assert clean("x" * 500) == "x" * 64
    assert clean(None) == ""
    # markup and pipes are kept: each display escapes for its own syntax
    assert clean(IMG) == IMG and clean("a | b") == "a | b"


def test_discovered_devices_are_cleaned():
    dev = _device_from_txt(OSC52 + "._hap._tcp.local.", "192.0.2.9", 51826,
                           {"id": "AA:BB:CC:DD:EE:FF\x1b[2J", "md": "M" * 300 + "\x07", "ci": "9"})
    assert dev.name == "Lobby]52;c;ZXZpbA=="
    assert "\x1b" not in dev.id and len(dev.model) == 64
    assert Device(BIDI, "x", "m", "192.0.2.1", 1).name == "Dengnp.exe"


def _hostile(monkeypatch):
    async def fake_discover(subnets, timeout=3.0):
        return [Device(OSC52, "aa:bb:cc:dd:ee:ff", IMG, "192.0.2.9", 51826, category=9)]

    monkeypatch.setattr(discovery, "discover", fake_discover)


def test_discover_output_has_no_control_characters(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d"))
    _hostile(monkeypatch)
    for args in (["discover"], ["discover", "--json"]):
        try:
            cli.main(args)
        except SystemExit:
            pass
        out = capsys.readouterr().out
        assert "\x1b" not in out and "\x07" not in out, args
    try:
        cli.main(["discover", "--json"])
    except SystemExit:
        pass
    (found,) = json.loads(capsys.readouterr().out)
    assert found["name"] == "Lobby]52;c;ZXZpbA==" and found["model"] == IMG


def test_status_bars_dont_interpret_names():
    from thermoslop.bar import render, select

    def state(alias, name):
        return {"alias": alias, "name": name, "house": "home", "available": True, "units": "F",
                "temperature": 68.0, "mode": "heat", "action": "idle", "target": 68,
                "heat_setpoint": 68, "cool_setpoint": 75, "comfort": "hold", "updated_at": 1000.0}

    cache = {"updated_at": 1000.0, "thermostats": {
        "den": state("den", "Den | bash=/bin/sh param1=-c param2=id"),
        "lab": state("lab", "<b>Lab</b>\nInjected | href=http://203.0.113.9"),
    }}
    waybar = json.loads(render("waybar", select(cache), 1000.0))
    assert "&lt;b&gt;Lab&lt;/b&gt;" in waybar["tooltip"] and "<b>" not in waybar["tooltip"]

    swift = render("swiftbar", select(cache), 1000.0, binary="/x/thermoslop").splitlines()
    for line in swift:
        title, _, params = line.partition(" | ")
        # parameters only ever come from ThermoSlop's own actions and styling
        assert "/bin/sh" not in params and "203.0.113.9" not in params, line
    assert any(line.startswith("Den bash=/bin/sh") for line in swift)  # shown, but as plain title text
    assert not any(line.startswith("Injected") for line in swift)       # no extra item from the newline
