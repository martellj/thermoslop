import pytest

from thermoslop.config import McpConfig, degrees_in, load_config, parse_degrees


def test_parse_degrees():
    assert parse_degrees("55F") == (55, "F")
    assert parse_degrees("12.5 c") == (12.5, "C")
    assert parse_degrees(70) == (70, "F")
    with pytest.raises(ValueError):
        parse_degrees("warm")


def test_degrees_in_other_units():
    assert degrees_in("13C", "C") == 13
    assert round(degrees_in("13C", "F"), 1) == 55.4
    assert round(degrees_in("80F", "C"), 1) == 26.7


def test_mcp_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('subnets = ["192.168.1.0/24"]\n')
    mcp = load_config(path).mcp
    assert (mcp.read_only, mcp.allow_off, mcp.max_changes_per_hour) == (False, False, 20)
    assert (mcp.min_setpoint, mcp.max_setpoint, mcp.http_port, mcp.allow) == ("55F", "80F", 8765, [])


def test_mcp_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[mcp]\nmin_setpoint = "13C"\nmax_setpoint = "25C"\nallow_off = true\nallow = ["alice@example.com"]\nunits = "c"\n')
    mcp = load_config(path).mcp
    assert (mcp.min_setpoint, mcp.allow_off, mcp.allow, mcp.units) == ("13C", True, ["alice@example.com"], "C")


def test_mcp_rejects_inverted_range():
    with pytest.raises(ValueError):
        McpConfig(min_setpoint="80F", max_setpoint="55F")


def test_mcp_unknown_key(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[mcp]\nallow_of = true\n")
    with pytest.raises(ValueError, match="allow_of"):
        load_config(path)


@pytest.mark.parametrize("entry", ["alice@", "alices-laptop", "node:abc", "node:abc@alice"])
def test_mcp_allow_rejects_weak_identities(entry):
    with pytest.raises(ValueError, match="allow"):
        McpConfig(allow=[entry])


def test_mcp_allow_accepts_logins_and_devices():
    McpConfig(allow=["alice@example.com", "node:nJZFmD3fA721CNTRL@alice@example.com"])
