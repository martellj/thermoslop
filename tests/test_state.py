import pytest
from aiohomekit.model import Accessories, Accessory
from aiohomekit.model.characteristics import CharacteristicsTypes as CT
from aiohomekit.model.services import ServicesTypes as ST

from thermoslop.cli import _parse_temp, format_state
from thermoslop.discovery import _parse_txt
from thermoslop.homekit import slugify, thermostat_state, to_c


def _ecobee(mode=1, action=1, comfort=0, units=1) -> Accessories:
    accessories = Accessories()
    acc = Accessory.create_with_info(1, "Main Floor", "ecobee Inc.", "ecobee3 lite", "1", "4.8")
    t = acc.add_service(ST.THERMOSTAT)
    t.add_char(CT.TEMPERATURE_CURRENT, value=21.0)
    t.add_char(CT.TEMPERATURE_TARGET, value=20.0)
    t.add_char(CT.TEMPERATURE_HEATING_THRESHOLD, value=20.0)
    t.add_char(CT.TEMPERATURE_COOLING_THRESHOLD, value=24.5)
    t.add_char(CT.HEATING_COOLING_TARGET, value=mode)
    t.add_char(CT.HEATING_COOLING_CURRENT, value=action)
    t.add_char(CT.RELATIVE_HUMIDITY_CURRENT, value=41.6)
    t.add_char(CT.TEMPERATURE_UNITS, value=units)
    t.add_char(CT.VENDOR_ECOBEE_CURRENT_MODE, value=comfort)
    occ = acc.add_service(ST.OCCUPANCY_SENSOR)
    occ.add_char(CT.OCCUPANCY_DETECTED, value=1)
    accessories.add_accessory(acc)

    sensor = Accessory.create_with_info(2, "Bedroom", "ecobee Inc.", "EBERS41", "2", "1.0")
    sensor.add_service(ST.TEMPERATURE_SENSOR).add_char(CT.TEMPERATURE_CURRENT, value=19.5)
    sensor.add_service(ST.OCCUPANCY_SENSOR).add_char(CT.OCCUPANCY_DETECTED, value=0)
    accessories.add_accessory(sensor)
    return accessories


def test_heat_mode_fahrenheit():
    st = thermostat_state("main-floor", _ecobee())
    assert st["name"] == "Main Floor"
    assert st["units"] == "F"
    assert st["temperature"] == 69.8
    assert st["target"] == 68
    assert (st["mode"], st["action"], st["comfort"]) == ("heat", "heating", "home")
    assert st["humidity"] == 42
    assert st["sensors"] == [
        {"name": "Main Floor", "temperature": None, "occupied": True},
        {"name": "Bedroom", "temperature": 67.1, "occupied": False},
    ]


def test_celsius_override_and_auto():
    st = thermostat_state("main-floor", _ecobee(mode=3, action=0, comfort=2), units="C")
    assert st["units"] == "C"
    assert st["target"] is None
    assert (st["heat_setpoint"], st["cool_setpoint"]) == (20.0, 24.5)
    assert (st["action"], st["comfort"]) == ("idle", "away")


def test_off_mode_reports_off_action():
    st = thermostat_state("main-floor", _ecobee(mode=0, action=0))
    assert (st["mode"], st["action"]) == ("off", "off")


def test_format_state():
    text = format_state(thermostat_state("main-floor", _ecobee()))
    assert text.splitlines()[0] == "Main Floor: 69.8°F · ▲ heating · set 68°F (heat) · home · 42% RH"
    assert "    Bedroom: 67.1°F, empty" in text


def test_helpers():
    assert to_c(68, "F") == 20.0
    assert to_c(21, "C") == 21
    assert _parse_temp("70") == (70.0, False)
    assert _parse_temp("+1") == (1.0, True)
    assert _parse_temp("-1.5") == (-1.5, True)
    assert slugify("Main Floor") == "main-floor"
    assert _parse_txt(b"\x04c#=6\x14id=AA:BB:CC:DD:EE:FF\x0fmd=ecobee3 lite") == {
        "c#": "6",
        "id": "AA:BB:CC:DD:EE:FF",
        "md": "ecobee3 lite",
    }


def test_manual_hold():
    st = thermostat_state("main-floor", _ecobee(comfort=3), units="F")
    assert st["comfort"] == "hold"


def test_house_of():
    from thermoslop.config import Config

    config = Config(houses={"home": ["192.168.1.0/24"], "cabin": ["192.168.2.0/24"]})
    assert config.house_of("192.168.2.31") == "cabin"
    assert config.house_of("192.168.1.186") == "home"
    assert config.house_of("10.0.0.5") is None


def test_status_groups_by_house():
    from thermoslop.cli import format_states

    home = thermostat_state("main-floor", _ecobee(), house="home")
    cabin = thermostat_state("cabin-main-floor", _ecobee(), house="cabin")
    text = format_states([home, cabin])
    assert text.startswith("Home\n  Main Floor:") and "\n\nCabin\n  Main Floor:" in text
    assert format_states([home]).startswith("Main Floor:")


def _readings(hk, hours_of_data, trend_hours, t0=1_000_000):
    for minute in range(0, int(hours_of_data * 60)):  # a reading every minute
        hk.write_cache(
            [{"alias": "upstairs", "available": True, "temperature": 70 + minute / 60, "updated_at": t0 + minute * 60}],
            trend_hours=trend_hours,
        )
    return hk.read_cache()


@pytest.fixture
def hk(tmp_path, monkeypatch):
    import thermoslop.homekit as hk

    monkeypatch.setattr(hk, "STATE_FILE", tmp_path / "state.json")
    return hk


def test_history_samples_every_5_minutes_within_the_window(hk):
    cache = _readings(hk, 7, trend_hours=6)
    series = cache["history"]["upstairs"]
    assert all(b[0] - a[0] == 300 for a, b in zip(series, series[1:]))
    assert series[-1][0] - series[0][0] < 6 * 3600 and len(series) == 72
    assert cache["trend_hours"] == 6
    assert "history" not in cache["thermostats"]["upstairs"]


def test_history_default_window_is_24_hours(hk, tmp_path):
    from thermoslop.config import load_config

    (tmp_path / "config.toml").write_text("")
    hours = load_config(tmp_path / "config.toml").trend_hours
    assert hours == 24
    assert len(_readings(hk, 25, trend_hours=hours)["history"]["upstairs"]) == 288


def test_history_only_recorded_by_the_watcher(hk):
    hk.write_cache([{"alias": "upstairs", "available": True, "temperature": 70, "updated_at": 1}])  # CLI write
    assert "history" not in hk.read_cache()
    _readings(hk, 1, trend_hours=24)
    hk.write_cache([{"alias": "upstairs", "available": False, "updated_at": 10**7}], trend_hours=24)
    assert len(hk.read_cache()["history"]["upstairs"]) == 12  # unavailable readings aren't recorded
    hk.write_cache([], remove=["upstairs"])
    assert "upstairs" not in hk.read_cache()["history"]


def test_trend_off_drops_history(hk):
    _readings(hk, 1, trend_hours=24)
    cache = _readings(hk, 1, trend_hours=0, t0=2_000_000)
    assert "history" not in cache and cache["trend_hours"] == 0


def test_trend_hours_validated(tmp_path):
    from thermoslop.config import load_config

    (tmp_path / "config.toml").write_text("trend_hours = 1000\n")
    with pytest.raises(ValueError, match="trend_hours"):
        load_config(tmp_path / "config.toml")


def test_mdns_skips_tunnel_and_loopback_interfaces(monkeypatch):
    import types

    import ifaddr

    from thermoslop.discovery import lan_interfaces

    def adapter(name, *ips):
        return types.SimpleNamespace(name=name, nice_name=name, ips=[types.SimpleNamespace(ip=i) for i in ips])

    monkeypatch.setattr(ifaddr, "get_adapters", lambda: [
        adapter("lo0", "127.0.0.1"), adapter("en0", "192.168.1.248", ("fe80::1", 0, 0)),
        adapter("utun4", "100.100.100.100"), adapter("tailscale0", "100.100.100.100"), adapter("en5", "169.254.3.3"),
    ])
    assert lan_interfaces() == ["192.168.1.248"]
    monkeypatch.setattr(ifaddr, "get_adapters", lambda: [adapter("utun4", "100.100.100.100")])
    assert lan_interfaces() is None  # nothing usable: let zeroconf decide
