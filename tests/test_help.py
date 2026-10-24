"""The CLI documents itself: every command and option has help, examples parse."""

import argparse
import json
import shlex
import socket

import pytest

from thermoslop import cli, cli_help


def _subparsers():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return parser, sub.choices


def test_every_command_has_a_description_and_examples():
    _, commands = _subparsers()
    assert set(commands) == set(cli_help.COMMANDS)
    for name, p in commands.items():
        assert p.description and len(p.description) > 40, name
        assert "examples:" in (p.epilog or ""), name


def test_every_visible_option_has_help():
    _, commands = _subparsers()
    for name, p in commands.items():
        for a in p._actions:
            if a.help == argparse.SUPPRESS:
                continue
            assert a.help, f"{name}: {a.option_strings or a.dest} has no help"


def test_examples_parse():
    parser, _ = _subparsers()
    for name, (_, _, _, examples) in cli_help.COMMANDS.items():
        for example in examples:
            words = shlex.split(example.split("#")[0].split(">")[0])
            if words[0] == "eval":  # eval "$(thermoslop completion bash)"
                words = shlex.split(words[1].strip("$()"))
            assert words[0] == "thermoslop", example
            parser.parse_args(words[1:])  # SystemExit on a bad example


@pytest.mark.parametrize("command", ["pair", "discover", "setup", "watch", "mcp"])
def test_no_thermostat_option_where_it_does_nothing(command, capsys):
    with pytest.raises(SystemExit):
        cli.main([command, "--help"])
    assert "--thermostat" not in capsys.readouterr().out


def test_ignored_options_still_parse_for_old_scripts():
    parser, _ = _subparsers()
    assert parser.parse_args(["discover", "-t", "x", "--demo"]).demo


def test_top_level_help_groups_commands_and_says_where_files_are(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "first steps:" in out and "control and history:" in out and "pairing:" in out
    assert "config.toml" in out and "THERMOSLOP_SOURCE" in out
    assert "==SUPPRESS==" not in out


def test_set_help_explains_the_default_thermostat(capsys):
    with pytest.raises(SystemExit):
        cli.main(["set", "--help"])
    assert "`default` thermostat" in capsys.readouterr().out.replace("\n", " ")


def test_mode_help_explains_off(capsys):
    with pytest.raises(SystemExit):
        cli.main(["mode", "--help"])
    assert "no heating or cooling" in capsys.readouterr().out.replace("\n", " ")


def test_help_command(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["help", "set"])
    assert e.value.code == 0 and "usage: thermoslop set" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["help", "nope"])
    assert e.value.code == 2 and "commands: status" in capsys.readouterr().err


def test_completion_aliases_read_the_pairing_file_without_network(tmp_path, monkeypatch, capsys):
    pairing = tmp_path / "pairing.json"
    pairing.write_text(json.dumps({"upstairs": {}, "cabin": {}}))
    monkeypatch.setattr(cli_help, "PAIRING_FILE", pairing)

    def no_network(*a, **k):
        raise AssertionError("completion opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    with pytest.raises(SystemExit) as e:
        cli.main(["completion", "--aliases"])
    assert e.value.code == 0
    assert capsys.readouterr().out.split() == ["cabin", "upstairs"]


def test_completion_scripts_cover_commands_and_modes():
    parser, _ = _subparsers()
    script = cli_help.bash(parser)
    assert "complete -F _thermoslop thermoslop" in script
    assert "status set mode" in script and "off heat cool auto" in script
    assert "complete -c thermoslop" in cli_help.fish(parser)
    assert "bashcompinit" in cli_help.zsh(parser)
