"""Paths and user configuration (~/.config/thermoslop/config.toml)."""

from __future__ import annotations

import ipaddress
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from thermoslop import APP


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP
CONFIG_FILE = CONFIG_DIR / "config.toml"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / APP
PAIRING_FILE = DATA_DIR / "pairing.json"
CHARMAP_FILE = DATA_DIR / "charmap.json"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / APP
STATE_FILE = CACHE_DIR / "state.json"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / APP
AUDIT_FILE = STATE_DIR / "changes.jsonl"

# Readable by the owner only: the pairing key (full control of the thermostats),
# config, and the audit log of tailnet callers. The cache holds only readings.
PRIVATE_DIRS = (CONFIG_DIR, DATA_DIR, STATE_DIR)


def private_dir(path: Path) -> Path:
    """mkdir -m 700, tightening it if it already exists."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def secure_existing() -> None:
    """Tighten installs made before the directories were created 700."""
    for directory in PRIVATE_DIRS:
        if directory.is_dir():
            os.chmod(directory, 0o700)
    for path in (PAIRING_FILE, AUDIT_FILE, AUDIT_FILE.with_suffix(".jsonl.1")):
        if path.exists():
            os.chmod(path, 0o600)


# Before the rename the project was called "ecobee"; its files are moved over.
LEGACY = "ecobee"


def migrate_legacy(dirs: tuple[Path, ...] = (CONFIG_DIR, DATA_DIR, CACHE_DIR, STATE_DIR)) -> list[Path]:
    """Move files from each old `…/ecobee/` dir into the matching `…/thermoslop/` dir.

    Per file, so it still works after the installer has created the new venv.
    Never overwrites, and skips the old venv (it can't be moved; the installer
    builds a new one). Returns the new paths.
    """
    moved = []
    for new_dir in dirs:
        old_dir = new_dir.with_name(LEGACY)
        if not old_dir.is_dir():
            continue
        for old in sorted(old_dir.iterdir()):
            new = new_dir / old.name
            if old.name == "venv" or not old.is_file() or new.exists():
                continue
            new_dir.mkdir(parents=True, exist_ok=True)
            old.replace(new)  # a rename, so pairing.json keeps mode 600
            print(f"{APP}: moved {old} to {new}", file=sys.stderr)
            moved.append(new)
        try:
            old_dir.rmdir()
        except OSError:
            pass  # not empty: the old venv, or files we wouldn't overwrite
    return moved


def parse_degrees(text: str | int | float) -> tuple[float, str]:
    """'55F' / '13C' / '12.5 c' -> (value, unit). A bare number is Fahrenheit."""
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*°?\s*([FfCc]?)\s*", str(text))
    if not m:
        raise ValueError(f"not a temperature: {text!r} (use e.g. \"55F\" or \"13C\")")
    return float(m.group(1)), (m.group(2) or "F").upper()


def degrees_in(text: str, units: str) -> float:
    value, unit = parse_degrees(text)
    if unit == units:
        return value
    return value * 9 / 5 + 32 if units == "F" else (value - 32) * 5 / 9


@dataclass
class McpConfig:
    """Guardrails for changes made through `thermoslop mcp` (the CLI isn't limited)."""

    read_only: bool = False
    min_setpoint: str = "55F"
    max_setpoint: str = "80F"
    allow_off: bool = False
    max_changes_per_hour: int = 20
    http_port: int = 8765
    # Tailnet login names ("alice@" matches any login starting with it) or node
    # names allowed over HTTP. Empty means the owner of this node.
    allow: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        low, high = parse_degrees(self.min_setpoint), parse_degrees(self.max_setpoint)
        if degrees_in(self.min_setpoint, "F") >= degrees_in(self.max_setpoint, "F"):
            raise ValueError(f"[mcp] min_setpoint {low} must be below max_setpoint {high}")


@dataclass
class Config:
    # Subnets to scan with unicast DNS-SD when multicast discovery finds nothing
    # (VMs behind NAT, separate VLANs). e.g. ["192.168.1.0/24"]. Includes
    # every house's subnets.
    subnets: list[str] = field(default_factory=list)
    # House name -> its subnets, e.g. {"cabin": ["192.168.2.0/24"]}. A
    # thermostat belongs to the house whose subnet holds its IP.
    houses: dict[str, list[str]] = field(default_factory=dict)
    # Alias of the thermostat commands act on when -t is not given.
    default: str | None = None
    # "F" or "C"; None follows each thermostat's display setting.
    units: str | None = None
    # Seconds between full polls in `thermoslop watch` (events arrive in between).
    poll_interval: int = 60
    # Hours of temperature history the watcher keeps for the widget's trend line; 0 turns it off.
    trend_hours: float = 24
    mcp: McpConfig = field(default_factory=McpConfig)

    def house_of(self, address: str | None) -> str | None:
        if not address:
            return None
        ip = ipaddress.ip_address(address)
        for house, subnets in self.houses.items():
            if any(ip in ipaddress.ip_network(s, strict=False) for s in subnets):
                return house
        return None


def _trend_hours(value) -> float:
    hours = float(value)
    if not 0 <= hours <= 24 * 7:
        raise ValueError(f"trend_hours must be between 0 and 168, got {value!r}")
    return hours


def _mcp(raw: dict) -> McpConfig:
    known = set(McpConfig.__dataclass_fields__)
    if unknown := set(raw) - known:
        raise ValueError(f"unknown [mcp] setting(s): {', '.join(sorted(unknown))} (known: {', '.join(sorted(known))})")
    return McpConfig(**raw)


def load_config(path: Path = CONFIG_FILE) -> Config:
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Config()
    units = raw.get("units")
    houses = {name: list(subnets) for name, subnets in raw.get("houses", {}).items()}
    subnets = list(raw.get("subnets", []))
    subnets += [s for nets in houses.values() for s in nets if s not in subnets]
    return Config(
        subnets=subnets,
        houses=houses,
        default=raw.get("default"),
        units=units.upper() if units else None,
        poll_interval=int(raw.get("poll_interval", 60)),
        trend_hours=_trend_hours(raw.get("trend_hours", 24)),
        mcp=_mcp(raw.get("mcp", {})),
    )
