"""Paths and user configuration (~/.config/ecobee/config.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "ecobee"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "ecobee"
PAIRING_FILE = DATA_DIR / "pairing.json"
CHARMAP_FILE = DATA_DIR / "charmap.json"
STATE_FILE = _xdg("XDG_CACHE_HOME", ".cache") / "ecobee" / "state.json"


@dataclass
class Config:
    # Subnets to scan with unicast DNS-SD when multicast discovery finds nothing
    # (VMs behind NAT, separate VLANs). e.g. ["192.168.1.0/24"]
    subnets: list[str] = field(default_factory=list)
    # Alias of the thermostat commands act on when -t is not given.
    default: str | None = None
    # "F" or "C"; None follows each thermostat's display setting.
    units: str | None = None
    # Seconds between full polls in `ecobee watch` (events arrive in between).
    poll_interval: int = 60


def load_config(path: Path = CONFIG_FILE) -> Config:
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Config()
    units = raw.get("units")
    return Config(
        subnets=list(raw.get("subnets", [])),
        default=raw.get("default"),
        units=units.upper() if units else None,
        poll_interval=int(raw.get("poll_interval", 60)),
    )
