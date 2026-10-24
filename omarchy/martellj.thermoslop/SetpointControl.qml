// One thermostat's setpoint and mode changes, used by its card in Panel.qml
// and by scrolling on the bar. Its rule: never adjust from the cache. It reads
// the thermostat (`thermoslop status --live`) before the first change, presses
// build a draft that is never ignored, the draft goes out as one absolute
// `thermoslop set`, and the result comes from that command's own reply.
//
//   unread → reading → synced ⇄ editing → sending → synced, or editing again
//   if you pressed meanwhile. A failed read → unknown (a press retries it).
import QtQuick
import Quickshell.Io

Item {
  id: sc
  property string alias: ""
  // The watcher's cached state for this thermostat (shown until a read), set by the panel.
  property var t: null
  property string phase: "unread"   // unread, reading, unknown, synced, editing, sending
  property var base: null            // last value read from the thermostat or a reply
  property var draft: null           // what you're asking for: {mode, target} or {mode, heat, cool}
  property var sent: null
  property int queued: 0             // presses made before the first read finished
  property string note: ""
  property real baseAt: 0            // when `base` was read (s)
  property bool acting: false        // a mode/away/resume command is running
  property int idleMs: 1500          // quiet time after the last press before sending
  readonly property bool busy: acting || phase === "sending" || phase === "reading"
  readonly property var shown: draft || base || (t ? fromState(t) : null)
  readonly property bool adjustable: !!base && !acting && ["heat", "cool", "auto"].includes(base.mode)
    && ["synced", "editing", "sending"].includes(phase)

  function fmt(v) {
    if (!v || v.mode === "off") return "off"
    // Half degrees stay visible: rounding 66.5 to "67" would hide what the thermostat took.
    const n = x => x === null || x === undefined ? "—" : String(Math.round(x * 10) / 10)
    return v.mode === "auto" ? n(v.heat) + "–" + n(v.cool) + "°" : n(v.target) + "°"
  }

  function fromState(s) {
    return { mode: s.mode, target: s.target, heat: s.heat_setpoint, cool: s.cool_setpoint,
             units: s.units, comfort: s.comfort }
  }

  function same(a, b) {
    if (!a || !b || a.mode !== b.mode) return false
    const close = (x, y) => x !== null && x !== undefined && y !== null && y !== undefined && Math.abs(x - y) < 0.05
    return a.mode === "auto" ? close(a.heat, b.heat) && close(a.cool, b.cool) : close(a.target, b.target)
  }

  function stepped(v, step) {
    const n = Object.assign({}, v)
    if (n.mode === "auto") { n.heat += step; n.cool += step } else n.target += step
    return n
  }

  function read() {
    if (reader.running || phase === "editing" || phase === "sending" || acting) return
    phase = "reading"
    reader.command = ["thermoslop", "status", "--live", "--json", "-t", sc.alias]
    reader.running = true
  }

  function press(step) {
    if (!adjustable) {
      // Not read yet (or the read failed): read first, then apply the presses.
      if (["unread", "unknown", "reading"].includes(phase)) {
        queued += step
        read()
      }
      return
    }
    draft = stepped(draft || base, step)
    note = ""
    if (phase !== "sending") phase = same(draft, base) ? "synced" : "editing"
    if (phase === "synced") { draft = null; idle.stop() } else idle.restart()
  }

  function send() {
    sent = draft
    phase = "sending"
    const fmt = v => String(Math.round(v * 10) / 10)
    const args = sent.mode === "auto" ? ["--heat", fmt(sent.heat), "--cool", fmt(sent.cool)] : [fmt(sent.target)]
    writer.command = ["env", "THERMOSLOP_SOURCE=widget", "thermoslop", "set"].concat(args, ["-t", sc.alias, "--json"])
    writer.running = true
  }

  // Mode, away and resume: one command, then adopt the state it reports.
  function act(args) {
    if (acting || phase === "sending") return
    acting = true
    draft = null
    idle.stop()
    note = ""
    actor.command = ["env", "THERMOSLOP_SOURCE=widget", "thermoslop"].concat(args, ["-t", sc.alias, "--json"])
    actor.running = true
  }

  function parse(text) {
    let r = null
    try { r = JSON.parse(text || "null") } catch (e) {}
    return Array.isArray(r) ? r[0] : r
  }

  function adopt(s) {
    base = fromState(s)
    baseAt = s.updated_at || Date.now() / 1000
  }

  Timer {
    id: idle
    interval: sc.idleMs
    onTriggered: if (sc.phase === "editing") sc.send()
  }

  Process {
    id: reader
    stdout: StdioCollector {
      onStreamFinished: {
        const s = sc.parse(text)
        if (!s || s.error || !s.available) {
          sc.phase = "unknown"
          sc.note = s && (s.error || "can't reach the thermostat") || "couldn't read the thermostat"
          sc.queued = 0
          return
        }
        sc.adopt(s)
        sc.note = ""
        sc.phase = "synced"
        const q = sc.queued
        sc.queued = 0
        if (q) sc.press(q)
      }
    }
  }

  Process {
    id: writer
    stdout: StdioCollector {
      onStreamFinished: {
        const r = sc.parse(text)
        const sent = sc.sent
        sc.sent = null
        if (!r || r.error || !r.alias) {
          sc.note = r && r.error || "the change failed"
          sc.draft = null
          sc.phase = "synced"
          sc.read()   // show what the thermostat really has
          return
        }
        sc.adopt(r)
        sc.note = r.confirmed === false ? "sent; not confirmed yet"
          : sc.same(sc.base, sent) ? "" : "thermostat set " + sc.fmt(sc.base)
        if (sc.draft && !sc.same(sc.draft, sent) && sc.draft.mode === sc.base.mode) {
          // You pressed while it was saving: that newest value goes next.
          sc.phase = "editing"
          if (!idle.running) sc.send()
        } else {
          sc.draft = null
          sc.phase = "synced"
        }
      }
    }
  }

  Process {
    id: actor
    stdout: StdioCollector {
      onStreamFinished: {
        const r = sc.parse(text)
        sc.acting = false
        if (!r || r.error || !r.alias) {
          sc.note = r && r.error || "the change failed"
          sc.read()
          return
        }
        sc.adopt(r)
        sc.phase = "synced"
      }
    }
  }

  // When the watcher reports something different (a change at the
  // thermostat, the app, its schedule), an idle card reads the thermostat
  // again rather than trusting the file. A draft or a send in progress is
  // left alone.
  onTChanged: {
    if (!t || (phase !== "synced" && phase !== "unknown")) return
    if (!t.available) {
      if (phase === "synced") { phase = "unknown"; note = t.error || "can't reach the thermostat" }
      return
    }
    const s = fromState(t)
    if (phase === "unknown" || ((t.updated_at || 0) > baseAt && !(same(s, base) && s.comfort === base.comfort))) read()
  }
}
