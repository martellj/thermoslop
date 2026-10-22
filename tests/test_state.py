from aiohomekit.model import Accessories, Accessory
from aiohomekit.model.characteristics import CharacteristicsTypes as CT
from aiohomekit.model.services import ServicesTypes as ST

from ecobee.cli import _parse_temp, format_state
from ecobee.discovery import _parse_txt
from ecobee.homekit import slugify, thermostat_state, to_c


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
