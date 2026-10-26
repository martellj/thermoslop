// ThermoSlop: thermostats in the bar. State comes from the cache file that
// `thermoslop watch` keeps fresh (it subscribes to HomeKit events), so the widget
// never polls the thermostats itself.
//
//   left click    open the panel (cards per thermostat, setpoint +/-, modes)
//   right click   away hold on every thermostat, or resume the schedule if away
//   middle click  resume the schedule (clear holds)
//   scroll        nudge the setpoint by 1°, sent once scrolling stops
//
// Optional settings on the widget's entry in shell.json:
//   "thermostat": "upstairs"   show / control only this one
//   "house": "cabin"           show / control only this house's thermostats
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
  readonly property string requiredVersion: "0.2.3"
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
  property int pendingDelta: 0

  readonly property var shown: thermostats.filter(t => (!only || t.alias === only) && (!house || t.house === house))
  readonly property var houses: [...new Set(shown.map(t => t.house || ""))]
  readonly property var live: shown.filter(t => t.available && now - (t.updated_at || 0) < staleSeconds)
  readonly property string scrollTarget: only || (shown.length ? shown[0].alias : "")
  readonly property bool anyAway: live.some(t => t.comfort === "away")
  // `--all`, `--all --house cabin` or `-t upstairs`: what the bar's actions act on.
  readonly property string scope: only ? "-t " + Util.shellQuote(only)
    : house ? "--all --house " + Util.shellQuote(house) : "--all"

  function load(text) {
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
    const pending = pendingDelta ? "  →" + (pendingDelta > 0 ? "+" : "") + pendingDelta : ""
    return icon() + " " + temps.join(" │ ") + pending + (cliState === "outdated" ? "  ↑" : "")
  }

  // Changes made here are logged with source "widget" (`thermoslop log`).
  readonly property string cli: "THERMOSLOP_SOURCE=widget thermoslop"

  function thermoslop(args) {
    if (root.bar && root.cliOk) root.bar.run(root.cli + " " + args)
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
    onLoadFailed: root.thermostats = []
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

  Timer {
    id: sendDelta
    interval: 900
    onTriggered: {
      if (root.pendingDelta && root.scrollTarget) {
        const d = root.pendingDelta
        root.thermoslop("set " + (d > 0 ? "+" : "") + d + " -t " + Util.shellQuote(root.scrollTarget))
      }
      root.pendingDelta = 0
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
    fontSize: Style.font.caption
    horizontalMargin: 6
    dimmed: root.live.length === 0 || !root.cliOk
    // The panel is the detail view.
    tooltipText: ""

    onPressed: function(b) {
      if (b === Qt.RightButton) root.thermoslop((root.anyAway ? "resume " : "away ") + root.scope)
      else if (b === Qt.MiddleButton) root.thermoslop("resume " + root.scope)
      else if (panelLoader.item) panelLoader.item.toggle()
    }

    onWheelMoved: function(delta) {
      if (!root.live.length || !root.cliOk) return
      root.pendingDelta += delta > 0 ? 1 : -1
      sendDelta.restart()
    }
  }
}
