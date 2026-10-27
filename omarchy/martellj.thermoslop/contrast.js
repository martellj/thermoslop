.pragma library
// WCAG contrast for the panel's colors. Colors are {r, g, b} in 0..1 (a QML
// color has those fields too). Used by Panel.qml, and run under Node by
// tests/test_contrast.py over every Omarchy theme, so the test checks this
// exact code. A theme's own color is kept when it's readable; otherwise it's
// moved toward black or white, only as far as needed.

function channel(c) {
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function luminance(c) {
  return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b)
}

function ratio(a, b) {
  const la = luminance(a), lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

// `fg` drawn at `alpha` over `bg`.
function blend(fg, bg, alpha) {
  return { r: fg.r * alpha + bg.r * (1 - alpha), g: fg.g * alpha + bg.g * (1 - alpha), b: fg.b * alpha + bg.b * (1 - alpha) }
}

// `c`, or the closest mix of it with black or white (away from `bg`) that
// reaches `target`:1 against `bg`.
function readable(c, bg, target) {
  const plain = { r: c.r, g: c.g, b: c.b }
  if (ratio(plain, bg) >= target) return plain
  const toward = luminance(bg) < 0.5 ? { r: 1, g: 1, b: 1 } : { r: 0, g: 0, b: 0 }
  for (let t = 0.02; t <= 1.0001; t += 0.02) {
    const mixed = blend(toward, plain, t)
    if (ratio(mixed, bg) >= target) return mixed
  }
  return toward
}

// The smallest alpha (from `floor`) at which `fg` over `bg` reaches `target`:1,
// for outlines that should stay subtle where the theme allows it.
function alphaFor(fg, bg, target, floor) {
  for (let a = floor; a <= 1.0001; a += 0.02) {
    if (ratio(blend(fg, bg, a), bg) >= target) return Math.min(1, a)
  }
  return 1
}

if (typeof module !== "undefined") module.exports = { luminance, ratio, blend, readable, alphaFor }
