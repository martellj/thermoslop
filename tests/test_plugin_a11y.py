"""Screen readers: every clickable thing in the plugin has a role and a name,
and the per-thermostat controls say which thermostat they act on."""

import re
from pathlib import Path

PANEL = (Path(__file__).parent.parent / "omarchy/martellj.thermoslop/Panel.qml").read_text()


def _blocks(source: str, header: str):
    lines = source.split("\n")
    for i, line in enumerate(lines):
        m = re.match(rf"^(\s*){header}\s*$", line)
        if m:
            body = []
            for nxt in lines[i + 1:]:
                if re.match(rf"^{m.group(1)}\}}", nxt):
                    break
                body.append(nxt)
            yield i + 1, "\n".join(body)


def test_clickable_components_have_role_and_name():
    found = 0
    for line, body in _blocks(PANEL, r"component \w+: \w+ \{"):
        if "MouseArea" in body:
            found += 1
            assert "Accessible.role" in body and "Accessible.name" in body, f"Panel.qml:{line}: clickable without a role/name"
            assert "Accessible.onPressAction" in body, f"Panel.qml:{line}: screen readers can't press it"
    assert found >= 3  # TextButton, StepButton, Chip


def test_card_controls_name_their_thermostat():
    for kind in ("StepButton", "Chip"):
        uses = [body for _, body in _blocks(PANEL, rf"{kind} \{{")]
        assert uses, kind
        for body in uses:
            assert "accessibleName:" in body, f"a {kind} without an accessibleName"
    for _, body in _blocks(PANEL, r"StepButton \{"):
        if "−" in body or '"+"' in body:
            assert "zone.t.name" in body  # "Raise Upstairs setpoint", not just "+"


def test_graphics_have_text_alternatives():
    for component in ("Ring", "Sparkline"):
        (body,) = [b for _, b in _blocks(PANEL, rf"component {component}: \w+ \{{")]
        assert "Accessible.name" in body, component
