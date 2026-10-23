"""The release checks: versions, built artifacts, and the plugin folder."""

import runpy
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def script(name):
    return runpy.run_path(str(SCRIPTS / name))


def _dist(tmp_path, extra=None):
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "thermoslop-9.9.9-py3-none-any.whl", "w") as z:
        z.writestr("thermoslop/cli.py", "print('hi')")
        z.writestr("thermoslop-9.9.9.dist-info/METADATA", "Name: thermoslop")
        if extra:
            z.writestr(extra, "planning notes")
    src = tmp_path / "sdist"
    (src / "thermoslop-9.9.9/src/thermoslop").mkdir(parents=True)
    (src / "thermoslop-9.9.9/src/thermoslop/cli.py").write_text("print('hi')")
    (src / "thermoslop-9.9.9/pyproject.toml").write_text("")
    with tarfile.open(dist / "thermoslop-9.9.9.tar.gz", "w:gz") as t:
        t.add(src / "thermoslop-9.9.9", arcname="thermoslop-9.9.9")
    return dist


def test_check_dist_accepts_a_clean_build(tmp_path):
    out = subprocess.run([sys.executable, SCRIPTS / "check-dist", _dist(tmp_path)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("planted", ["openspec/AUDIT.md", ".claude/settings.json", "thermoslop/pairing.json"])
def test_check_dist_rejects_private_files(tmp_path, planted):
    out = subprocess.run([sys.executable, SCRIPTS / "check-dist", _dist(tmp_path, planted)], capture_output=True, text=True)
    assert out.returncode == 1 and planted in out.stderr


def test_check_plugin_without_omarchy(tmp_path, monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["check-plugin"])
    with pytest.raises(SystemExit) as done:
        runpy.run_path(str(SCRIPTS / "check-plugin"), run_name="__main__")
    assert done.value.code == 0

    broken = tmp_path / "plugin"
    shutil.copytree(ROOT / "omarchy/martellj.thermoslop", broken)
    (broken / "Panel.qml").unlink()  # not an entry point: still fine
    (broken / "ThermoSlop.qml").unlink()  # the entry point
    monkeypatch.setattr(sys, "argv", ["check-plugin", str(broken)])
    with pytest.raises(SystemExit) as done:
        runpy.run_path(str(SCRIPTS / "check-plugin"), run_name="__main__")
    assert done.value.code == 1


def test_check_version_agrees_now():
    assert subprocess.run([sys.executable, SCRIPTS / "check-version"], capture_output=True).returncode == 0
