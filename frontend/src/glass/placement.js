/**
 * Where a station's pin is drawn: the nearest pixel of the served NDCI
 * overlay that holds a usable value (opaque), so the pin sits on the
 * measured area, not on cloud, land or an empty cell.
 *
 * Data source: the overlay PNG of GET /raster-scan (`overlay_url`, transparent
 * = no usable reading) and its `bounds`. The image is drawn once to a
 * canvas (downscaled to at most 1024 px) and read for its alpha channel.
 * Nothing is invented: a station keeps its real coordinates (shown in the
 * panel, marked on the map by a small dot joined to the pin) and a pin is
 * moved only within MAX_DEG of it; farther, or with no overlay, it stays.
 */
import { useEffect, useMemo, useState } from 'react'
import { apiAssetUrl } from '../api/client.js'

export const MAX_DEG = 0.2
const MAX_SIDE = 1024
const OPAQUE = 24
const HALF = 4 // window half-size in px: a pin needs solid measured pixels all around
const SOLID = 0.92

export const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))
export const unmerc = (y) => ((2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180) / Math.PI

/** Pure: nearest opaque cell to (lat, lng) in an alpha grid over `bounds`. */
export function nearestValid({ alpha, width, height, bounds, lat, lng, maxDeg = MAX_DEG }) {
  const [[south, west], [north, east]] = bounds
  const yTop = merc(north)
  const yBot = merc(south)
  const toX = (lo) => ((lo - west) / (east - west)) * width
  const toY = (la) => ((yTop - merc(la)) / (yTop - yBot)) * height
  const x0 = Math.floor(toX(lng))
  const y0 = Math.floor(toY(lat))
  // Summed-area table of opaque pixels: a cell counts only when its whole
  // (2*HALF+1)^2 window is (almost) all measured, so a pin never sits on an
  // edge, a speckle or beside a hole.
  const sat = new Uint32Array((width + 1) * (height + 1))
  for (let y = 0; y < height; y += 1) {
    let row = 0
    for (let x = 0; x < width; x += 1) {
      row += alpha[y * width + x] >= OPAQUE ? 1 : 0
      sat[(y + 1) * (width + 1) + x + 1] = sat[y * (width + 1) + x + 1] + row
    }
  }
  const ok = (x, y) => {
    if (x < HALF || y < HALF || x >= width - HALF || y >= height - HALF) return false
    const x1 = x - HALF
    const y1 = y - HALF
    const x2 = x + HALF + 1
    const y2 = y + HALF + 1
    const n = sat[y2 * (width + 1) + x2] - sat[y1 * (width + 1) + x2] - sat[y2 * (width + 1) + x1] + sat[y1 * (width + 1) + x1]
    return n >= SOLID * (2 * HALF + 1) * (2 * HALF + 1)
  }
  const back = (x, y) => ({
    lat: unmerc(yTop - ((y + 0.5) / height) * (yTop - yBot)),
    lng: west + ((x + 0.5) / width) * (east - west),
  })
  if (ok(x0, y0)) return { ...back(x0, y0), moved: false }
  const maxR = Math.ceil((maxDeg / (east - west)) * width)
  for (let r = 1; r <= maxR; r += 1) {
    let best = null
    let bestD = Infinity
    for (let dx = -r; dx <= r; dx += 1) {
      for (const dy of [-r, r]) {
        const d = dx * dx + dy * dy
        if (d < bestD && ok(x0 + dx, y0 + dy)) { best = [x0 + dx, y0 + dy]; bestD = d }
      }
    }
    for (let dy = -r + 1; dy <= r - 1; dy += 1) {
      for (const dx of [-r, r]) {
        const d = dx * dx + dy * dy
        if (d < bestD && ok(x0 + dx, y0 + dy)) { best = [x0 + dx, y0 + dy]; bestD = d }
      }
    }
    if (best) return { ...back(best[0], best[1]), moved: true }
  }
  return null
}

async function readAlpha(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`overlay ${res.status}`)
  const bmp = await createImageBitmap(await res.blob())
  const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height))
  const width = Math.max(1, Math.round(bmp.width * k))
  const height = Math.max(1, Math.round(bmp.height * k))
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(bmp, 0, 0, width, height)
  const rgba = ctx.getImageData(0, 0, width, height).data
  const alpha = new Uint8Array(width * height)
  for (let i = 0; i < alpha.length; i += 1) alpha[i] = rgba[i * 4 + 3]
  return { alpha, width, height }
}

const km = (aLat, aLng, bLat, bLng) => Math.hypot((bLat - aLat) * 111, (bLng - aLng) * 111 * Math.cos((aLat * Math.PI) / 180))

/**
 * Pure: give each station the nearest still-free flagged cell within
 * MAX_DEG (one cell per station, nearest pairs first).
 * `cells`: [{lat, lng, z, level}]. Returns Map(stationId -> cell).
 */
export function assignFlagged(stations, cells, maxDeg = MAX_DEG) {
  const pairs = []
  stations.forEach((s) => {
    if (s.lat === null || s.lng === null) return
    cells.forEach((c, i) => {
      const d = Math.hypot(c.lat - s.lat, c.lng - s.lng)
      if (d <= maxDeg) pairs.push({ id: s.id, i, d })
    })
  })
  pairs.sort((a, b) => a.d - b.d)
  const out = new Map()
  const used = new Set()
  pairs.forEach((p) => {
    if (out.has(p.id) || used.has(p.i)) return
    out.set(p.id, cells[p.i])
    used.add(p.i)
  })
  return out
}

/**
 * Stations with `pinLat`/`pinLng` (and `moved`, `movedKm`) set. A station
 * with a TEST-flagged cell nearby (robust z at or above the TEST watch
 * boundary, from GET /raster-scan/highlights) is drawn on that cell
 * (`flagged`: {z, level}); otherwise on the nearest solid measured pixel.
 */
export function usePlacedStations(stations, raster, cells = []) {
  const [grid, setGrid] = useState(null)
  const url = typeof raster?.overlay_url === 'string' ? apiAssetUrl(raster.overlay_url) : null
  useEffect(() => {
    if (!url) return undefined
    let alive = true
    readAlpha(url).then((g) => { if (alive) setGrid({ url, ...g }) }).catch(() => { if (alive) setGrid(null) })
    return () => { alive = false }
  }, [url])
  const bounds = raster?.bounds
  return useMemo(() => {
    if (!stations) return null
    const flagged = assignFlagged(stations, cells)
    return stations.map((s) => {
      const base = { ...s, pinLat: s.lat, pinLng: s.lng, moved: false, movedKm: 0, flagged: null }
      const cell = flagged.get(s.id)
      if (cell) {
        return { ...base, pinLat: cell.lat, pinLng: cell.lng, moved: true, movedKm: km(s.lat, s.lng, cell.lat, cell.lng), flagged: { z: cell.z, level: cell.level } }
      }
      if (!grid || grid.url !== url || !bounds || s.lat === null || s.lng === null) return base
      const hit = nearestValid({ ...grid, bounds, lat: s.lat, lng: s.lng })
      if (!hit || !hit.moved) return base
      return { ...base, pinLat: hit.lat, pinLng: hit.lng, moved: true, movedKm: km(s.lat, s.lng, hit.lat, hit.lng) }
    })
  }, [stations, grid, url, bounds, cells])
}
