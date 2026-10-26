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
