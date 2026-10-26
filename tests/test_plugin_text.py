"""Qt Text guesses "rich text" from content unless told otherwise, and rich text
loads <img src> URLs. Device names and models are untrusted (discovery is
unauthenticated), so every Text in the plugin must say how it renders."""

import re
from pathlib import Path

PLUGIN = Path(__file__).parent.parent / "omarchy/martellj.thermoslop"
# Styled text is allowed only where it's built from numbers and fixed strings.
STYLED_ALLOWED = {"deltaText"}


def _text_blocks(source: str):
    lines = source.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)Text \{\s*$", line)
        if not m:
            continue
        block = []
        for nxt in lines[i + 1:]:
            if re.match(rf"^{m.group(1)}\}}", nxt):
                break
            block.append(nxt)
        yield i + 1, "\n".join(block)


def test_every_text_declares_its_format():
    checked = 0
    for qml in sorted(PLUGIN.glob("*.qml")):
        for line, block in _text_blocks(qml.read_text()):
            checked += 1
            fmt = re.search(r"^\s*textFormat:\s*Text\.(\w+)", block, re.M)
            assert fmt, f"{qml.name}:{line}: Text without textFormat (it would auto-detect rich text)"
            if fmt.group(1) != "PlainText":
                ident = re.search(r"^\s*id:\s*(\w+)", block, re.M)
                assert ident and ident.group(1) in STYLED_ALLOWED, \
                    f"{qml.name}:{line}: textFormat {fmt.group(1)} outside the numbers-only allow list"
    assert checked > 20  # the scan really found the panel's labels


def test_no_rich_text_anywhere():
    for qml in PLUGIN.glob("*.qml"):
        assert "Text.RichText" not in qml.read_text() and "Text.AutoText" not in qml.read_text(), qml.name
