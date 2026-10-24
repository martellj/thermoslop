// Drives the plugin's SetpointControl.qml against tests/qml/fake-thermoslop.
// tests/test_setpoint_qml.py copies this and SetpointControl.qml into one
// folder (Quickshell won't import from outside its config folder). Each step
// logs a "HARNESS" line.
import QtQuick
import Quickshell

ShellRoot {
  SetpointControl { id: c; alias: "cabin"; idleMs: 300 }

  function log(m) { console.log("HARNESS " + m) }

  property var steps: [
    [1, () => { log("unread adjustable=" + c.adjustable); c.press(1) }],
    [150, () => log("reading adjustable=" + c.adjustable + " phase=" + c.phase + " queued=" + c.queued)],
    [1000, () => { c.press(1); c.press(1) }],
    [2000, () => { c.press(1); log("during-send phase=" + c.phase + " draft=" + c.draft.target) }],
    [8000, () => { log("settled base=" + c.base.target + " phase=" + c.phase + " draft=" + c.draft); c.press(-1) }],
    [11500, () => { log("adjusted base=" + c.base.target + " phase=" + c.phase + " note=" + c.note); Qt.quit() }],
  ]

  Component.onCompleted: {
    for (const s of steps) {
      const t = Qt.createQmlObject("import QtQuick; Timer {}", this)
      t.interval = s[0]
      t.triggered.connect(s[1])
      t.start()
    }
  }
}
