// ecobee thermostats in the bar. State comes from the cache file that
// `ecobee watch` keeps fresh (it subscribes to HomeKit events), so the widget
// never polls the thermostats itself.
//
//   left click    notification with full status (all thermostats + sensors)
//   right click   away hold on every thermostat, or resume the schedule if away
//   middle click  resume the schedule (clear holds)
//   scroll        nudge the setpoint by 1°, sent once scrolling stops
//
// Optional settings on the widget's entry in shell.json:
//   "thermostat": "upstairs"   show / control only this one
import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

BarWidget {
  id: root
  moduleName: "john.ecobee"

  readonly property string stateFile: Quickshell.env("HOME") + "/.cache/ecobee/state.json"
  readonly property string only: root.settings && root.settings.thermostat ? String(root.settings.thermostat) : ""
  // A reading older than this means `ecobee watch` isn't running.
  readonly property int staleSeconds: 600

  property var thermostats: []
  property real now: Date.now() / 1000
  property int pendingDelta: 0

  readonly property var shown: only ? thermostats.filter(t => t.alias === only) : thermostats
  readonly property var live: shown.filter(t => t.available && now - (t.updated_at || 0) < staleSeconds)
  readonly property string scrollTarget: only || (shown.length ? shown[0].alias : "")
  readonly property bool anyAway: live.some(t => t.comfort === "away")

  function load(text) {
    try {
      const stats = JSON.parse(text || "{}").thermostats || {}
      root.thermostats = Object.keys(stats).sort().map(k => stats[k])
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
    const temps = shown.map(t => t.available ? deg(t.temperature) : "?")
    const pending = pendingDelta ? "  →" + (pendingDelta > 0 ? "+" : "") + pendingDelta : ""
    return icon() + " " + temps.join(" ") + pending
  }

  function setpoint(t) {
    if (t.mode === "auto") return deg(t.heat_setpoint) + "–" + deg(t.cool_setpoint)
    if (t.target !== null && t.target !== undefined) return deg(t.target)
    return "—"
  }

  function tooltip() {
    if (!shown.length) return "ecobee: no data (is `ecobee watch` running?)"
    return shown.map(function(t) {
      if (!t.available) return t.name + ": unavailable"
      let line = t.name + "  " + deg(t.temperature) + "  " + t.action + " → " + setpoint(t) + " " + t.mode
      if (t.comfort) line += " · " + t.comfort
      if (t.humidity !== null && t.humidity !== undefined) line += " · " + t.humidity + "%"
      const occupied = (t.sensors || []).filter(s => s.occupied).map(s => s.name)
      if (occupied.length) line += "\n  occupied: " + occupied.join(", ")
      return line
    }).join("\n")
  }

  function ecobee(args) {
    if (root.bar) root.bar.run("ecobee " + args)
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
        root.ecobee("set " + (d > 0 ? "+" : "") + d + " -t " + Util.shellQuote(root.scrollTarget))
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
    tooltipText: root.tooltip()

    onPressed: function(b) {
      const all = root.only ? "-t " + Util.shellQuote(root.only) : "--all"
      if (b === Qt.RightButton) root.ecobee((root.anyAway ? "resume " : "away ") + all)
      else if (b === Qt.MiddleButton) root.ecobee("resume " + all)
      else if (root.bar) root.bar.run("omarchy-notification-send -g 󰔏 Ecobee \"$(ecobee status 2>&1)\"")
    }

    onWheelMoved: function(delta) {
      if (!root.live.length) return
      root.pendingDelta += delta > 0 ? 1 : -1
      sendDelta.restart()
    }
  }
}
