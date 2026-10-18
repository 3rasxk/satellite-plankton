/**
 * The Sentinel-2 scene around a pin, filling the frame: the true-colour image
 * (10 m) and, in NDCI mode, the scene's NDCI heatmap laid over it as a
 * filter. Both come from GET /satellite-image for the same point and date
 * (the same scene and the same extent), so they line up pixel for pixel.
 *
 * The images' blank margins (transparent or white, where the thumbnail
 * extends past the scene's data) are cropped away and the rest is scaled to
 * cover the frame; nothing is invented to fill it. The ring marks the pin.
 */
import { useEffect, useRef, useState } from 'react'

const W = 960
const H = 720

function load(src) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

/** Bounding box of the pixels that carry data (opaque and not white). */
function dataBox(img) {
  const c = document.createElement('canvas')
  c.width = img.naturalWidth
  c.height = img.naturalHeight
  const g = c.getContext('2d', { willReadFrequently: true })
  g.drawImage(img, 0, 0)
  const { data, width, height } = g.getImageData(0, 0, c.width, c.height)
  let x0 = width
  let y0 = height
  let x1 = -1
  let y1 = -1
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4
      const blank = data[i + 3] < 16 || (data[i] > 248 && data[i + 1] > 248 && data[i + 2] > 248)
      if (!blank) {
        if (x < x0) x0 = x
        if (x > x1) x1 = x
        if (y < y0) y0 = y
        if (y > y1) y1 = y
      }
    }
  }
  if (x1 < 0) return { x: 0, y: 0, w: width, h: height }
  return { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 }
}

export default function SentinelView({ trueSrc, ndciSrc, label }) {
  const canvas = useRef(null)
  const key = `${trueSrc}|${ndciSrc}`
  const [drawn, setDrawn] = useState(null)
  useEffect(() => {
    if (!trueSrc || !canvas.current) return undefined
    let alive = true
    ;(async () => {
      const tc = await load(trueSrc)
      const box = dataBox(tc)
      // cover the frame: scale the box up to fill it, centred
      const k = Math.max(W / box.w, H / box.h)
      const sw = W / k
      const sh = H / k
      const sx = box.x + (box.w - sw) / 2
      const sy = box.y + (box.h - sh) / 2
      const ctx = canvas.current.getContext('2d')
      ctx.fillStyle = '#0b1a1f'
      ctx.fillRect(0, 0, W, H)
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(tc, sx, sy, sw, sh, 0, 0, W, H)
      if (ndciSrc) {
        const nd = await load(ndciSrc)
        const fx = nd.naturalWidth / tc.naturalWidth
        const fy = nd.naturalHeight / tc.naturalHeight
        ctx.globalAlpha = 0.62
        ctx.drawImage(nd, sx * fx, sy * fy, sw * fx, sh * fy, 0, 0, W, H)
        ctx.globalAlpha = 1
      }
      // the pin: the centre of the full image
      const cx = ((tc.naturalWidth / 2 - sx) / sw) * W
      const cy = ((tc.naturalHeight / 2 - sy) / sh) * H
      ctx.lineWidth = 5
      ctx.strokeStyle = '#fff'
      ctx.beginPath(); ctx.arc(cx, cy, 20, 0, Math.PI * 2); ctx.stroke()
      ctx.lineWidth = 2.5
      ctx.strokeStyle = '#1D1D1F'
      ctx.beginPath(); ctx.arc(cx, cy, 20, 0, Math.PI * 2); ctx.stroke()
      if (alive) setDrawn(key)
    })().catch(() => { if (alive) setDrawn(`error|${key}`) })
    return () => { alive = false }
  }, [trueSrc, ndciSrc, key])
  return (
    <>
      <canvas ref={canvas} width={W} height={H} style={{ width: '100%', height: '100%', display: drawn === key ? 'block' : 'none' }} role="img" aria-label={label} />
      {drawn !== key && !String(drawn).startsWith('error') && <>Drawing the image…</>}
      {String(drawn).startsWith('error') && <>Couldn’t draw the image.</>}
    </>
  )
}
