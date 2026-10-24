"""The panel's SetpointControl.qml, run headless against a pretend thermoslop.

Needs Quickshell and a Wayland session, so it's skipped elsewhere (CI)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent / "qml"
PLUGIN = Path(__file__).parent.parent / "omarchy/martellj.thermoslop"

pytestmark = pytest.mark.skipif(
    not shutil.which("quickshell") or not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs quickshell and a Wayland session",
)


def test_reads_first_sends_absolute_values_and_latest_wins(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "thermoslop").symlink_to(HERE / "fake-thermoslop")
    shell = tmp_path / "shell"
    shell.mkdir()
    shutil.copy(HERE / "setpoint/shell.qml", shell)
    shutil.copy(PLUGIN / "SetpointControl.qml", shell)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DIR": str(tmp_path)}
    out = subprocess.run(["quickshell", "-p", str(shell)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=40).stdout
    log = {}
    for line in (out or "").splitlines():
        if "HARNESS " in line:
            key, _, rest = line.split("HARNESS ", 1)[1].partition(" ")
            log[key] = rest
    calls = (tmp_path / "calls.log").read_text().splitlines()

    # Buttons are off until the thermostat has been read; the early press waits.
    assert log["unread"] == "adjustable=false"
    assert log["reading"] == "adjustable=false phase=reading queued=1"
    # One read, then absolute values only; presses made while saving are sent
    # next as one value, so 64 + 4 presses ends at exactly 68.
    assert calls[0] == "status --live --json -t cabin"
    assert [c for c in calls if c.startswith("set")] == [
        "set 65 -t cabin --json", "set 68 -t cabin --json", "set 67 -t cabin --json"]
    assert log["during-send"] == "phase=sending draft=68"
    assert log["settled"] == "base=68 phase=synced draft=null"
    # The thermostat took 66.5 for 67: the card shows that, and says so.
    assert log["adjusted"] == "base=66.5 phase=synced note=thermostat set 66.5°"
