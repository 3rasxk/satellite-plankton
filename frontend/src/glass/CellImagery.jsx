/**
 * Satellite view of the place a pin sits on, drawn on a canvas, about 2 km
 * across: Esri World Imagery tiles, and -- in NDCI mode -- the map's own NDCI
 * (per pixel, about 40 m, from the same Sentinel-2 scenes; sea only, clear
 * where there is no NDCI) laid over them. Used for the NDCI tab, and for the
 * true-colour tab when the Sentinel-2 render of the scene is unavailable.
 */
import { useEffect, useRef, useState } from 'react'
import { merc } from './placement.js'
import { loadCleanImage } from './cleanImage.js'
import { MAP_BOUNDS } from '../utils/mapBounds.js'

const W = 480
const H = 360
const TZ = 15
const TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile'

function tileImage(z, x, y) {
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => resolve(null)
    img.src = `${TILE}/${z}/${y}/${x}`
  })
}

async function drawSatellite(ctx, lat, lng) {
  const n = 2 ** TZ * 256
  const wx = ((lng + 180) / 360) * n
  const wy = ((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) * n
  const x0 = wx - W / 2
  const y0 = wy - H / 2
  const tiles = []
  for (let ty = Math.floor(y0 / 256); ty <= Math.floor((y0 + H) / 256); ty += 1) {
    for (let tx = Math.floor(x0 / 256); tx <= Math.floor((x0 + W) / 256); tx += 1) tiles.push([tx, ty])
  }
  const imgs = await Promise.all(tiles.map(([tx, ty]) => tileImage(TZ, tx, ty)))
  ctx.fillStyle = '#E5E5EA'
  ctx.fillRect(0, 0, W, H)
  let drawn = 0
  imgs.forEach((img, i) => {
    if (!img) return
    ctx.drawImage(img, tiles[i][0] * 256 - x0, tiles[i][1] * 256 - y0)
    drawn += 1
  })
  if (drawn === 0) throw new Error('no tiles')
}

function drawNdci(ctx, img, lat, lng) {
  const [[S, Wd], [N, E]] = MAP_BOUNDS
  const n = 2 ** TZ * 256
  const unit = (2 * Math.PI) / n
  const lng0 = lng - ((W / 2) / n) * 360
  const lng1 = lng + ((W / 2) / n) * 360
  const mTop = merc(lat) + (H / 2) * unit
  const mBot = merc(lat) - (H / 2) * unit
  const yT = merc(N)
  const yB = merc(S)
  const sx0 = ((lng0 - Wd) / (E - Wd)) * img.naturalWidth
  const sx1 = ((lng1 - Wd) / (E - Wd)) * img.naturalWidth
  const sy0 = ((yT - mTop) / (yT - yB)) * img.naturalHeight
  const sy1 = ((yT - mBot) / (yT - yB)) * img.naturalHeight
  ctx.imageSmoothingEnabled = false
  ctx.globalAlpha = 0.92
  ctx.drawImage(img, sx0, sy0, sx1 - sx0, sy1 - sy0, 0, 0, W, H)
  ctx.globalAlpha = 1
}

function ring(ctx) {
  ctx.lineWidth = 3
  ctx.strokeStyle = '#fff'
  ctx.beginPath(); ctx.arc(W / 2, H / 2, 11, 0, Math.PI * 2); ctx.stroke()
  ctx.lineWidth = 1.5
  ctx.strokeStyle = '#1D1D1F'
  ctx.beginPath(); ctx.arc(W / 2, H / 2, 11, 0, Math.PI * 2); ctx.stroke()
}

export default function CellImagery({ raster, lat, lng, mode, onFine }) {
  const canvas = useRef(null)
  const key = `${mode}|${lat}|${lng}|${raster?.run_id}`
  const [loaded, setLoaded] = useState(null)
  const [failed, setFailed] = useState(null)
  useEffect(() => {
    if (lat == null || lng == null || !canvas.current) return undefined
    let alive = true
    const ctx = canvas.current.getContext('2d')
    const run = async () => {
      await drawSatellite(ctx, lat, lng)
      if (mode === 'ndci') {
        const { img, fine } = await loadCleanImage(raster)
        drawNdci(ctx, img, lat, lng)
        onFine?.(fine)
      }
      if (alive) { ring(ctx); setLoaded(key) }
    }
    run().catch(() => { if (alive) setFailed(key) })
    return () => { alive = false }
  }, [mode, lat, lng, raster, key]) // eslint-disable-line react-hooks/exhaustive-deps
  const state = loaded === key ? 'ready' : failed === key ? 'error' : 'loading'
  return (
    <>
      <canvas ref={canvas} width={W} height={H} style={{ width: '100%', height: '100%', display: state === 'ready' ? 'block' : 'none' }} role="img" aria-label={`${mode === 'rgb' ? 'Satellite' : 'NDCI over satellite'} view around the pin`} />
      {state === 'loading' && <>Loading the imagery…</>}
      {state === 'error' && <>Couldn’t load the imagery.</>}
    </>
  )
}
