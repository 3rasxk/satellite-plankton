/**
 * The NDCI image for the map: sea only; transparent where there is no NDCI.
 *
 * Data source: the overlay PNG of GET /raster-scan (200 m cells, transparent
 * where nothing was measured) placed by its `bounds`, and Esri's light-gray
 * base tiles, read only to tell sea from land (flat sea colour vs land).
 * One image covers the whole map extent (MAP_BOUNDS):
 *   - sea with a measured NDCI cell: that cell's colour (the API's ramp);
 *   - sea with no NDCI -- cloud, gaps, and all the Gulf outside the scanned
 *     area: transparent (the base map shows), never coloured or filled;
 *   - land: transparent (the base map shows). Measured cells on land, mud
 *     flats and river banks are dropped, and isolated specks (fewer than 9 of
 *     the 25 cells around them measured) too.
 * Nothing is interpolated or blurred: the image keeps the overlay's own
 * resolution (the ~40 m Sentinel-2 NDCI when `hires`, else the 200 m raster)
 * and is scaled with `image-rendering: pixelated` (global.css), so edges stay
 * sharp at every zoom.
 */
import { apiAssetUrl } from '../api/client.js'
import { merc, unmerc } from './placement.js'
import { MAP_BOUNDS } from '../utils/mapBounds.js'

const SCALE = 1 // drawn at the source's own resolution; the browser scales it without smoothing
const MAX_PX_PER_DEG = 1800 // cap for the high-resolution image (about 55 m)
const BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile'
export const cache = new Map()

const worldX = (lng, tz) => ((lng + 180) / 360) * 2 ** tz * 256
const worldY = (lat, tz) => ((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) * 2 ** tz * 256

function tile(x, y, tz) {
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    img.src = `${BASE}/${tz}/${y}/${x}`
  })
}

/** Sea mask (1 = sea) for an extent, from the base map's flat sea colour. */
async function seaMask(bounds, w, h, tz) {
  const [[south, west], [north, east]] = bounds
  const x0 = Math.floor(worldX(west, tz) / 256)
  const x1 = Math.floor(worldX(east, tz) / 256)
  const y0 = Math.floor(worldY(north, tz) / 256)
  const y1 = Math.floor(worldY(south, tz) / 256)
  const cw = (x1 - x0 + 1) * 256
  const ch = (y1 - y0 + 1) * 256
  const canvas = document.createElement('canvas')
  canvas.width = cw
  canvas.height = ch
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  const jobs = []
  for (let ty = y0; ty <= y1; ty += 1) for (let tx = x0; tx <= x1; tx += 1) jobs.push([tx, ty])
  const imgs = await Promise.all(jobs.map(([tx, ty]) => tile(tx, ty, tz)))
  let drawn = 0
  imgs.forEach((img, i) => { if (img) { ctx.drawImage(img, (jobs[i][0] - x0) * 256, (jobs[i][1] - y0) * 256); drawn += 1 } })
  if (drawn < jobs.length * 0.9) throw new Error('base tiles missing')
  const px = ctx.getImageData(0, 0, cw, ch).data
  const yTop = merc(north)
  const yBot = merc(south)
  const mask = new Uint8Array(w * h)
  for (let y = 0; y < h; y += 1) {
    const lat = unmerc(yTop - ((y + 0.5) / h) * (yTop - yBot))
    const sy = Math.floor(worldY(lat, tz) - y0 * 256)
    for (let x = 0; x < w; x += 1) {
      const lng = west + ((x + 0.5) / w) * (east - west)
      const sx = Math.floor(worldX(lng, tz) - x0 * 256)
      if (sx < 0 || sy < 0 || sx >= cw || sy >= ch) continue
      const i = (sy * cw + sx) * 4
      // Sea in this style is a flat (208,207,212); land is 230+, inland
      // water has no blue tint.
      if (Math.abs(px[i] - 208) <= 6 && Math.abs(px[i + 1] - 207) <= 6 && Math.abs(px[i + 2] - 212) <= 6 && px[i + 2] - px[i] >= 2) mask[y * w + x] = 1
    }
  }
  // Only the sea connected to the Gulf: reservoirs, ponds and lakes inland
  // have the same colour but are not sea.
  const [sLat, sLng] = [12.9, 100.5]
  const sx = Math.round(((sLng - west) / (east - west)) * w)
  const sy = Math.round(((yTop - merc(sLat)) / (yTop - yBot)) * h)
  const connected = new Uint8Array(w * h)
  const queue = new Int32Array(w * h)
  let head = 0
  let tail = 0
  const start = sy * w + sx
  if (mask[start]) {
    connected[start] = 1
    queue[tail] = start
    tail += 1
  }
  while (head < tail) {
    const i = queue[head]
    head += 1
    const x = i % w
    const y = (i - x) / w
    if (x > 0 && mask[i - 1] && !connected[i - 1]) { connected[i - 1] = 1; queue[tail] = i - 1; tail += 1 }
    if (x < w - 1 && mask[i + 1] && !connected[i + 1]) { connected[i + 1] = 1; queue[tail] = i + 1; tail += 1 }
    if (y > 0 && mask[i - w] && !connected[i - w]) { connected[i - w] = 1; queue[tail] = i - w; tail += 1 }
    if (y < h - 1 && mask[i + w] && !connected[i + w]) { connected[i + w] = 1; queue[tail] = i + w; tail += 1 }
  }
  return tail > 0 ? connected : mask
}

/** Keep a measured cell only if at least 9 of the 25 cells around it are measured. */
function despeckle(rgba, w, h) {
  const has = new Uint8Array(w * h)
  for (let i = 0; i < w * h; i += 1) has[i] = rgba[i * 4 + 3] > 0 ? 1 : 0
  const keep = new Uint8Array(w * h)
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      if (!has[y * w + x]) continue
      let c = 0
      for (let dy = -2; dy <= 2; dy += 1) {
        for (let dx = -2; dx <= 2; dx += 1) {
          const xx = x + dx
          const yy = y + dy
          if ((dx || dy) && xx >= 0 && yy >= 0 && xx < w && yy < h && has[yy * w + xx]) c += 1
        }
      }
      keep[y * w + x] = c >= 9 ? 1 : 0
    }
  }
  return keep
}

/** `hires`: the ~40 m Sentinel-2 NDCI image instead of the 200 m raster. */
export async function build(url, bounds, hires = false) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`overlay ${res.status}`)
  const bmp = await createImageBitmap(await res.blob())
  const w = bmp.width
  const h = bmp.height
  const src = document.createElement('canvas')
  src.width = w
  src.height = h
  const sctx = src.getContext('2d', { willReadFrequently: true })
  sctx.drawImage(bmp, 0, 0)
  const data = sctx.getImageData(0, 0, w, h).data
  let alpha = 235
  for (let i = 3; i < data.length; i += 4) if (data[i] > 0) { alpha = data[i]; break }
  // Specks are judged on the 200 m cells; the ~40 m image is not despeckled.
  const keep = hires ? null : despeckle(data, w, h)

  // The whole map extent, at the overlay's own resolution.
  const [[S, W], [N, E]] = MAP_BOUNDS
  const [[s0, w0], [n0, e0]] = bounds
  const PX_PER_DEG = Math.min(MAX_PX_PER_DEG, w / (e0 - w0))
  const EW = Math.round((E - W) * PX_PER_DEG)
  const yT = merc(N)
  const yB = merc(S)
  const EH = Math.round((EW * (yT - yB)) / (((E - W) * Math.PI) / 180))
  const sea = await seaMask(MAP_BOUNDS, EW, EH, hires ? 11 : 10)
  const out = new Uint8ClampedArray(EW * EH * 4)
  const oyT = merc(n0)
  const oyB = merc(s0)
  for (let y = 0; y < EH; y += 1) {
    const lat = unmerc(yT - ((y + 0.5) / EH) * (yT - yB))
    const oy = Math.floor(((oyT - merc(lat)) / (oyT - oyB)) * h)
    for (let x = 0; x < EW; x += 1) {
      const i = y * EW + x
      if (!sea[i]) continue
      const lng = W + ((x + 0.5) / EW) * (E - W)
      const ox = Math.floor(((lng - w0) / (e0 - w0)) * w)
      const inside = ox >= 0 && oy >= 0 && ox < w && oy < h
      const j = oy * w + ox
      if (inside && (hires ? data[j * 4 + 3] > 0 : keep[j])) {
        out[i * 4] = data[j * 4]
        out[i * 4 + 1] = data[j * 4 + 1]
        out[i * 4 + 2] = data[j * 4 + 2]
        out[i * 4 + 3] = hires ? data[j * 4 + 3] : alpha
      }
      // else: sea with no NDCI stays transparent, so the base map shows through
    }
  }
  const base = document.createElement('canvas')
  base.width = EW
  base.height = EH
  base.getContext('2d').putImageData(new ImageData(out, EW, EH), 0, 0)
  const big = document.createElement('canvas')
  big.width = EW * SCALE
  big.height = EH * SCALE
  const bctx = big.getContext('2d')
  bctx.imageSmoothingEnabled = false
  bctx.drawImage(base, 0, 0, big.width, big.height)
  return big.toDataURL('image/png')
}

/**
 * The cleaned NDCI image of the whole map extent (MAP_BOUNDS), as an Image:
 * the ~40 m Sentinel-2 NDCI when it can be had, else the 200 m raster.
 * Returns { img, fine }.
 */
export async function loadCleanImage(data) {
  const raw = typeof data?.overlay_url === 'string' ? apiAssetUrl(data.overlay_url) : null
  const bounds = data?.bounds
  if (!raw || !bounds) throw new Error('no overlay')
  const hiresRaw = Number.isInteger(data?.run_id) ? apiAssetUrl(`/raster-scan/ndci-hires.png?run_id=${data.run_id}`) : null
  let href = null
  let fine = false
  if (hiresRaw) {
    try {
      if (!cache.has(hiresRaw)) cache.set(hiresRaw, build(hiresRaw, MAP_BOUNDS, true))
      href = await cache.get(hiresRaw)
      fine = true
    } catch {
      cache.delete(hiresRaw)
    }
  }
  if (!href) {
    if (!cache.has(raw)) cache.set(raw, build(raw, bounds))
    href = await cache.get(raw)
  }
  const img = await new Promise((resolve, reject) => {
    const el = new Image()
    el.onload = () => resolve(el)
    el.onerror = reject
    el.src = href
  })
  return { img, fine }
}
