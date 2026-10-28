// ThermoSlop: thermostats in the bar. State comes from the cache file that
// `thermoslop watch` keeps fresh (it subscribes to HomeKit events), so the widget
// never polls the thermostats itself.
//
//   left click    open the panel (cards per thermostat, setpoint −/+, modes)
//   right click   away hold, or resume the schedule if away
//   middle click  resume the schedule (clear holds)
//   scroll        nudge the setpoint by 1° (read from the thermostat first,
//                 sent as one value once scrolling stops)
// Right/middle click act on the one thermostat or the one house shown; with
// several houses shown they open the panel instead. Scroll works only when one
// thermostat is shown: it never guesses which one you meant.
//
// Optional settings on the widget's entry in shell.json:
//   "thermostat": "upstairs"   show / control only this one
//   "house": "cabin"           show / control only this house's thermostats
//   "demo": true               pretend thermostats in the bar and panel, for
//                              trying the controls or taking screenshots;
//                              nothing is read from or sent to a thermostat
//   "pairingDemo": true        "Add thermostat" pairs with a pretend thermostat
//                              (thermoslop discover/pair --demo); nothing is saved
// With several houses shown, temperatures are grouped per house: 68° 70° │ 55°
import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "martellj.thermoslop"

  readonly property string stateFile: Quickshell.env("HOME") + "/.cache/thermoslop/state.json"
  readonly property string only: root.settings && root.settings.thermostat ? String(root.settings.thermostat) : ""
  readonly property string house: root.settings && root.settings.house ? String(root.settings.house) : ""
  // A reading older than this means `thermoslop watch` isn't running.
  readonly property int staleSeconds: 600

  // The plugin drives the `thermoslop` CLI and reads its state file, so it
  // needs a CLI at least as new as itself (scripts/release keeps this in step).
  readonly property string requiredVersion: "0.3.1"
  property string cliVersion: ""
  property string cliState: "checking"   // checking, missing, outdated, ok
  readonly property bool cliOk: cliState === "ok" || cliState === "checking"
  readonly property string installHint: "uv tool install thermoslop && thermoslop setup"
  readonly property string upgradeHint: "uv tool upgrade thermoslop"

  function olderThan(a, b) {
    const x = a.split(".").map(Number), y = b.split(".").map(Number)
    for (let i = 0; i < 3; i++) {
      if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) < (y[i] || 0)
    }
    return false
  }

  Process {
    id: versionProc
    // Through sh, which always starts and exits 127 when thermoslop is missing:
    // a missing executable on its own never reports back.
    command: ["sh", "-c", "thermoslop --version"]
    running: true
    stdout: StdioCollector {
      onStreamFinished: {
        const m = /thermoslop (\d+\.\d+\.\d+)/.exec(text || "")
        root.cliVersion = m ? m[1] : ""
        root.cliState = !m ? "missing" : root.olderThan(m[1], root.requiredVersion) ? "outdated" : "ok"
      }
    }
    onExited: function(code) { if (code !== 0) root.cliState = "missing" }
  }

  Timer {
    interval: 10000
    running: root.cliState === "checking"
    onTriggered: root.cliState = "missing"
  }

  property var thermostats: []
  property var history: ({})
  // The watcher's [trend_hours] (config.toml); 0 = no trend line.
  property real trendHours: 24
  property real updatedAt: 0
  property real now: Date.now() / 1000

  readonly property var shown: thermostats.filter(t => (!only || t.alias === only) && (!house || t.house === house))
  readonly property var houses: [...new Set(shown.map(t => t.house || ""))]
  readonly property var live: shown.filter(t => t.available && now - (t.updated_at || 0) < staleSeconds)
  // The watcher rewrites the file at least every few minutes, even while it
  // can't reach a thermostat, so an old file means the watcher itself stopped.
  readonly property bool watcherLive: now - updatedAt < staleSeconds
  readonly property string scrollTarget: shown.length === 1 ? shown[0].alias : ""
  readonly property bool anyAway: live.some(t => t.comfort === "away")
  // Scroll drives that thermostat's controller in the panel (the same one its
  // card uses); this is its value on the way, e.g. "→67°".
  readonly property string pendingText: panel && scrollTarget ? panel.pendingLabel(scrollTarget) : ""
  // What right/middle clicks act on: `-t upstairs` for one thermostat,
  // `--all --house cabin` for one house, or "" when several houses are shown.
  readonly property string scope: shown.length === 1 ? "-t " + Util.shellQuote(shown[0].alias)
    : houses.length === 1 ? "--all" + (houses[0] ? " --house " + Util.shellQuote(houses[0]) : "") : ""

  readonly property bool demo: !!(root.settings && root.settings.demo)

  // Three pretend thermostats in two houses, with a day of trend.
  function demoCache() {
    const now = Date.now() / 1000
    const t = (alias, name, house, temp, hum, action, target) => ({
      alias: alias, name: name, house: house, available: true, units: "F", temperature: temp,
      humidity: hum, mode: "heat", action: action, target: target, heat_setpoint: target,
      cool_setpoint: 76, comfort: "hold", updated_at: now })
    const trend = (base, swing, phase) => Array.from({ length: 96 }, (_, i) =>
      [now - (95 - i) * 900, Math.round((base + swing * Math.sin(i / 15 + phase) + 0.15 * Math.sin(i * 0.9 + phase * 3) * Math.sin(i * 0.23)) * 10) / 10])
    return {
      updated_at: now, trend_hours: 24,
      thermostats: {
        "main-floor": t("main-floor", "Main Floor", "home", 68.4, 41, "heating", 70),
        "upstairs": t("upstairs", "Upstairs", "home", 70.2, 38, "idle", 69),
        "cabin": t("cabin", "Cabin", "cabin", 55.1, 52, "idle", 55),
      },
      history: { "main-floor": trend(68.5, 1.2, 0), "upstairs": trend(70, 0.8, 1), "cabin": trend(55, 2.5, 2) },
    }
  }

  function load(text) {
    if (root.demo) text = JSON.stringify(root.demoCache())
    try {
      const cache = JSON.parse(text || "{}")
      const stats = cache.thermostats || {}
      root.thermostats = Object.keys(stats).map(k => stats[k])
        .sort((a, b) => (a.house || "").localeCompare(b.house || "") || a.alias.localeCompare(b.alias))
      root.history = cache.history || {}
      root.trendHours = cache.trend_hours ?? 24
      root.updatedAt = cache.updated_at || 0
    } catch (e) {
      // Mid-write reads can't happen (the file is replaced atomically), so a
      // parse failure means a bad file: keep the last good reading.
    }
  }

  function deg(v) {
    return v === null || v === undefined ? "—" : Math.round(v) + "°"
  }

  function icon() {
    if (live.some(t => t.action === "heating")) return "󰈸"
    if (live.some(t => t.action === "cooling")) return "󰜗"
    if (live.length && live.every(t => t.comfort === "away")) return "󰜷"
    return "󰔏"
  }

  function label() {
    if (cliState === "missing") return "󰔏 install thermoslop"
    if (!shown.length) return ""
    const temps = houses.map(h => shown.filter(t => (t.house || "") === h)
      .map(t => t.available ? deg(t.temperature) : "?").join(" "))
    const pending = pendingText ? "  " + pendingText : ""
    return icon() + " " + temps.join(" │ ") + pending + (cliState === "outdated" ? "  ↑" : "")
  }

  // What a screen reader says for the bar item: names and readings in words.
  function spoken() {
    if (cliState === "missing") return "ThermoSlop: the thermoslop command isn't installed"
    if (!shown.length) return "ThermoSlop: no thermostats"
    return "ThermoSlop: " + shown.map(t => (t.name || t.alias) + " "
      + (t.available ? Math.round(t.temperature) + " degrees, " + (t.action || "") : "unavailable")).join("; ")
  }

  // Changes made here are logged with source "widget" (`thermoslop log`).
  readonly property string cli: "THERMOSLOP_SOURCE=widget thermoslop"

  function thermoslop(args) {
    if (root.bar && root.cliOk && !root.demo) root.bar.run(root.cli + " " + args)
  }

  // ---- panel hosting (same contract as Omarchy's weather widget)

  function injectPanel() {
    const target = panelLoader.item
    if (!target) return
    target.bar = root.bar
    target.settings = root.settings
    target.anchorItem = button
    target.hostWidget = root
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property var panel: panelLoader.item
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  function open() { if (panelLoader.item) panelLoader.item.openFromHotkey() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  FileView {
    id: stateView
    path: root.stateFile
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.load(text())
    onLoadFailed: root.demo ? root.load("") : root.thermostats = []
  }

  // Ages readings so the widget dims when the daemon stops. The reload covers
  // a state file created after the widget loaded, which the watch can't see.
  Timer {
    interval: 30000
    running: true
    repeat: true
    onTriggered: {
      root.now = Date.now() / 1000
      stateView.reload()
    }
  }

  // Also shown without any thermostats when the CLI is missing or too old, so
  // the panel can say how to fix it.
  visible: shown.length > 0 || cliState === "missing" || cliState === "outdated"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.label()
    Accessible.name: root.spoken()
    Accessible.description: "Click for the thermostat panel"
    fontSize: Style.font.caption
    horizontalMargin: 6
    dimmed: root.live.length === 0 || !root.cliOk
    // The panel is the detail view.
    tooltipText: ""

    onPressed: function(b) {
      const act = b === Qt.RightButton ? (root.anyAway ? "resume " : "away ") : b === Qt.MiddleButton ? "resume " : ""
      if (act && root.scope) root.thermoslop(act + root.scope)
      else if (panelLoader.item) panelLoader.item.toggle()
    }

    onWheelMoved: function(delta) {
      if (!root.scrollTarget || !root.cliOk || !panelLoader.item) return
      panelLoader.item.nudge(root.shown[0], delta > 0 ? 1 : -1)
    }
  }
}
