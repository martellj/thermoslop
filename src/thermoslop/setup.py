"""`thermoslop setup`: install (or `--remove`) the background services.

Linux: systemd user units. macOS: launchd agents. Both point at the
`thermoslop` that's running setup, so they work for uv tool, pipx and venv
installs alike. The watcher is enabled and started; the MCP HTTP service is
installed but left off unless it was already on. Pairings, config, the state
cache and the change log are never touched.

On Omarchy, setup also offers to add the bar widget plugin.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from thermoslop import APP

PLUGIN_ID = "martellj.thermoslop"
PLUGIN_URL = "https://github.com/martellj/thermoslop-omarchy"
LAUNCHD_PREFIX = "io.github.martellj.thermoslop"
SERVICES = {
    "watch": ("ThermoSlop HomeKit watcher (keeps the bar widget's state fresh)", ["watch"]),
    "mcp": ("ThermoSlop MCP server on the tailnet (for AI clients on other machines)", ["mcp", "--http"]),
}

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def executable() -> str:
    """Absolute path of the running `thermoslop`, unresolved: a stable symlink
    such as ~/.local/bin/thermoslop survives upgrades, the target may not."""
    argv0 = sys.argv[0]
    if argv0.endswith("__main__.py"):  # `python -m thermoslop`: point at the installed command instead
        return shutil.which(APP) or str(Path(argv0).absolute())
    if os.sep in argv0 or (os.altsep and os.altsep in argv0):
        return str(Path(argv0).absolute())
    return shutil.which(argv0) or shutil.which(APP) or str(Path(argv0).absolute())


# ---- Linux (systemd --user)


def systemd_unit(name: str, binary: str) -> str:
    description, args = SERVICES[name]
    # Quote the path: systemd splits ExecStart on spaces otherwise.
    exec_start = " ".join([f'"{binary}"', *args])
    wants = "Wants=network-online.target\n" if name == "watch" else ""
    restart = "Restart=always\nRestartSec=10" if name == "watch" else (
        "# Tailscale may not be up yet at login; keep retrying.\nRestart=always\nRestartSec=15")
    return (
        f"[Unit]\nDescription={description}\nAfter=network-online.target\n{wants}\n"
        f"[Service]\nExecStart={exec_start}\n{restart}\n\n"
        f"[Install]\nWantedBy=default.target\n"
    )


def _units_dir(home: Path) -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "systemd" / "user"


def has_systemd_user() -> bool:
    """A systemd user manager we can talk to (not Alpine/OpenRC, Void/runit, containers…)."""
    return bool(shutil.which("systemctl")) and Path("/run/systemd/system").is_dir()


def without_systemd(binary: str) -> list[str]:
    """What to do instead, for service managers setup doesn't drive."""
    return [
        "no systemd user session here, so nothing was installed. Keep the watcher running with your own",
        f"service manager or autostart; the command is: \"{binary}\" watch",
        "  runit (Void):      a user service whose run script is: exec \"" + binary + "\" watch",
        "  OpenRC (Alpine):   a user service (rc-update -U add), or your session's autostart",
        "  any desktop/WM:    an autostart entry (e.g. Hyprland: exec-once = thermoslop watch)",
    ]


def setup_linux(home: Path, binary: str, run: Runner, remove: bool = False) -> list[str]:
    if not has_systemd_user():
        return [] if remove else without_systemd(binary)
    done = []
    units = _units_dir(home)
    if remove:
        for name in SERVICES:
            unit = f"{APP}-{name}.service"
            run(["systemctl", "--user", "disable", "--now", unit])
            path = units / unit
            if path.exists() or path.is_symlink():
                path.unlink()
                done.append(f"removed {unit}")
        run(["systemctl", "--user", "daemon-reload"])
        return done
    mcp_was_on = run(["systemctl", "--user", "is-enabled", "--quiet", f"{APP}-mcp.service"]).returncode == 0
    units.mkdir(parents=True, exist_ok=True)
    for name in SERVICES:
        path = units / f"{APP}-{name}.service"
        if path.is_symlink():
            path.unlink()  # a checkout's symlinked unit from install.sh before setup existed
        path.write_text(systemd_unit(name, binary))
        done.append(f"wrote {path}")
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", f"{APP}-watch.service"])
    run(["systemctl", "--user", "restart", f"{APP}-watch.service"])
    done.append(f"{APP}-watch enabled and started")
    if mcp_was_on:
        run(["systemctl", "--user", "restart", f"{APP}-mcp.service"])
        done.append(f"{APP}-mcp was enabled: restarted")
    else:
        done.append(f"{APP}-mcp installed, off (enable: systemctl --user enable --now {APP}-mcp)")
    return done


# ---- macOS (launchd)


def launchd_plist(name: str, binary: str, home: Path) -> bytes:
    _, args = SERVICES[name]
    logs = home / "Library" / "Logs" / APP
    return plistlib.dumps({
        "Label": f"{LAUNCHD_PREFIX}.{name}",
        "ProgramArguments": [binary, *args],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        # launchd starts agents with a bare PATH; `thermoslop mcp --http` needs
        # to find `tailscale` (Homebrew or the app's CLI).
        "EnvironmentVariables": {"PATH": ":".join([
            str(Path(binary).parent), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
        ])},
        "StandardOutPath": str(logs / f"{name}.log"),
        "StandardErrorPath": str(logs / f"{name}.log"),
    })


def setup_macos(home: Path, binary: str, run: Runner, remove: bool = False) -> list[str]:
    done = []
    agents = home / "Library" / "LaunchAgents"
    domain = f"gui/{os.getuid()}"
    if remove:
        for name in SERVICES:
            path = agents / f"{LAUNCHD_PREFIX}.{name}.plist"
            run(["launchctl", "bootout", f"{domain}/{LAUNCHD_PREFIX}.{name}"])
            if path.exists():
                path.unlink()
                done.append(f"removed {path.name}")
        return done
    mcp_was_on = run(["launchctl", "print", f"{domain}/{LAUNCHD_PREFIX}.mcp"]).returncode == 0
    agents.mkdir(parents=True, exist_ok=True)
    (home / "Library" / "Logs" / APP).mkdir(parents=True, exist_ok=True)
    for name in SERVICES:
        path = agents / f"{LAUNCHD_PREFIX}.{name}.plist"
        path.write_bytes(launchd_plist(name, binary, home))
        done.append(f"wrote {path}")
    for name in ["watch"] + (["mcp"] if mcp_was_on else []):
        label = f"{domain}/{LAUNCHD_PREFIX}.{name}"
        run(["launchctl", "bootout", label])  # reload with the new plist
        run(["launchctl", "bootstrap", domain, str(agents / f"{LAUNCHD_PREFIX}.{name}.plist")])
        done.append(f"{LAUNCHD_PREFIX}.{name} loaded")
    if not mcp_was_on:
        done.append(f"MCP agent installed, off (enable: launchctl bootstrap {domain} "
                    f"~/Library/LaunchAgents/{LAUNCHD_PREFIX}.mcp.plist)")
    return done


# ---- Omarchy plugin


def offer_plugin(home: Path, run: Runner, assume_yes: bool, interactive: bool) -> list[str]:
    """On Omarchy only: add the bar widget plugin if it isn't there."""
    if not shutil.which("omarchy"):
        return []
    plugins = home / ".config" / "omarchy" / "plugins"
    if (plugins / PLUGIN_ID).exists():
        return [f"Omarchy plugin {PLUGIN_ID} already installed"]
    command = ["omarchy", "plugin", "add", PLUGIN_URL, "--enable", "--yes"]
    if not assume_yes:
        if not interactive:
            return [f"Omarchy detected: add the bar widget with `{' '.join(command[:-1])}`"]
        answer = input(f"Add the ThermoSlop bar widget to Omarchy ({PLUGIN_URL})? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            return [f"skipped the plugin; add it later with `{' '.join(command[:-1])}`"]
    result = run(command)
    if result.returncode != 0:
        return [f"couldn't add the plugin: {(result.stderr or result.stdout).strip()}"]
    return [f"added and enabled Omarchy plugin {PLUGIN_ID}"]


def setup(remove: bool = False, assume_yes: bool = False, plugin: bool = True,
          home: Path | None = None, run: Runner = _run, platform: str = sys.platform) -> list[str]:
    home = home or Path.home()
    binary = executable()
    if platform.startswith("linux"):
        done = setup_linux(home, binary, run, remove)
    elif platform == "darwin":
        done = setup_macos(home, binary, run, remove)
    else:
        raise SystemExit(f"{APP} setup supports Linux (systemd) and macOS (launchd), not {platform}")
    if not remove and plugin:
        done += offer_plugin(home, run, assume_yes, sys.stdin.isatty())
    if remove:
        done.append("kept your pairings, config, state and change log")
    return done
