import importlib
import os
import stat

import pytest

import thermoslop.config


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                     ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    config = importlib.reload(thermoslop.config)
    yield tmp_path, config
    monkeypatch.undo()
    importlib.reload(thermoslop.config)


def test_default_paths(xdg):
    root, config = xdg
    assert config.CONFIG_FILE == root / "config/thermoslop/config.toml"
    assert config.PAIRING_FILE == root / "data/thermoslop/pairing.json"
    assert config.STATE_FILE == root / "cache/thermoslop/state.json"
    assert config.AUDIT_FILE == root / "state/thermoslop/changes.jsonl"


def _legacy(root):
    (root / "config/ecobee").mkdir(parents=True)
    (root / "config/ecobee/config.toml").write_text('subnets = ["192.168.1.0/24"]\n')
    data = root / "data/ecobee"
    (data / "venv/bin").mkdir(parents=True)
    (data / "pairing.json").write_text("{}")
    os.chmod(data / "pairing.json", 0o600)
    (data / "charmap.json").write_text("{}")
    (root / "state/ecobee").mkdir(parents=True)
    (root / "state/ecobee/changes.jsonl").write_text("{}\n")


def test_migrates_files_and_skips_venv(xdg, capsys):
    root, config = xdg
    _legacy(root)
    moved = config.migrate_legacy()
    assert sorted(p.relative_to(root).as_posix() for p in moved) == [
        "config/thermoslop/config.toml", "data/thermoslop/charmap.json",
        "data/thermoslop/pairing.json", "state/thermoslop/changes.jsonl",
    ]
    assert stat.S_IMODE((root / "data/thermoslop/pairing.json").stat().st_mode) == 0o600
    assert (root / "data/ecobee/venv").is_dir() and not (root / "data/thermoslop/venv").exists()
    assert not (root / "config/ecobee").exists()  # emptied dirs are removed
    assert capsys.readouterr().err.count("moved") == 4
    assert config.load_config(config.CONFIG_FILE).subnets == ["192.168.1.0/24"]


def test_migrates_after_new_venv_exists(xdg):
    root, config = xdg
    _legacy(root)
    (root / "data/thermoslop/venv").mkdir(parents=True)
    config.migrate_legacy()
    assert (root / "data/thermoslop/pairing.json").exists()


def test_never_overwrites(xdg):
    root, config = xdg
    _legacy(root)
    (root / "config/thermoslop").mkdir(parents=True)
    (root / "config/thermoslop/config.toml").write_text("units = \"C\"\n")
    config.migrate_legacy()
    assert (root / "config/thermoslop/config.toml").read_text() == "units = \"C\"\n"
    assert (root / "config/ecobee/config.toml").exists()
    assert config.migrate_legacy() == []  # second run: nothing left to move


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_secure_existing_tightens_old_installs(xdg):
    root, config = xdg
    for d in (config.CONFIG_DIR, config.DATA_DIR, config.STATE_DIR, config.CACHE_DIR):
        d.mkdir(parents=True, mode=0o755)
    config.PAIRING_FILE.write_text("{}")
    os.chmod(config.PAIRING_FILE, 0o644)
    config.AUDIT_FILE.write_text("")
    config.secure_existing()
    assert [_mode(d) for d in (config.CONFIG_DIR, config.DATA_DIR, config.STATE_DIR)] == [0o700] * 3
    assert _mode(config.CACHE_DIR) == 0o755  # readings only, for the widget
    assert _mode(config.PAIRING_FILE) == _mode(config.AUDIT_FILE) == 0o600


def test_audit_log_is_private(xdg):
    root, config = xdg
    from thermoslop.guard import Guard

    Guard(config.McpConfig(), config.AUDIT_FILE).record("set_temperature", {}, "test", "ok", ["upstairs"])
    assert _mode(config.AUDIT_FILE) == 0o600 and _mode(config.STATE_DIR) == 0o700
