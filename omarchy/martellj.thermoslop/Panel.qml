// The ThermoSlop panel: a header and one card per thermostat (ring gauge,
// temperature, setpoint −/+, its own mode row, temperature trend). Data comes
// from the bar widget (hostWidget), which reads the watcher's cache file.
// Changes run the `thermoslop` CLI, so they go through the same code as the
// terminal, and every control acts on one thermostat; only away/resume can
// act on a whole house, after a confirming second press.
//
// Colors come from the Omarchy theme (accent for heat, the foreground at
// varying alpha for surfaces), so the panel follows theme changes.
import QtQuick 6.11 // omacvm #376: QtQuick's own Color (Qt 6.12) would hide Omarchy's
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "martellj.thermoslop"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property var zones: hostWidget ? hostWidget.shown : []
  // Controls are off while the CLI is missing or older than the plugin.
  readonly property bool cliOk: hostWidget ? hostWidget.cliOk : true
  readonly property string cliState: hostWidget ? hostWidget.cliState : "ok"
  readonly property string cli: hostWidget ? hostWidget.cli : "THERMOSLOP_SOURCE=widget thermoslop"
  readonly property var live: hostWidget ? hostWidget.live : []
  readonly property bool watcherLive: hostWidget ? hostWidget.watcherLive : false
  readonly property var history: hostWidget ? hostWidget.history : ({})
  readonly property real trendHours: hostWidget ? hostWidget.trendHours : 24
  readonly property real now: hostWidget ? hostWidget.now : Date.now() / 1000
  readonly property bool multiHouse: hostWidget ? hostWidget.houses.length > 1 : false

  // One SetpointControl per thermostat (see the component below), by alias.
  // Keyed on the alias list as a string, so a cache reload with the same
  // thermostats keeps them (and any change in progress).
  property var controls: ({})
  readonly property string aliasKey: zones.map(z => z.alias).join("\n")
  function control(alias) { return root.controls[alias] || null }

  Instantiator {
    model: root.aliasKey ? root.aliasKey.split("\n") : []
    delegate: SetpointControl {
      required property string modelData
      alias: modelData
      t: root.zones.find(z => z.alias === modelData) || null
      demo: root.hostWidget ? root.hostWidget.demo : false
    }
    onObjectAdded: function(index, object) {
      const next = Object.assign({}, root.controls)
      next[object.alias] = object
      root.controls = next
    }
    onObjectRemoved: function(index, object) {
      const next = Object.assign({}, root.controls)
      delete next[object.alias]
      root.controls = next
    }
  }

  // Away/resume for a whole house waits for a second press within 4 s.
  property string armed: ""
  Timer {
    id: disarm
    interval: 4000
    onTriggered: root.armed = ""
  }

  readonly property color fg: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color cool: "#6cb6d9"
  readonly property color good: "#5fd38d"
  readonly property color bad: Color.urgent
  readonly property color dim: Qt.darker(fg, 1.5)
  readonly property color surface: Util.alpha(fg, 0.035)
  readonly property color hairline: Util.alpha(fg, 0.10)
  readonly property string font: root.bar ? root.bar.fontFamily : Style.font.family
  readonly property int radius: Style.space(10)

  function open() {
    root.controller.show()
    if (root.hostWidget) root.hostWidget.now = Date.now() / 1000
    // Never adjust from the cache: read every thermostat now.
    for (const alias in root.controls) root.controls[alias].read()
  }
  function openFromHotkey() { open() }
  function close() { root.controller.hide() }
  function toggle() { root.opened ? close() : open() }

  // ---- helpers

  function num(v, digits) {
    return v === null || v === undefined ? "—" : Number(v).toFixed(digits === undefined ? 0 : digits)
  }

  function modeGlyph(mode) {
    return { heat: "󰈸", cool: "󰜗", auto: "󰔏", off: "󰤆" }[mode] || "󰔏"
  }

  function actionColor(t) {
    if (!t.available) return root.bad
    if (t.action === "heating") return root.accent
    if (t.action === "cooling") return root.cool
    return root.dim
  }

  function fmtSetpoint(v, units) {
    if (!v || v.mode === "off") return "OFF"
    // Half degrees stay visible (an ecobee in °C, or one that adjusted a value).
    const n = x => x === null || x === undefined ? "—" : String(Math.round(x * 10) / 10)
    if (v.mode === "auto") return n(v.heat) + "–" + n(v.cool) + "°"
    return n(v.target) + "°" + (units || "")
  }

  // Positive when the room is warmer than the target (heat) or cooler (cool):
  // the thermostat has nothing to do.
  function targetDelta(t) {
    if (!t.available || t.temperature === null) return null
    if (t.mode === "heat") return t.temperature - (t.target ?? t.heat_setpoint)
    if (t.mode === "cool") return (t.target ?? t.cool_setpoint) - t.temperature
    if (t.mode === "auto") return Math.min(t.temperature - t.heat_setpoint, t.cool_setpoint - t.temperature)
    return null
  }

  function ago(seconds) {
    if (seconds < 60) return Math.max(0, Math.round(seconds)) + "s ago"
    if (seconds < 3600) return Math.round(seconds / 60) + "m ago"
    return Math.round(seconds / 3600) + "h ago"
  }

  function summary() {
    if (root.live.some(t => t.action === "heating")) return "HEATING"
    if (root.live.some(t => t.action === "cooling")) return "COOLING"
    if (root.zones.length && !root.live.length) return "OFFLINE"
    return "IDLE"
  }

  // The bar's scroll and the card's −/+ both land here.
  function nudge(t, step) {
    const c = root.control(t.alias)
    if (c && root.cliOk) c.press(step)
  }

  // Shown in the bar while a scroll's change is pending or saving.
  function pendingLabel(alias) {
    const c = root.control(alias)
    return c && c.draft ? "→" + root.fmtSetpoint(c.draft, "") : ""
  }

  function run(args) {
    if (root.bar && root.cliOk) root.bar.run(args)
  }

  function houseZones(house) {
    return root.zones.filter(t => (t.house || "") === (house || "") && t.available)
  }

  // First press arms (the button asks to confirm), the second runs.
  function houseAction(action, house) {
    const key = action + ":" + (house || "")
    if (root.armed !== key) {
      root.armed = key
      disarm.restart()
      return
    }
    root.armed = ""
    disarm.stop()
    if (root.hostWidget && root.hostWidget.demo) return
    run(root.cli + " " + action + " --all" + (house ? " --house " + Util.shellQuote(house) : ""))
  }

  function houseLabel(action, house) {
    const n = root.houseZones(house).length
    if (root.armed === action + ":" + (house || ""))
      return action.toUpperCase() + " " + n + (house ? " AT " + house.toUpperCase() : "") + "?"
    return action === "away" ? "AWAY ALL" : "RESUME ALL"
  }

  // ---- adding a thermostat. Runs `thermoslop discover --json` and
  // `thermoslop pair NAME --json`, which announces on stderr when it wants the
  // code; the code goes to its stdin. With the widget's `pairingDemo` setting
  // both run with --demo: a pretend thermostat, nothing is saved.

  property string view: "zones"         // "zones" or "add"
  property string pairStage: "idle"     // scanning, list, starting, code, verifying, done, error
  property var found: []
  property string pairName: ""
  property string pairDevice: ""
  property string pairHint: ""
  property string pairError: ""
  property var paired: null
  readonly property bool pairingDemo: !!(root.settings && root.settings.pairingDemo)
  readonly property var demoArgs: pairingDemo ? ["--demo"] : []

  function startAdding() {
    if (!root.cliOk) return
    root.view = "add"
    scan()
  }

  function scan() {
    root.pairStage = "scanning"
    root.found = []
    root.pairError = ""
    discoverProc.command = ["thermoslop", "discover", "--json"].concat(root.demoArgs)
    discoverProc.running = true
  }

  // `device` is the discovered device's id (names can repeat across houses);
  // `name` is only for display.
  function beginPair(device, name) {
    root.pairDevice = device
    root.pairName = name || device
    root.pairHint = ""
    root.pairError = ""
    root.pairStage = "starting"
    pairProc.command = ["env", "THERMOSLOP_SOURCE=widget", "thermoslop", "pair", device, "--json"].concat(root.demoArgs)
    pairProc.running = true
  }

  function submitCode(code) {
    if (code.replace(/\D/g, "").length !== 8) return
    root.pairStage = "verifying"
    pairProc.write(code + "\n")
  }

  function stopAdding() {
    root.pairStage = "idle"
    if (pairProc.running) pairProc.running = false
    if (discoverProc.running) discoverProc.running = false
    root.view = "zones"
  }

  // `omarchy-shell thermoslop add` opens the panel on "Add thermostat"
  // (bindable to a key); `… pair DEVICE` (id, address or unique name) starts pairing.
  // There's a widget (and panel) per monitor, and only one gets the IPC
  // target, so it hands off to the copy the bar picks for the focused screen.
  function visibleCopy() {
    const widget = root.bar && typeof root.bar.findPanelWidget === "function"
      ? root.bar.findPanelWidget("martellj.thermoslop") : null
    return widget && widget.panel ? widget.panel : root
  }

  IpcHandler {
    target: "thermoslop"
    function open(): void { root.visibleCopy().open() }
    function add(): void { const p = root.visibleCopy(); p.open(); p.startAdding() }
    function pair(device: string): void { const p = root.visibleCopy(); p.open(); p.view = "add"; p.beginPair(device) }
  }

  Process {
    id: discoverProc
    stdout: StdioCollector {
      onStreamFinished: {
        if (root.pairStage !== "scanning") return
        try {
          const result = JSON.parse(text || "[]")
          if (Array.isArray(result)) {
            root.found = result
            root.pairStage = "list"
            return
          }
          root.pairError = result.error || "discovery failed"
        } catch (e) {
          root.pairError = "discovery failed"
        }
        root.pairStage = "error"
      }
    }
  }

  Process {
    id: pairProc
    stdinEnabled: true
    stderr: SplitParser {
      onRead: function(line) {
        try {
          const event = JSON.parse(line)
          if (event.event === "code_needed") {
            root.pairHint = event.hint || ""
            root.pairStage = "code"
          }
        } catch (e) {
          // Plain log lines; only the JSON event matters here.
        }
      }
    }
    stdout: StdioCollector {
      onStreamFinished: {
        if (root.pairStage === "idle") return  // cancelled
        let result = {}
        try { result = JSON.parse(text || "{}") } catch (e) {}
        if (result.alias) {
          root.paired = result
          root.pairStage = "done"
        } else {
          root.pairError = result.error || "pairing failed"
          root.pairStage = "error"
        }
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: false
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: codeField.activeFocus
      onCloseRequested: root.view === "add" ? root.stopAdding() : root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: content
          width: scroll.width
          spacing: Style.space(10)

          // ---- header
          Card {
            id: headerCard
            width: parent.width
            height: header.implicitHeight + Style.space(24)

            Row {
              id: header
              anchors.left: parent.left
              anchors.leftMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(12)

              Rectangle {
                width: Style.space(40)
                height: width
                radius: Style.space(8)
                color: Util.alpha(root.accent, 0.10)
                border.color: Util.alpha(root.accent, 0.55)
                border.width: 1
                anchors.verticalCenter: parent.verticalCenter

                Text {
                  textFormat: Text.PlainText
                  anchors.centerIn: parent
                  text: "󰔏"
                  color: root.accent
                  font.family: root.font
                  font.pixelSize: Style.font.iconLarge
                }
              }

              Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(3)

                Row {
                  spacing: Style.space(8)
                  Text {
                    textFormat: Text.PlainText
                    id: titleText
                    text: "ThermoSlop"
                    color: root.fg
                    font.family: root.font
                    font.pixelSize: Style.font.heading
                    font.bold: true
                  }
                  Badge {
                    id: localBadge
                    anchors.verticalCenter: parent.verticalCenter
                    text: "LOCAL"
                    tint: root.accent
                    filled: true
                    // Dropped when the zones pill needs the room.
                    visible: headerCard.width - zonesPill.width - Style.space(100) - titleText.implicitWidth >= implicitWidth
                  }
                }

                Row {
                  spacing: Style.space(6)
                  readonly property bool fresh: root.live.length > 0
                  Rectangle {
                    width: Style.space(7)
                    height: width
                    radius: width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: parent.fresh ? root.good : root.bad
                  }
                  Text {
                    textFormat: Text.PlainText
                    // Stays clear of the zones pill on the right.
                    width: Math.min(implicitWidth, headerCard.width - zonesPill.width - Style.space(110))
                    elide: Text.ElideRight
                    text: parent.fresh
                      ? root.live.length + " live · "
                        + root.ago(root.now - (root.hostWidget ? root.hostWidget.updatedAt : 0))
                      : root.watcherLive && root.zones.length ? "can't reach " + (root.zones.length === 1 ? "thermostat" : "thermostats") + " · retrying"
                      : root.watcherLive ? "watcher running · no thermostats"
                      : "watcher offline · run: thermoslop setup"
                    color: root.dim
                    font.family: root.font
                    font.pixelSize: Style.font.bodySmall
                  }
                }
              }
            }

            Badge {
              id: zonesPill
              anchors.right: parent.right
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              text: root.zones.length + " ZONES │ " + root.summary()
              tint: root.summary() === "COOLING" ? root.cool : root.summary() === "HEATING" ? root.accent : root.fg
              large: true
            }
          }

          // ---- the CLI is missing or too old
          Card {
            visible: root.cliState === "missing" || root.cliState === "outdated"
            width: parent.width
            height: cliColumn.implicitHeight + Style.space(28)
            border.color: Util.alpha(root.bad, 0.5)

            Column {
              id: cliColumn
              anchors.fill: parent
              anchors.margins: Style.space(14)
              spacing: Style.space(8)
              Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WordWrap
                text: root.cliState === "missing"
                  ? "The thermoslop command isn't installed. The bar widget needs it:"
                  : "thermoslop " + (root.hostWidget ? root.hostWidget.cliVersion : "") + " is older than this plugin ("
                    + (root.hostWidget ? root.hostWidget.requiredVersion : "") + "). Update it:"
                color: root.fg
                font.family: root.font
                font.pixelSize: Style.font.body
              }
              Text {
                textFormat: Text.PlainText
                width: parent.width
                wrapMode: Text.WrapAnywhere
                text: root.hostWidget ? (root.cliState === "missing" ? root.hostWidget.installHint : root.hostWidget.upgradeHint) : ""
                color: root.accent
                font.family: root.font
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Text {
                textFormat: Text.PlainText
                visible: root.cliState === "missing"
                text: "Then restart the shell: omarchy restart shell"
                color: root.dim
                font.family: root.font
                font.pixelSize: Style.font.bodySmall
              }
            }
          }

          // ---- one card per thermostat
          Repeater {
            model: root.view === "zones" ? root.zones : []

            Column {
              id: zone
              required property var modelData
              required property int index
              readonly property var t: modelData
              readonly property var c: root.control(t.alias)
              readonly property bool showHouse: root.multiHouse && (index === 0 || root.zones[index - 1].house !== t.house)
              width: content.width
              spacing: Style.space(6)

              Item {
                visible: zone.showHouse
                width: parent.width
                height: Math.max(houseName.implicitHeight, houseActions.implicitHeight)
                Text {
                  textFormat: Text.PlainText
                  id: houseName
                  anchors.verticalCenter: parent.verticalCenter
                  text: (zone.t.house || "other").toUpperCase()
                  color: root.dim
                  font.family: root.font
                  font.pixelSize: Style.font.caption
                  font.letterSpacing: 2
                  leftPadding: Style.space(4)
                }
                HouseActions {
                  id: houseActions
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  house: zone.t.house || ""
                }
              }

              Card {
                width: parent.width
                height: cardBody.implicitHeight + Style.space(28)
                opacity: zone.t.available ? 1 : 0.55

                Column {
                  id: cardBody
                  anchors.fill: parent
                  anchors.margins: Style.space(14)
                  spacing: Style.space(12)

                  // name + badges
                  Item {
                    width: parent.width
                    height: Math.max(nameRow.implicitHeight, badges.implicitHeight)

                    Row {
                      id: nameRow
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(8)
                      Rectangle {
                        width: Style.space(8)
                        height: width
                        radius: width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: zone.t.available ? (zone.t.action === "idle" ? root.accent : root.actionColor(zone.t)) : root.bad
                      }
                      Text {
                        textFormat: Text.PlainText
                        text: (zone.t.name || zone.t.alias).toUpperCase()
                        color: root.fg
                        font.family: root.font
                        font.pixelSize: Style.font.subtitle
                        font.bold: true
                        font.letterSpacing: 1.5
                      }
                    }

                    Row {
                      id: badges
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(6)
                      Badge {
                        text: zone.t.available ? (zone.t.action || "—").toUpperCase() : "OFFLINE"
                        glyph: zone.t.available ? "" : "󰅤"
                        tint: root.actionColor(zone.t)
                      }
                      Badge {
                        visible: !!zone.t.comfort
                        text: (zone.t.comfort || "").toUpperCase()
                        tint: root.accent
                      }
                    }
                  }

                  Rectangle { width: parent.width; height: 1; color: root.hairline }

                  // gauge + temperature + setpoint
                  Item {
                    width: parent.width
                    height: Math.max(gauge.height, setBox.height)

                    Ring {
                      id: gauge
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                      size: Style.space(66)
                      value: zone.t.temperature
                      tint: zone.t.mode === "cool" ? root.cool : root.accent
                      glyph: root.modeGlyph(zone.t.mode)
                    }

                    Column {
                      anchors.left: gauge.right
                      anchors.leftMargin: Style.space(14)
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(2)

                      Row {
                        Text {
                          textFormat: Text.PlainText
                          id: bigTemp
                          text: root.num(zone.t.temperature, 1)
                          color: root.fg
                          font.family: root.font
                          // Hero read-out, deliberately above the Style.font scale.
                          font.pixelSize: Style.space(32)
                          font.bold: true
                        }
                        Text {
                          textFormat: Text.PlainText
                          text: "°" + (zone.t.units || "F")
                          color: root.accent
                          font.family: root.font
                          font.pixelSize: Style.font.heading
                          anchors.top: bigTemp.top
                          anchors.topMargin: Style.space(4)
                        }
                      }
                      Text {
                        textFormat: Text.PlainText
                        visible: zone.t.humidity !== null && zone.t.humidity !== undefined
                        text: "󰖌 " + zone.t.humidity + "% RH"
                        color: root.dim
                        font.family: root.font
                        font.pixelSize: Style.font.body
                      }
                    }

                    Rectangle {
                      id: setBox
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      width: setColumn.implicitWidth + Style.space(24)
                      height: setColumn.implicitHeight + Style.space(20)
                      radius: Style.space(8)
                      color: Util.alpha(root.fg, 0.03)
                      border.color: root.hairline
                      border.width: 1

                      Column {
                        id: setColumn
                        anchors.centerIn: parent
                        spacing: Style.space(6)

                        Text {
                          textFormat: Text.PlainText
                          anchors.right: parent.right
                          text: !zone.c ? "SET" : zone.c.phase === "reading" ? "READING…"
                            : zone.c.phase === "sending" ? "SAVING…"
                            : zone.c.phase === "unknown" ? "CAN'T READ"
                            : "SET (" + ((zone.c.base || zone.t).mode || "—").toUpperCase() + ")"
                          color: zone.c && zone.c.phase === "unknown" ? root.bad : root.dim
                          font.family: root.font
                          font.pixelSize: Style.font.caption
                          font.letterSpacing: 1.5
                        }
                        Row {
                          spacing: Style.space(10)
                          readonly property bool adjustable: root.cliOk && !!zone.c && zone.c.adjustable
                          StepButton {
                            text: "−"
                            enabled: parent.adjustable
                            onClicked: root.nudge(zone.t, -1)
                          }
                          Text {
                            textFormat: Text.PlainText
                            anchors.verticalCenter: parent.verticalCenter
                            text: zone.c ? root.fmtSetpoint(zone.c.shown, (zone.c.base || zone.t).units) : "—"
                            // Dim until a fresh read backs the number up.
                            color: zone.c && zone.c.draft ? root.accent : zone.c && zone.c.base ? root.fg : root.dim
                            font.family: root.font
                            font.pixelSize: Style.font.heading
                            font.bold: true
                          }
                          StepButton {
                            text: "+"
                            enabled: parent.adjustable
                            onClicked: root.nudge(zone.t, 1)
                          }
                        }
                        Text {
                          textFormat: Text.PlainText
                          visible: !!zone.c && zone.c.note !== ""
                          anchors.right: parent.right
                          width: Math.min(implicitWidth, Style.space(150))
                          elide: Text.ElideRight
                          text: zone.c ? zone.c.note : ""
                          color: zone.c && zone.c.phase === "unknown" ? root.bad : root.dim
                          font.family: root.font
                          font.pixelSize: Style.font.caption
                        }
                      }
                    }
                  }

                  // this thermostat's mode, comfort and hold
                  Row {
                    width: parent.width
                    spacing: Style.space(6)
                    readonly property var s: zone.c && zone.c.base ? zone.c.base : zone.t
                    readonly property bool usable: root.cliOk && zone.t.available && !!zone.c && !zone.c.busy
                    readonly property real cell: (width - spacing * 4) / 5
                    Chip {
                      width: parent.cell; label: "HEAT"; glyph: "󰈸"
                      active: parent.s.mode === "heat"; enabled: parent.usable
                      onClicked: zone.c.act(["mode", "heat"])
                    }
                    Chip {
                      width: parent.cell; label: "COOL"; glyph: "󰜗"; activeTint: root.cool
                      active: parent.s.mode === "cool"; enabled: parent.usable
                      onClicked: zone.c.act(["mode", "cool"])
                    }
                    Chip {
                      width: parent.cell; label: "OFF"; glyph: "󰤆"; activeTint: root.fg
                      active: parent.s.mode === "off"; enabled: parent.usable
                      onClicked: zone.c.act(["mode", "off"])
                    }
                    Chip {
                      // ecobee's energy-saving comfort setting; pressed again, back to the schedule.
                      width: parent.cell; label: "AWAY"; glyph: "󰌪"
                      active: parent.s.comfort === "away"; enabled: parent.usable
                      onClicked: zone.c.act([parent.s.comfort === "away" ? "resume" : "away"])
                    }
                    Chip {
                      // Clears a hold (manual setpoint or comfort) and resumes the schedule.
                      width: parent.cell; label: "RESUME"; glyph: "󰥔"
                      enabled: parent.usable && (parent.s.comfort === "hold" || parent.s.comfort === "away")
                      onClicked: zone.c.act(["resume"])
                    }
                  }

                  Rectangle { width: parent.width; height: 1; color: root.hairline }

                  // trend + delta
                  Item {
                    width: parent.width
                    visible: root.trendHours > 0 || deltaText.text !== ""
                    height: Math.max(trendLabel.implicitHeight, Style.space(20))

                    Text {
                      textFormat: Text.PlainText
                      id: trendLabel
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                      visible: root.trendHours > 0
                      text: Number(root.trendHours.toFixed(1)) + "H TREND"
                      color: root.dim
                      font.family: root.font
                      font.pixelSize: Style.font.caption
                      font.letterSpacing: 1.5
                    }

                    Sparkline {
                      visible: root.trendHours > 0
                      anchors.left: trendLabel.right
                      anchors.leftMargin: Style.space(12)
                      anchors.right: deltaText.left
                      anchors.rightMargin: Style.space(12)
                      anchors.verticalCenter: parent.verticalCenter
                      height: Style.space(20)
                      points: root.history[zone.t.alias] || []
                      tint: root.accent
                      emptyColor: root.dim
                      fontFamily: root.font
                    }

                    Text {
                      id: deltaText
                      readonly property var delta: root.targetDelta(zone.t)
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.StyledText
                      text: delta === null ? "" : "Target Δ <font color='" + (delta >= 0 ? root.good : root.accent) + "'>"
                        + (delta >= 0 ? "+" : "") + delta.toFixed(1) + "°" + (zone.t.units === "C" ? "C" : "F") + "</font>"
                      color: root.dim
                      font.family: root.font
                      font.pixelSize: Style.font.bodySmall
                    }
                  }
                }
              }
            }
          }

          // ---- with one house of several thermostats, its away/resume sit here
          Item {
            visible: root.view === "zones" && !root.multiHouse && root.houseZones(root.zones.length ? root.zones[0].house : "").length > 1
            width: parent.width
            height: singleHouseActions.implicitHeight
            HouseActions {
              id: singleHouseActions
              anchors.horizontalCenter: parent.horizontalCenter
              house: root.zones.length ? (root.zones[0].house || "") : ""
            }
          }

          TextButton {
            visible: root.view === "zones"
            enabled: root.cliOk
            anchors.horizontalCenter: parent.horizontalCenter
            text: "+ ADD THERMOSTAT"
            onClicked: root.startAdding()
          }

          // ---- adding a thermostat
          Card {
            visible: root.view === "add"
            width: parent.width
            height: addBody.implicitHeight + Style.space(28)

            Column {
              id: addBody
              anchors.fill: parent
              anchors.margins: Style.space(14)
              spacing: Style.space(12)

              Item {
                width: parent.width
                height: addTitle.implicitHeight

                StepButton {
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  text: "×"
                  onClicked: root.stopAdding()
                }

              Row {
                id: addTitle
                spacing: Style.space(8)
                Text {
                  textFormat: Text.PlainText
                  text: "ADD THERMOSTAT"
                  color: root.fg
                  font.family: root.font
                  font.pixelSize: Style.font.subtitle
                  font.bold: true
                  font.letterSpacing: 1.5
                }
                Badge {
                  visible: root.pairingDemo
                  anchors.verticalCenter: parent.verticalCenter
                  text: "DEMO"
                  tint: root.cool
                }
              }
              }

              Rectangle { width: parent.width; height: 1; color: root.hairline }

              // scanning / starting / verifying
              Row {
                visible: ["scanning", "starting", "verifying"].includes(root.pairStage)
                spacing: Style.space(10)
                Text {
                  textFormat: Text.PlainText
                  id: spinner
                  text: "󰑓"
                  color: root.accent
                  font.family: root.font
                  font.pixelSize: Style.font.iconLarge
                  RotationAnimation on rotation {
                    running: spinner.visible
                    from: 0; to: 360; duration: 1200; loops: Animation.Infinite
                  }
                }
                Column {
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(2)
                  Text {
                    textFormat: Text.PlainText
                    text: root.pairStage === "scanning" ? "Looking for HomeKit thermostats…"
                      : root.pairStage === "starting" ? "Starting pairing with " + root.pairName + "…"
                      : "Checking the code…"
                    color: root.fg
                    font.family: root.font
                    font.pixelSize: Style.font.body
                  }
                  Text {
                    textFormat: Text.PlainText
                    visible: root.pairStage === "starting"
                    text: "It shows a fresh code once pairing starts."
                    color: root.dim
                    font.family: root.font
                    font.pixelSize: Style.font.bodySmall
                  }
                }
              }

              // found devices
              Column {
                visible: root.pairStage === "list"
                width: parent.width
                spacing: Style.space(8)

                Repeater {
                  model: root.found

                  Rectangle {
                    id: deviceRow
                    required property var modelData
                    readonly property bool ready: modelData.status === "ready to pair"
                    width: parent.width
                    height: Style.space(48)
                    radius: Style.space(8)
                    color: Util.alpha(root.fg, ready ? 0.05 : 0.02)
                    border.color: ready ? Util.alpha(root.good, 0.4) : root.hairline
                    border.width: 1

                    Column {
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(12)
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(2)
                      Text {
                        textFormat: Text.PlainText
                        text: deviceRow.modelData.name
                        color: root.fg
                        font.family: root.font
                        font.pixelSize: Style.font.body
                        font.bold: true
                      }
                      Text {
                        textFormat: Text.PlainText
                        text: [deviceRow.modelData.model, deviceRow.modelData.address].filter(x => x).join(" · ") || "paired as " + deviceRow.modelData.alias
                        color: root.dim
                        font.family: root.font
                        font.pixelSize: Style.font.caption
                      }
                    }

                    Row {
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(10)
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.space(8)
                      Badge {
                        anchors.verticalCenter: parent.verticalCenter
                        text: deviceRow.ready ? "READY" : deviceRow.modelData.status === "paired here" ? "PAIRED HERE" : "PAIRED ELSEWHERE"
                        tint: deviceRow.ready ? root.good : deviceRow.modelData.status === "paired here" ? root.accent : root.dim
                      }
                      TextButton {
                        visible: deviceRow.ready
                        text: "PAIR"
                        primary: true
                        onClicked: root.beginPair(deviceRow.modelData.id, deviceRow.modelData.name)
                      }
                    }
                  }
                }

                Text {
                  textFormat: Text.PlainText
                  visible: !root.found.some(d => d.status === "ready to pair")
                  width: parent.width
                  wrapMode: Text.WordWrap
                  text: "Nothing is ready to pair. A thermostat pairs with one HomeKit controller: remove it from Apple Home, or reset HomeKit on it (Menu → Settings → HomeKit)."
                  color: root.dim
                  font.family: root.font
                  font.pixelSize: Style.font.bodySmall
                }

                TextButton {
                  text: "RESCAN"
                  onClicked: root.scan()
                }
              }

              // code entry
              Column {
                visible: root.pairStage === "code"
                width: parent.width
                spacing: Style.space(8)

                Text {
                  textFormat: Text.PlainText
                  text: "Enter the code " + root.pairName + " shows now"
                  color: root.fg
                  font.family: root.font
                  font.pixelSize: Style.font.body
                  font.bold: true
                }
                Text {
                  textFormat: Text.PlainText
                  width: parent.width
                  wrapMode: Text.WordWrap
                  text: "On the thermostat: Menu → Settings → HomeKit. It changes when pairing starts, so use the one on screen now."
                  color: root.dim
                  font.family: root.font
                  font.pixelSize: Style.font.bodySmall
                }
                Text {
                  textFormat: Text.PlainText
                  visible: root.pairHint !== ""
                  text: root.pairHint
                  color: root.cool
                  font.family: root.font
                  font.pixelSize: Style.font.bodySmall
                }
                Row {
                  spacing: Style.space(8)
                  TextField {
                    id: codeField
                    width: Style.space(170)
                    placeholderText: "XXX-XX-XXX"
                    font.family: root.font
                    font.pixelSize: Style.font.heading
                    font.letterSpacing: 2
                    inputMethodHints: Qt.ImhDigitsOnly
                    onAccepted: root.submitCode(text)
                    onVisibleChanged: if (visible) { text = ""; forceActiveFocus() }
                  }
                  TextButton {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "PAIR"
                    primary: true
                    enabled: codeField.text.replace(/\D/g, "").length === 8
                    onClicked: root.submitCode(codeField.text)
                  }
                }
              }

              // done
              Column {
                visible: root.pairStage === "done"
                spacing: Style.space(6)
                Text {
                  textFormat: Text.PlainText
                  text: "󰄬 Paired " + (root.paired ? root.paired.name + " as '" + root.paired.alias + "'" : "")
                  color: root.good
                  font.family: root.font
                  font.pixelSize: Style.font.title
                  font.bold: true
                }
                Text {
                  textFormat: Text.PlainText
                  text: root.paired && root.paired.demo ? "Demo: nothing was saved; your pairings are unchanged."
                    : "It appears in the bar once the watcher picks it up (a few seconds)."
                  color: root.dim
                  font.family: root.font
                  font.pixelSize: Style.font.bodySmall
                }
                TextButton {
                  text: "DONE"
                  primary: true
                  onClicked: root.stopAdding()
                }
              }

              // error
              Column {
                visible: root.pairStage === "error"
                width: parent.width
                spacing: Style.space(8)
                Text {
                  textFormat: Text.PlainText
                  width: parent.width
                  wrapMode: Text.WordWrap
                  text: root.pairError
                  color: root.bad
                  font.family: root.font
                  font.pixelSize: Style.font.body
                }
                Row {
                  spacing: Style.space(8)
                  TextButton {
                    text: "TRY AGAIN"
                    primary: true
                    onClicked: root.pairDevice ? root.beginPair(root.pairDevice, root.pairName) : root.scan()
                  }
                  TextButton {
                    text: "BACK"
                    onClicked: root.scan()
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  // ---- building blocks

  component Card: Rectangle {
    radius: root.radius
    color: root.surface
    border.color: root.hairline
    border.width: 1
  }

  component Badge: Rectangle {
    id: badge
    property string text: ""
    property string glyph: ""
    property color tint: root.fg
    property bool filled: false
    property bool large: false
    implicitWidth: badgeRow.implicitWidth + Style.space(large ? 20 : 14)
    implicitHeight: badgeRow.implicitHeight + Style.space(large ? 12 : 6)
    width: implicitWidth
    height: implicitHeight
    radius: height / 2
    color: Util.alpha(tint, filled ? 0.16 : 0.08)
    border.color: Util.alpha(tint, 0.45)
    border.width: 1

    Row {
      id: badgeRow
      anchors.centerIn: parent
      spacing: Style.space(4)
      Text {
        textFormat: Text.PlainText
        visible: badge.glyph !== ""
        text: badge.glyph
        color: badge.tint
        font.family: root.font
        font.pixelSize: Style.font.caption
      }
      Text {
        textFormat: Text.PlainText
        text: badge.text
        color: badge.tint
        font.family: root.font
        font.pixelSize: badge.large ? Style.font.bodySmall : Style.font.caption
        font.bold: true
        font.letterSpacing: 1
      }
    }
  }

  component TextButton: Rectangle {
    id: textButton
    property string text: ""
    property bool primary: false
    property bool enabled: true
    signal clicked()
    width: textButtonLabel.implicitWidth + Style.space(22)
    height: Style.space(28)
    radius: Style.space(6)
    color: primary ? Util.alpha(root.accent, buttonMouse.containsMouse && enabled ? 0.26 : 0.16)
      : (buttonMouse.containsMouse && enabled ? Util.alpha(root.fg, 0.08) : "transparent")
    border.color: primary ? Util.alpha(root.accent, 0.6) : Util.alpha(root.fg, 0.18)
    border.width: 1
    opacity: enabled ? 1 : 0.4

    Text {
      textFormat: Text.PlainText
      id: textButtonLabel
      anchors.centerIn: parent
      text: textButton.text
      color: textButton.primary ? root.accent : root.fg
      font.family: root.font
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 1
    }
    MouseArea {
      id: buttonMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: textButton.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: if (textButton.enabled) textButton.clicked()
    }
  }

  component StepButton: Rectangle {
    id: step
    property string text: ""
    property bool enabled: true
    signal clicked()
    width: Style.space(26)
    height: width
    radius: Style.space(5)
    color: stepMouse.containsMouse && enabled ? Util.alpha(root.accent, 0.18) : Util.alpha(root.fg, 0.06)
    border.color: Util.alpha(root.fg, 0.18)
    border.width: 1
    opacity: enabled ? 1 : 0.35

    Text {
      textFormat: Text.PlainText
      anchors.centerIn: parent
      text: step.text
      color: root.fg
      font.family: root.font
      font.pixelSize: Style.font.title
      font.bold: true
    }
    MouseArea {
      id: stepMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: step.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: if (step.enabled) step.clicked()
    }
  }

  // One of a card's mode buttons: lit when it's the thermostat's current state.
  component Chip: Rectangle {
    id: chip
    property string glyph: ""
    property string label: ""
    property bool active: false
    property bool enabled: true
    property color activeTint: root.accent
    signal clicked()
    height: Style.space(28)
    radius: Style.space(6)
    color: active ? Util.alpha(activeTint, 0.14) : (chipMouse.containsMouse && enabled ? Util.alpha(root.fg, 0.06) : "transparent")
    border.color: active ? Util.alpha(activeTint, 0.6) : root.hairline
    border.width: 1
    opacity: enabled || active ? 1 : 0.4

    Row {
      anchors.centerIn: parent
      spacing: Style.space(4)
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: chip.glyph
        color: chip.active ? chip.activeTint : root.dim
        font.family: root.font
        font.pixelSize: Style.font.body
      }
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: chip.label
        color: chip.active ? chip.activeTint : root.dim
        font.family: root.font
        font.pixelSize: Style.font.caption
        font.bold: chip.active
        font.letterSpacing: 1
      }
    }
    MouseArea {
      id: chipMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: chip.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: if (chip.enabled) chip.clicked()
    }
  }

  // Away / resume for every thermostat in one house, each confirmed by a
  // second press. Only shown for a house with more than one thermostat.
  component HouseActions: Row {
    property string house: ""
    visible: root.houseZones(house).length > 1
    spacing: Style.space(6)
    TextButton {
      text: root.houseLabel("away", parent.house)
      primary: root.armed === "away:" + parent.house
      enabled: root.cliOk
      onClicked: root.houseAction("away", parent.house)
    }
    TextButton {
      text: root.houseLabel("resume", parent.house)
      primary: root.armed === "resume:" + parent.house
      enabled: root.cliOk
      onClicked: root.houseAction("resume", parent.house)
    }
  }

  // Temperature on a 50–90° dial (or 10–32°C), drawn from the top clockwise.
  component Ring: Item {
    id: ring
    property real size: 72
    property var value: null
    property color tint: root.accent
    property string glyph: ""
    readonly property real fraction: value === null || value === undefined ? 0
      : Math.max(0, Math.min(1, (value > 45 ? (value - 50) / 40 : (value - 10) / 22)))
    width: size
    height: size
    onFractionChanged: canvas.requestPaint()
    onTintChanged: canvas.requestPaint()

    Canvas {
      id: canvas
      anchors.fill: parent
      onPaint: {
        const ctx = getContext("2d")
        const r = width / 2 - 5
        ctx.reset()
        ctx.lineWidth = 6
        ctx.lineCap = "round"
        ctx.strokeStyle = Util.alpha(root.fg, 0.08)
        ctx.beginPath()
        ctx.arc(width / 2, height / 2, r, 0, Math.PI * 2)
        ctx.stroke()
        if (ring.fraction > 0) {
          ctx.strokeStyle = ring.tint
          ctx.beginPath()
          ctx.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * ring.fraction)
          ctx.stroke()
        }
      }
    }
    Text {
      textFormat: Text.PlainText
      anchors.centerIn: parent
      text: ring.glyph
      color: ring.tint
      font.family: root.font
      font.pixelSize: Style.font.iconLarge
    }
  }

  // The trend window's temperatures (trend_hours), with a dot on the latest.
  component Sparkline: Item {
    id: spark
    property var points: []
    property color tint: root.accent
    property color emptyColor: root.dim
    property string fontFamily: ""
    onPointsChanged: sparkCanvas.requestPaint()
    onWidthChanged: sparkCanvas.requestPaint()

    Text {
      textFormat: Text.PlainText
      visible: spark.points.length < 2
      anchors.verticalCenter: parent.verticalCenter
      text: "collecting…"
      color: spark.emptyColor
      font.family: spark.fontFamily
      font.pixelSize: Style.font.caption
    }

    Canvas {
      id: sparkCanvas
      anchors.fill: parent
      visible: spark.points.length >= 2
      onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        const pts = spark.points
        if (pts.length < 2) return
        const temps = pts.map(p => p[1])
        const lo = Math.min(...temps), hi = Math.max(...temps)
        const span = Math.max(hi - lo, 1)  // flat-ish lines stay flat-ish
        const t0 = pts[0][0], t1 = pts[pts.length - 1][0]
        const x = p => 3 + (width - 6) * (p[0] - t0) / Math.max(t1 - t0, 1)
        const y = p => height - 3 - (height - 6) * (p[1] - lo) / span
        ctx.strokeStyle = spark.tint
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(x(pts[0]), y(pts[0]))
        for (let i = 1; i < pts.length; i++) ctx.lineTo(x(pts[i]), y(pts[i]))
        ctx.stroke()
        const last = pts[pts.length - 1]
        ctx.fillStyle = spark.tint
        ctx.beginPath()
        ctx.arc(x(last), y(last), 2.5, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }
}
