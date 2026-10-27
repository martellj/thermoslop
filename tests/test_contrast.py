"""The panel's colors are readable in every Omarchy theme.

Runs the plugin's own contrast.js (what Panel.qml uses) under Node over the
22 themes' colors (tests/fixtures/omarchy-themes.json, taken from
/usr/share/omarchy/themes with the keys Omarchy's Color.qml reads)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
JS = ROOT / "omarchy/martellj.thermoslop/contrast.js"
THEMES = ROOT / "tests/fixtures/omarchy-themes.json"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

# Mirrors the property definitions in Panel.qml.
CHECK = r"""
const src = require("fs").readFileSync(process.argv[1], "utf8").replace(/^\.pragma library\s*/, "");
const m = { exports: {} };
new Function("module", src)(m);
const C = m.exports;
const hex = h => ({ r: parseInt(h.slice(1, 3), 16) / 255, g: parseInt(h.slice(3, 5), 16) / 255, b: parseInt(h.slice(5, 7), 16) / 255 });
const darker = (c, f) => ({ r: c.r / f, g: c.g / f, b: c.b / f });  // Qt.darker, close enough for this check
const out = {};
for (const [name, t] of Object.entries(JSON.parse(require("fs").readFileSync(process.argv[2], "utf8")))) {
  const fg = hex(t.foreground), bg = hex(t.background);
  const card = C.blend(fg, bg, 0.035);
  const text = { fg, accent: C.readable(hex(t.accent), card, 4.5), cool: C.readable(hex("#6cb6d9"), card, 4.5),
                 good: C.readable(hex("#5fd38d"), card, 4.5), bad: C.readable(hex(t.urgent), card, 4.5),
                 dim: C.readable(darker(fg, 1.5), card, 4.5) };
  const outline = C.blend(fg, card, C.alphaFor(fg, card, 3, 0.18));
  out[name] = Object.fromEntries([...Object.entries(text).map(([k, c]) => [k, C.ratio(c, card)]), ["outline", C.ratio(outline, card)]]);
}
console.log(JSON.stringify(out));
"""


def _ratios():
    run = subprocess.run(["node", "-e", CHECK, str(JS), str(THEMES)], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def test_all_themes_are_covered():
    assert len(json.loads(THEMES.read_text())) >= 22


def test_text_reaches_4_5_and_outlines_3_in_every_theme():
    failures = []
    for theme, ratios in _ratios().items():
        for role, r in ratios.items():
            need = 3.0 if role == "outline" else 4.5
            if role != "fg" and r < need - 1e-6:
                failures.append(f"{theme} {role} {r:.2f} < {need}")
    assert not failures, failures


def test_readable_keeps_colors_that_already_pass():
    run = subprocess.run(["node", "-e", r"""
      const src = require("fs").readFileSync(process.argv[1], "utf8").replace(/^\.pragma library\s*/, "");
      const m = { exports: {} }; new Function("module", src)(m);
      const black = {r: 0, g: 0, b: 0}, white = {r: 1, g: 1, b: 1};
      console.log(JSON.stringify([m.exports.readable(white, black, 4.5), m.exports.readable({r: .2, g: .2, b: .2}, black, 4.5)]));
    """, str(JS)], capture_output=True, text=True, check=True)
    kept, nudged = json.loads(run.stdout)
    assert kept == {"r": 1, "g": 1, "b": 1}          # already readable: unchanged
    assert nudged["r"] > 0.2 and nudged["r"] < 1      # moved toward white, but not all the way
