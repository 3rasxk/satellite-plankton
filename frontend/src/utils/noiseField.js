/**
 * Deterministic multi-index composite simulation (NDCI + 2BDA + 3BDA).
 *
 * Accurate Upper Gulf of Thailand water masking with ray-casting point-in-polygon
 * algorithm so land is 100% transparent and water shows vibrant bloom indices.
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

/**
 * Detailed Upper Gulf of Thailand Water Polygon (normalised 0–1 coordinates).
 * Overlay bounds: Lat [12.55, 13.75], Lng [99.85, 101.15].
 * (0,0 is bottom-left / SW corner [12.55, 99.85]).
 */
const GULF_WATER_POLYGON = [
  // West Coast (Cha-am -> Phetchaburi -> Samut Songkhram)
  { x: 0.085, y: 0.000 }, // SW corner near Cha-am / Hua Hin [12.55, 99.96]
  { x: 0.100, y: 0.125 }, // Phetchaburi south
  { x: 0.123, y: 0.250 }, // Phetchaburi coast
  { x: 0.154, y: 0.375 }, // Hat Chao Samran [13.00, 100.05]
  { x: 0.185, y: 0.425 }, // Laem Phak Bia [13.06, 100.09]
  { x: 0.170, y: 0.542 }, // Ban Laem [13.20, 100.07]
  { x: 0.123, y: 0.675 }, // Don Hoi Lot / Mae Klong estuary [13.36, 100.01]

  // Inner Upper Gulf Coast (Samut Sakhon -> Bangkok -> Samut Prakan -> Chachoengsao)
  { x: 0.238, y: 0.758 }, // Samut Sakhon west [13.46, 100.16]
  { x: 0.323, y: 0.808 }, // Tha Chin estuary / Mahachai [13.52, 100.27]
  { x: 0.438, y: 0.817 }, // Bang Khun Thian coast [13.53, 100.42]
  { x: 0.569, y: 0.825 }, // Chao Phraya estuary / Bang Pu [13.54, 100.59]
  { x: 0.715, y: 0.783 }, // Bang Pu Mai / Khlong Dan [13.49, 100.78]
  { x: 0.831, y: 0.758 }, // Bang Pakong estuary [13.46, 100.93]

  // East Coast (Chonburi -> Si Racha -> Pattaya -> Sattahip)
  { x: 0.823, y: 0.650 }, // Chonburi / Ang Sila [13.33, 100.92]
  { x: 0.815, y: 0.600 }, // Bang Saen [13.27, 100.91]
  { x: 0.823, y: 0.517 }, // Si Racha [13.17, 100.92]
  { x: 0.800, y: 0.442 }, // Laem Chabang [13.08, 100.89]
  { x: 0.785, y: 0.283 }, // Pattaya / Jomtien [12.89, 100.87]
  { x: 0.800, y: 0.125 }, // Bang Saray / Sattahip [12.70, 100.89]
  { x: 0.846, y: 0.000 }, // Samae San / SE corner [12.55, 100.95]

  // Bottom boundary closing the open sea at south
  { x: 1.000, y: 0.000 }, // SE extent [12.55, 101.15]
  { x: 0.000, y: 0.000 }, // SW extent [12.55, 99.85]
]

/**
 * Standard ray-casting point-in-polygon test (handles complex non-convex polygons).
 * Returns true if (px, py) is seawater inside the Upper Gulf.
 */
function isWater(px, py) {
  let inside = false
  const n = GULF_WATER_POLYGON.length
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = GULF_WATER_POLYGON[i].x
    const yi = GULF_WATER_POLYGON[i].y
    const xj = GULF_WATER_POLYGON[j].x
    const yj = GULF_WATER_POLYGON[j].y

    const intersect = yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi
    if (intersect) inside = !inside
  }
  return inside
}

/**
 * Generates the composite NDCI + 2BDA + 3BDA field with domain warping.
 * Water pixels get index values in [0, 1]; land pixels get NaN.
 */
export function generateWarpedField(size, seed = 7, waterMask = true) {
  const field = new Float32Array(size * size)
  const scale = 3.5 / size
  const warpAmount = 1.8

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const nx01 = x / (size - 1)
      const ny01 = 1 - y / (size - 1) // 0 = south, 1 = north

      // Apply water mask: check if pixel is in seawater
      if (waterMask && !isWater(nx01, ny01)) {
        field[y * size + x] = NaN
        continue
      }

      const nx = x * scale
      const ny = y * scale

      // Multi-scale domain warp for fluid/swirling ocean eddies
      const warpX = fbm(nx, ny, seed + 91, 3)
      const warpY = fbm(nx, ny, seed + 193, 3)

      // 1. NDCI (Normalized Difference Chlorophyll Index)
      const ndci = fbm(nx + warpX * warpAmount, ny + warpY * warpAmount, seed, 4)

      // 2. 2BDA (Two-Band Difference Algorithm)
      const bda2 = fbm(nx * 1.2 + warpX * warpAmount * 0.9, ny * 1.2 + warpY * warpAmount * 1.1, seed + 37, 3)

      // 3. 3BDA (Three-Band Difference Algorithm)
      const bda3 = fbm(nx * 1.5 + warpX * warpAmount * 1.1, ny * 1.5 + warpY * warpAmount * 0.8, seed + 71, 3)

      // Estuary nutrient gradient (higher index in the inner bay near Chao Phraya / Tha Chin / Bang Pakong)
      const coastalInfluence = Math.max(0, Math.sin(nx01 * Math.PI) * 0.2 + (ny01 - 0.4) * 0.3)

      // Weighted composite index
      let composite = ndci * 0.45 + bda2 * 0.3 + bda3 * 0.25 + coastalInfluence

      // Normalize to [0, 1] range
      composite = (composite - 0.18) / 0.72
      field[y * size + x] = Math.min(1, Math.max(0, composite))
    }
  }
  return field
}

/**
 * Rich spectral color ramp matching the NDCI + 2BDA + 3BDA legend:
 * Dark Blue (-0.10) -> Azure Blue -> Turquoise/Cyan (0.10) -> Golden Yellow -> Orange -> Deep Red (>0.35)
 */
const STOPS = [
  { t: 0.00, rgb: [10, 35, 95] },    // Deep Blue (Clear/low chlorophyll, NDCI < -0.10)
  { t: 0.22, rgb: [25, 115, 185] },  // Ocean Blue
  { t: 0.42, rgb: [65, 195, 215] },  // Turquoise / Cyan (Baseline ~0.10)
  { t: 0.62, rgb: [240, 205, 45] },  // Golden Yellow (Elevated)
  { t: 0.80, rgb: [255, 130, 15] },  // Amber Orange (Watch)
  { t: 1.00, rgb: [195, 15, 15] },   // Deep Red (Severe bloom, NDCI > 0.35)
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

/**
 * Renders the composite index field to a canvas and returns a high-resolution PNG data URL.
 */
export function fieldToDataUrl(size = 512, seed = 7, opts = {}) {
  const waterMask = opts.waterMask !== false
  const field = generateWarpedField(size, seed, waterMask)
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  const imageData = ctx.createImageData(size, size)

  for (let i = 0; i < field.length; i++) {
    if (Number.isNaN(field[i])) {
      // Land — completely transparent
      imageData.data[i * 4] = 0
      imageData.data[i * 4 + 1] = 0
      imageData.data[i * 4 + 2] = 0
      imageData.data[i * 4 + 3] = 0
    } else {
      const [r, g, b] = rampColor(field[i])
      imageData.data[i * 4] = r
      imageData.data[i * 4 + 1] = g
      imageData.data[i * 4 + 2] = b
      imageData.data[i * 4 + 3] = 210 // Vivid and rich colors over water
    }
  }
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}
