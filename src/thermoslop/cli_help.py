"""What `thermoslop --help`, `thermoslop help COMMAND` and the shell completions say.

The command table below is the one place a command's group, summary,
description and examples live; cli.py builds the parser from it, and the
completion scripts and the docs site's CLI reference are generated from that
parser. Examples use documentation addresses only (192.0.2.0/24).
"""

from __future__ import annotations

import argparse
import json
import shlex
import textwrap
from pathlib import Path

from thermoslop import APP
from thermoslop.config import AUDIT_FILE, CONFIG_FILE, PAIRING_FILE, STATE_FILE, load_config

DOCS_URL = "https://github.com/martellj/thermoslop#readme"

ONE = ("Without -t it uses the `default` thermostat from the config, or the only "
       "one paired; with several paired and no default it asks you to pick one.")
MANY = ("-t picks one thermostat, --house every one in that house, --all every "
        "paired thermostat. " + ONE)

GROUPS = ["control", "pairing", "services", "troubleshooting"]
GROUP_TITLES = {
    "control": "Control and history",
    "pairing": "Pairing",
    "services": "Services and integrations",
    "troubleshooting": "Troubleshooting",
}

# name: (group, summary, description, examples)
COMMANDS: dict[str, tuple[str, str, str, list[str]]] = {
    "status": ("control", "current temperature, setpoints, mode and sensors",
               "Show each thermostat's temperature, humidity, setpoints, mode, comfort "
               "setting and remote sensors. It uses the watcher's recent readings when "
               "they're fresh, and asks the thermostats otherwise (or always, with "
               "--live). Without -t or --house it shows every paired thermostat.",
               ["thermoslop status", "thermoslop status -t upstairs --live", "thermoslop status --house cabin --json"]),
    "set": ("control", "set the target temperature: 70, +1, -2, or --heat/--cool",
            "Set the target temperature, in the thermostat's own units. A plain number "
            "is absolute; +N and -N change it from the value the thermostat reports "
            "right now. In auto mode, set both ends with --heat and --cool, or move "
            "both with +N/-N. The result is read back from the thermostat to confirm "
            "it. " + ONE,
            ["thermoslop set 68", "thermoslop set +1 -t upstairs", "thermoslop set --heat 66 --cool 76"]),
    "mode": ("control", "set the HVAC mode: heat, cool, auto or off",
             "Set the thermostat's mode. " + ONE,
             ["thermoslop mode heat", "thermoslop mode cool -t upstairs"]),
    "home": ("control", "hold the home comfort setting",
             "Hold ecobee's Home comfort setting until you resume the schedule. " + MANY,
             ["thermoslop home", "thermoslop home --house cabin"]),
    "sleep": ("control", "hold the sleep comfort setting",
              "Hold ecobee's Sleep comfort setting until you resume the schedule. " + MANY,
              ["thermoslop sleep -t upstairs"]),
    "away": ("control", "hold the away comfort setting",
             "Hold ecobee's Away comfort setting (its energy-saving setpoints) until you "
             "resume the schedule. " + MANY,
             ["thermoslop away --all", "thermoslop away --house cabin"]),
    "resume": ("control", "clear holds and resume the schedule",
               "Clear any hold (a manual setpoint or a comfort setting) so the "
               "thermostat follows its schedule again. " + MANY,
               ["thermoslop resume", "thermoslop resume --all"]),
    "log": ("control", "recent changes, from any source",
            "Show recent changes and who made them: this terminal, the bar widget, an "
            "AI client over MCP, or the thermostat itself, its app or its schedule "
            "(recorded by the watcher). Without -t or --house it shows every thermostat.",
            ["thermoslop log", "thermoslop log --hours 72 -t upstairs", "thermoslop log --source mcp --json"]),
    "discover": ("pairing", "find HomeKit thermostats on the network",
                 "Look for HomeKit thermostats: by multicast on this machine's LAN, and by "
                 "asking every address in the configured subnets (which reaches across "
                 "NAT, VLANs and Tailscale subnet routes). Each is listed as ready to pair, "
                 "paired here, or paired elsewhere.",
                 ["thermoslop discover", "thermoslop discover --house cabin",
                  "thermoslop discover --subnet 192.0.2.0/24 --all"]),
    "pair": ("pairing", "pair with a thermostat using its HomeKit code",
             "Pair with a thermostat found by `thermoslop discover`. Pairing starts first, "
             "then it asks for the code on the thermostat's screen (Menu → Settings → "
             "HomeKit), which changes once pairing starts. A thermostat pairs with one "
             "HomeKit controller at a time.",
             ["thermoslop pair 'Main Floor'", "thermoslop pair 12:34:56:78:9A:BC --alias upstairs",
              "thermoslop pair Basement --demo"]),
    "unpair": ("pairing", "remove a pairing",
               "Remove this machine's pairing with a thermostat, freeing it for another "
               "controller. " + ONE,
               ["thermoslop unpair -t cabin"]),
    "setup": ("services", "install the background services (systemd or launchd)",
              "Install the watcher and the MCP HTTP server as user services: systemd on "
              "Linux, launchd on macOS. The watcher is started; the MCP server is left "
              "off unless it was already on. On Omarchy it also offers the bar widget. "
              "--remove takes the services away and keeps pairings, config and history.",
              ["thermoslop setup", "thermoslop setup --remove"]),
    "watch": ("services", "run the watcher (what `setup` installs)",
              "Keep the state file the bar widget and `thermoslop bar` read up to date, "
              "from HomeKit events, and record changes made outside ThermoSlop. Usually "
              "run as a service by `thermoslop setup`; run it by hand under another "
              "service manager.",
              ["thermoslop watch"]),
    "mcp": ("services", "MCP server for AI clients (stdio, or --http on the tailnet)",
            "Serve the thermostats to AI clients over the Model Context Protocol: on "
            "stdio for a client on this machine, or with --http on this machine's "
            "Tailscale address for clients elsewhere on the tailnet. Setpoint limits, a "
            "rate limit and read-only mode come from [mcp] in the config.",
            ["thermoslop mcp", "thermoslop mcp --read-only", "thermoslop mcp --http --port 8765"]),
    "bar": ("services", "status-bar output (Waybar, SwiftBar, i3blocks…)",
            "Print the thermostats for a status bar, from the watcher's state file only "
            "(it never contacts a thermostat). --follow prints again on every change, for "
            "Waybar's continuous mode.",
            ["thermoslop bar", "thermoslop bar --format waybar --follow", "thermoslop bar --format swiftbar"]),
    "dump": ("troubleshooting", "raw HomeKit accessory data",
             "Print the thermostat's raw HomeKit services and characteristics, for "
             "debugging or a bug report. " + ONE,
             ["thermoslop dump -t upstairs"]),
    "help": ("troubleshooting", "help for a command",
             "Show the help for a command, the same as `thermoslop COMMAND --help`.",
             ["thermoslop help", "thermoslop help set"]),
    "completion": ("troubleshooting", "shell completion script (bash, zsh, fish)",
                   "Print a completion script for your shell. It completes commands, "
                   "options, modes, and your paired thermostats' aliases.",
                   ["eval \"$(thermoslop completion bash)\"   # in ~/.bashrc",
                    "eval \"$(thermoslop completion zsh)\"    # in ~/.zshrc",
                    "thermoslop completion fish > ~/.config/fish/completions/thermoslop.fish"]),
}

MODE_HELP = {
    "heat": "heat only, to the target",
    "cool": "cool only, to the target",
    "auto": "heat or cool to stay between the heat and cool setpoints",
    "off": "no heating or cooling at all",
}


def _wrap(text: str) -> str:
    return "\n".join(textwrap.fill(p, 78) for p in text.split("\n\n"))


def _home(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def command_kwargs(name: str) -> dict:
    """add_parser() arguments for one command: summary, description, examples."""
    _, summary, description, examples = COMMANDS[name]
    epilog = "examples:\n" + "\n".join(f"  {e}" for e in examples)
    return {"description": _wrap(description), "epilog": epilog,
            "formatter_class": argparse.RawDescriptionHelpFormatter}


def top_description() -> str:
    lines = [_wrap("ThermoSlop: ecobee thermostats over local HomeKit, from the terminal, a "
                   "status bar or an AI client. Unofficial; not affiliated with ecobee Inc. "
                   "or Apple Inc."),
             "",
             "first steps:",
             "  thermoslop discover        find thermostats on your network",
             "  thermoslop pair NAME       pair one (it asks for the code on its screen)",
             "  thermoslop setup           start the watcher in the background"]
    for group in GROUPS:
        lines += ["", GROUP_TITLES[group].lower() + ":"]
        lines += [f"  {name:<12} {summary}" for name, (g, summary, _, _) in COMMANDS.items() if g == group]
    return "\n".join(lines)


def top_epilog() -> str:
    return "\n".join([
        "Every command takes --json (machine-readable output), --plain (no symbols) and -v.",
        "",
        "files:",
        f"  config        {_home(CONFIG_FILE)}",
        f"  pairings      {_home(PAIRING_FILE)}",
        f"  state         {_home(STATE_FILE)}   (the watcher's readings)",
        f"  change log    {_home(AUDIT_FILE)}",
        "",
        "environment:",
        "  THERMOSLOP_SOURCE   who a change is logged as (cli, widget, mcp); set by the bar widget",
        "  THERMOSLOP_PLAIN=1  words instead of symbols in output, like --plain (screen readers)",
        "  XDG_CONFIG_HOME, XDG_DATA_HOME, XDG_CACHE_HOME, XDG_STATE_HOME   move the files above",
        "",
        f"docs: {DOCS_URL}",
        "more: thermoslop help COMMAND",
    ])


# ---- completion


def _spec(parser: argparse.ArgumentParser) -> dict[str, dict]:
    """{command: {"options": [...], "words": [...], "choices": {option: [...]}}} from the parser."""
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    spec = {}
    for name, p in sub.choices.items():
        options, words, choices = [], [], {}
        for a in p._actions:
            if a.help == argparse.SUPPRESS:
                continue
            if a.option_strings:
                options += [o for o in a.option_strings if o.startswith("--") or o in ("-t", "-n", "-v")]
                if a.choices:
                    for o in a.option_strings:
                        choices[o] = list(a.choices)
            elif a.choices:
                words += list(a.choices)
        spec[name] = {"options": options, "words": words, "choices": choices}
    return spec


def aliases() -> list[str]:
    """Paired aliases, from the pairing file only (no network)."""
    try:
        return sorted(json.loads(PAIRING_FILE.read_text()))
    except (OSError, ValueError):
        return []


def houses() -> list[str]:
    try:
        return sorted(load_config().houses)
    except (OSError, ValueError):
        return []


def bash(parser: argparse.ArgumentParser) -> str:
    spec = _spec(parser)
    cases = "\n".join(
        f"    {name}) opts={shlex.quote(' '.join(s['options'] + s['words']))} ;;" for name, s in spec.items())
    choice_cases = {}
    for s in spec.values():
        for opt, values in s["choices"].items():
            choice_cases[opt] = values
    prev = "\n".join(f"    {opt}) COMPREPLY=($(compgen -W {shlex.quote(' '.join(v))} -- \"$cur\")); return ;;"
                     for opt, v in sorted(choice_cases.items()))
    return f"""# thermoslop completion for bash (and zsh, through bashcompinit)
_thermoslop() {{
  local cur prev cmd opts
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  cmd="${{COMP_WORDS[1]}}"
  if [ "$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=($(compgen -W {shlex.quote(' '.join(spec))} -- "$cur"))
    return
  fi
  case "$prev" in
    -t|--thermostat) COMPREPLY=($(compgen -W "$(thermoslop completion --aliases 2>/dev/null)" -- "$cur")); return ;;
    --house) COMPREPLY=($(compgen -W "$(thermoslop completion --houses 2>/dev/null)" -- "$cur")); return ;;
{prev}
  esac
  case "$cmd" in
{cases}
    *) opts="" ;;
  esac
  COMPREPLY=($(compgen -W "$opts" -- "$cur"))
}}
complete -F _thermoslop thermoslop
"""


def zsh(parser: argparse.ArgumentParser) -> str:
    return "# thermoslop completion for zsh\nautoload -U +X bashcompinit && bashcompinit\n" + bash(parser)


def fish(parser: argparse.ArgumentParser) -> str:
    spec = _spec(parser)
    lines = ["# thermoslop completion for fish", "complete -c thermoslop -f"]
    for name, (_, summary, _, _) in COMMANDS.items():
        lines.append(f"complete -c thermoslop -n __fish_use_subcommand -a {name} -d {shlex.quote(summary)}")
    for name, s in spec.items():
        cond = f"'__fish_seen_subcommand_from {name}'"
        if s["words"]:
            lines.append(f"complete -c thermoslop -n {cond} -a {shlex.quote(' '.join(s['words']))}")
        for opt in s["options"]:
            if opt == "-t":
                continue
            flag = f"-l {opt[2:]}" if opt.startswith("--") else f"-s {opt[1:]}"
            extra = ""
            if opt in ("--thermostat",):
                extra = " -s t -x -a '(thermoslop completion --aliases)'"
            elif opt == "--house":
                extra = " -x -a '(thermoslop completion --houses)'"
            elif opt in s["choices"]:
                extra = f" -x -a {shlex.quote(' '.join(s['choices'][opt]))}"
            lines.append(f"complete -c thermoslop -n {cond} {flag}{extra}")
    return "\n".join(lines) + "\n"


SHELLS = {"bash": bash, "zsh": zsh, "fish": fish}
