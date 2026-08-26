/**
 * Deterministic 2D value noise with domain warp, used only to paint the
 * decorative NDCI-mode map overlay (docs/superpowers/specs/2026-08-26-
 * hab-sentinel-dashboard-design.md, Screen 1). This is NOT a real
 * per-pixel index product — there is no backend raster endpoint — it is
 * illustrative texture only, and every place it's shown must say so
 * (see NdciRasterOverlay.jsx). Self-contained (no noise library) so it
 * has zero new dependencies.
 */
function hash(x, y, seed) {
  const s = Math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453123
  return s - Math.floor(s)
}

function smoothstep(t) {
  return t * t * (3 - 2 * t)
}

function valueNoise(x, y, seed) {
  const x0 = Math.floor(x)
  const y0 = Math.floor(y)
  const tx = smoothstep(x - x0)
  const ty = smoothstep(y - y0)
  const v00 = hash(x0, y0, seed)
  const v10 = hash(x0 + 1, y0, seed)
  const v01 = hash(x0, y0 + 1, seed)
  const v11 = hash(x0 + 1, y0 + 1, seed)
  const a = v00 + (v10 - v00) * tx
  const b = v01 + (v11 - v01) * tx
  return a + (b - a) * ty
}

function fbm(x, y, seed, octaves = 4) {
  let value = 0
  let amplitude = 0.5
  let freq = 1
  for (let i = 0; i < octaves; i++) {
    value += valueNoise(x * freq, y * freq, seed) * amplitude
    amplitude *= 0.5
    freq *= 2
  }
  return value
}

/** Returns a Float32Array of length size*size, values in [0,1], domain-warped. */
export function generateWarpedField(size, seed = 7) {
  const field = new Float32Array(size * size)
  const scale = 4 / size
  const warpAmount = 1.6
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const nx = x * scale
      const ny = y * scale
      const warpX = fbm(nx, ny, seed + 91, 3)
      const warpY = fbm(nx, ny, seed + 193, 3)
      const v = fbm(nx + warpX * warpAmount, ny + warpY * warpAmount, seed, 4)
      field[y * size + x] = Math.min(1, Math.max(0, v))
    }
  }
  return field
}

// Diverging ramp: dark blue -> pale cyan -> orange -> dark red, matching
// the map legend's -0.10 / 0.10 / >0.35 stops (RiskLegend NDCI variant).
const STOPS = [
  { t: 0, rgb: [10, 30, 90] },
  { t: 0.4, rgb: [176, 224, 230] },
  { t: 0.7, rgb: [255, 159, 10] },
  { t: 1, rgb: [139, 0, 0] },
]

export function rampColor(t) {
  for (let i = 0; i < STOPS.length - 1; i++) {
    const a = STOPS[i]
    const b = STOPS[i + 1]
    if (t >= a.t && t <= b.t) {
      const lt = (t - a.t) / (b.t - a.t)
      return [
        Math.round(a.rgb[0] + (b.rgb[0] - a.rgb[0]) * lt),
        Math.round(a.rgb[1] + (b.rgb[1] - a.rgb[1]) * lt),
        Math.round(a.rgb[2] + (b.rgb[2] - a.rgb[2]) * lt),
      ]
    }
  }
  return STOPS[STOPS.length - 1].rgb
}

/** Renders the field to a canvas and returns a PNG data URL. */
export function fieldToDataUrl(size = 256, seed = 7) {
  const field = generateWarpedField(size, seed)
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  const imageData = ctx.createImageData(size, size)
  for (let i = 0; i < field.length; i++) {
    const [r, g, b] = rampColor(field[i])
    imageData.data[i * 4] = r
    imageData.data[i * 4 + 1] = g
    imageData.data[i * 4 + 2] = b
    imageData.data[i * 4 + 3] = 200 // slightly translucent so the basemap reads through
  }
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}
