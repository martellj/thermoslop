.pragma library
// The command behind a house's AWAY ALL / RESUME ALL, which must reach exactly
// the thermostats its confirmation counted. Used by Panel.qml, and run under
// Node by tests/test_house_action.py. A named house is `--all --house NAME`.
// Thermostats with no house (the OTHER group) have no CLI selector, and plain
// `--all` would reach every paired thermostat, other houses included, so each
// gets its own `-t ALIAS`, one after another (one failing doesn't stop the rest).

function command(cli, action, house, aliases, quote) {
  if (house) return cli + " " + action + " --all --house " + quote(house)
  return aliases.map(a => cli + " " + action + " -t " + quote(a)).join("; ")
}

if (typeof module !== "undefined") module.exports = { command }
