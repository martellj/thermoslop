"""The panel's AWAY ALL / RESUME ALL reach exactly the thermostats they count.

Runs the plugin's own house.js (what Panel.qml uses) under Node, runs the
commands it builds through bash against a pretend thermoslop, then resolves
each recorded call with the real CLI parser and target selection."""

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from thermoslop import ops
from thermoslop.cli import build_parser
from thermoslop.config import Config
from thermoslop.homekit import Home

JS = Path(__file__).parent.parent / "omarchy/martellj.thermoslop/house.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

# Two thermostats with no house (the panel's OTHER group) and one per named house.
HOUSE_OF = {"garage": None, "shop": None, "main-floor": "home", "cabin-main-floor": "cabin"}

BUILD = r"""
const src = require("fs").readFileSync(process.argv[1], "utf8").replace(/^\.pragma library\s*/, "");
const m = { exports: {} };
new Function("module", src)(m);
const quote = v => "'" + String(v || "").replace(/'/g, "'\\''") + "'";  // Omarchy's Util.shellQuote
const [action, house, aliases] = JSON.parse(process.argv[2]);
console.log(m.exports.command("THERMOSLOP_SOURCE=widget thermoslop", action, house, aliases, quote));
"""


class FakeHome(Home):
    def __init__(self):
        super().__init__(Config(houses={"home": ["192.168.1.0/24"], "cabin": ["192.168.2.0/24"]}))

    def aliases(self):
        return sorted(HOUSE_OF)

    def house(self, alias):
        return HOUSE_OF[alias]


def reached(tmp_path, action, house):
    """Aliases a group button's command acts on, as the CLI would resolve them."""
    group = [a for a, h in HOUSE_OF.items() if (h or "") == house]
    command = subprocess.run(["node", "-e", BUILD, str(JS), json.dumps([action, house, group])],
                             capture_output=True, text=True, check=True).stdout.strip()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "thermoslop"
    fake.write_text(f'#!/bin/bash\nprintf "%q " "$@" >> {shlex.quote(str(tmp_path / "calls"))}; echo >> {shlex.quote(str(tmp_path / "calls"))}\n')
    fake.chmod(0o755)
    (tmp_path / "calls").unlink(missing_ok=True)
    subprocess.run(["bash", "-c", command], env={"PATH": f"{bin_dir}:/usr/bin:/bin"}, check=True)
    hit = []
    for line in (tmp_path / "calls").read_text().splitlines():
        args = build_parser().parse_args(shlex.split(line))
        assert args.command == action
        hit += ops.targets(FakeHome(), args.thermostat, args.house, args.all)
    return group, hit


@pytest.mark.parametrize("action", ["away", "resume"])
def test_unassigned_group_reaches_only_its_own_thermostats(tmp_path, action):
    group, hit = reached(tmp_path, action, "")
    assert hit == group == ["garage", "shop"]  # not main-floor or cabin-main-floor


@pytest.mark.parametrize("action", ["away", "resume"])
@pytest.mark.parametrize("house", ["home", "cabin"])
def test_named_house_stays_in_its_house(tmp_path, action, house):
    group, hit = reached(tmp_path, action, house)
    assert hit == group


def test_odd_aliases_stay_one_argument(tmp_path):
    command = subprocess.run(["node", "-e", BUILD, str(JS), json.dumps(["away", "", ["it's; rm -rf ~"]])],
                             capture_output=True, text=True, check=True).stdout.strip()
    assert command == "THERMOSLOP_SOURCE=widget thermoslop away -t 'it'\\''s; rm -rf ~'"
