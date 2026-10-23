"""`thermoslop setup` with fake systemctl/launchctl/omarchy."""

import plistlib
import subprocess

import pytest

import thermoslop.setup as setup_mod
from thermoslop.setup import launchd_plist, setup, systemd_unit


class Recorder:
    def __init__(self, enabled=()):
        self.calls = []
        self.enabled = set(enabled)

    def __call__(self, cmd):
        self.calls.append(cmd)
        on = any(name in " ".join(cmd) for name in self.enabled)
        code = 0 if ("is-enabled" not in cmd and cmd[:2] != ["launchctl", "print"]) or on else 1
        return subprocess.CompletedProcess(cmd, code, "", "")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(setup_mod, "has_systemd_user", lambda: True)
    monkeypatch.setattr(setup_mod, "executable", lambda: "/home/a b/.local/bin/thermoslop")
    monkeypatch.setattr(setup_mod.shutil, "which", lambda name: None)  # not Omarchy unless a test says so
    return tmp_path


def test_unit_quotes_paths_with_spaces():
    unit = systemd_unit("watch", "/home/a b/.local/bin/thermoslop")
    assert 'ExecStart="/home/a b/.local/bin/thermoslop" watch' in unit
    assert "WantedBy=default.target" in unit
    assert 'ExecStart="/x/thermoslop" mcp --http' in systemd_unit("mcp", "/x/thermoslop")


def test_linux_setup_enables_watcher_and_leaves_mcp_off(home):
    run = Recorder()
    done = setup(home=home, run=run, platform="linux")
    units = home / ".config/systemd/user"
    assert (units / "thermoslop-watch.service").exists() and (units / "thermoslop-mcp.service").exists()
    assert ["systemctl", "--user", "enable", "thermoslop-watch.service"] in run.calls
    assert not any("enable" in c and "thermoslop-mcp.service" in c and "is-enabled" not in c for c in run.calls)
    assert any("installed, off" in line for line in done)


def test_linux_setup_keeps_an_enabled_mcp_service_on(home):
    run = Recorder(enabled={"thermoslop-mcp"})
    done = setup(home=home, run=run, platform="linux")
    assert ["systemctl", "--user", "restart", "thermoslop-mcp.service"] in run.calls
    assert any("was enabled" in line for line in done)


def test_linux_setup_replaces_a_symlinked_unit(home, tmp_path):
    units = home / ".config/systemd/user"
    units.mkdir(parents=True)
    target = tmp_path / "repo-unit.service"
    target.write_text("old")
    (units / "thermoslop-watch.service").symlink_to(target)
    setup(home=home, run=Recorder(), platform="linux")
    assert not (units / "thermoslop-watch.service").is_symlink() and target.read_text() == "old"


def test_remove_keeps_data(home):
    data = home / ".local/share/thermoslop"
    data.mkdir(parents=True)
    (data / "pairing.json").write_text("{}")
    setup(home=home, run=Recorder(), platform="linux")
    done = setup(remove=True, home=home, run=Recorder(), platform="linux")
    assert not list((home / ".config/systemd/user").glob("thermoslop-*"))
    assert (data / "pairing.json").exists() and "kept your pairings" in done[-1]


def test_macos_plist(home):
    plist = plistlib.loads(launchd_plist("watch", "/Users/a b/.local/bin/thermoslop", home))
    assert plist["Label"] == "io.github.martellj.thermoslop.watch"
    assert plist["ProgramArguments"] == ["/Users/a b/.local/bin/thermoslop", "watch"]
    assert plist["KeepAlive"] and plist["RunAtLoad"]
    assert plist["EnvironmentVariables"]["PATH"].startswith("/Users/a b/.local/bin:")
    assert "/opt/homebrew/bin" in plist["EnvironmentVariables"]["PATH"]


def test_macos_setup_and_remove(home):
    run = Recorder()
    setup(home=home, run=run, platform="darwin")
    agents = home / "Library/LaunchAgents"
    assert sorted(p.name for p in agents.iterdir()) == [
        "io.github.martellj.thermoslop.mcp.plist", "io.github.martellj.thermoslop.watch.plist"]
    assert any(c[:2] == ["launchctl", "bootstrap"] and c[-1].endswith("watch.plist") for c in run.calls)
    assert not any(c[:2] == ["launchctl", "bootstrap"] and c[-1].endswith("mcp.plist") for c in run.calls)
    setup(remove=True, home=home, run=Recorder(), platform="darwin")
    assert not list(agents.iterdir())


def test_plugin_offer_only_on_omarchy(home, monkeypatch):
    run = Recorder()
    done = setup(home=home, run=run, platform="linux")
    assert not any("Omarchy" in line for line in done)
    monkeypatch.setattr(setup_mod.shutil, "which", lambda name: "/usr/bin/omarchy" if name == "omarchy" else None)
    done = setup(home=home, run=run, platform="linux", assume_yes=True)
    assert ["omarchy", "plugin", "add", setup_mod.PLUGIN_URL, "--enable", "--yes"] in run.calls
    (home / ".config/omarchy/plugins/martellj.thermoslop").mkdir(parents=True)
    assert any("already installed" in line for line in setup(home=home, run=Recorder(), platform="linux"))


def test_tailscale_cli_lookup(monkeypatch):
    import thermoslop.tailnet as tailnet
    from thermoslop.homekit import ThermoSlopError

    monkeypatch.setattr(tailnet.shutil, "which", lambda name: "/opt/homebrew/bin/tailscale")
    assert tailnet.tailscale_cli() == "/opt/homebrew/bin/tailscale"
    monkeypatch.setattr(tailnet.shutil, "which", lambda name: None)
    monkeypatch.setattr(tailnet.os.path, "exists", lambda p: p == tailnet.MAC_APP_CLI)
    assert tailnet.tailscale_cli() == tailnet.MAC_APP_CLI
    monkeypatch.setattr(tailnet.os.path, "exists", lambda p: False)
    with pytest.raises(ThermoSlopError, match="needs Tailscale"):
        tailnet.tailscale_cli()


def test_linux_without_systemd_explains_instead_of_crashing(home, monkeypatch):
    monkeypatch.setattr(setup_mod, "has_systemd_user", lambda: False)
    run = Recorder()
    done = setup(home=home, run=run, platform="linux")
    assert run.calls == [] and not (home / ".config/systemd").exists()
    assert "no systemd user session" in done[0]
    assert any('"/home/a b/.local/bin/thermoslop" watch' in line for line in done)
