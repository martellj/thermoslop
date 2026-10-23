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

  property var thermostats: []
  property var history: ({})
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
    if (!shown.length) return ""
    const temps = houses.map(h => shown.filter(t => (t.house || "") === h)
      .map(t => t.available ? deg(t.temperature) : "?").join(" "))
    const pending = pendingDelta ? "  →" + (pendingDelta > 0 ? "+" : "") + pendingDelta : ""
    return icon() + " " + temps.join(" │ ") + pending
  }

  function thermoslop(args) {
    if (root.bar) root.bar.run("thermoslop " + args)
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

  visible: shown.length > 0
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.label()
    fontSize: Style.font.caption
    horizontalMargin: 6
    dimmed: root.live.length === 0
    // The panel is the detail view.
    tooltipText: ""

    onPressed: function(b) {
      if (b === Qt.RightButton) root.thermoslop((root.anyAway ? "resume " : "away ") + root.scope)
      else if (b === Qt.MiddleButton) root.thermoslop("resume " + root.scope)
      else if (panelLoader.item) panelLoader.item.toggle()
    }

    onWheelMoved: function(delta) {
      if (!root.live.length) return
      root.pendingDelta += delta > 0 ? 1 : -1
      sendDelta.restart()
    }
  }
}
