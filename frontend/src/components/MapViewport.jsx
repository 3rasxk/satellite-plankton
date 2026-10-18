/**
 * MapViewport: keeps the map's own content clear of the floating glass
 * panels (design reference). Renders nothing; lives inside the Leaflet map.
 *
 *   1. Fit: with nothing selected the raster bounds are fitted with padding
 *      that clears the left card (when shown), the top bar and the bottom
 *      controls / NDCI card.
 *   2. Reveal: when a station is selected the map pans so its pin and chip
 *      are fully visible beside the right panel (or above the bottom sheet).
 *   3. Pin labels: each station chip goes right of its dot, else left, else
 *      below, else above -- the first side that sits inside the free area
 *      and overlaps no panel, no other pin and no other chip.
 *
 * Data source: raster `bounds` of GET /raster-scan and measured panel sizes;
 * the arithmetic of 1 and 2 is in src/utils/mapViewport.js. Reads no API.
 */
import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'
import { fitPadding, revealShift } from '../utils/mapViewport.js'

const SETTLE_MS = 2400
const CLOSE_ZOOM = 13 // a selected pin is shown close up
const reduced = () => {
  try { return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true } catch { return false }
}
const stageOf = (map) => map.getContainer().closest('.gl-stage')
const visible = (el) => el && el.offsetWidth > 0 && el.offsetHeight > 0
const rel = (el, mr) => {
  const r = el.getBoundingClientRect()
  return { left: r.left - mr.left, right: r.right - mr.left, top: r.top - mr.top, bottom: r.bottom - mr.top }
}
const hit = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
const panels = (stage, mr) => ['.gl-top', '.gl-left', '.gl-right', '.gl-controls', '.gl-ndci', '.gl-show-panel']
  .map((s) => stage?.querySelector(s)).filter(visible).map((el) => rel(el, mr))

function measureFit(map) {
  const mr = map.getContainer().getBoundingClientRect()
  const stage = stageOf(map)
  const left = stage?.querySelector('.gl-left')
  const top = stage?.querySelector('.gl-top')
  const lowest = ['.gl-controls', '.gl-ndci'].map((s) => stage?.querySelector(s)).filter(visible)
    .map((el) => mr.bottom - el.getBoundingClientRect().top)
  const leftDocked = visible(left) && left.getBoundingClientRect().width < mr.width * 0.6
  return fitPadding({
    mapW: mr.width,
    mapH: mr.height,
    railW: leftDocked ? left.offsetWidth - 8 : 0, // fitPadding adds 24 -> card width + 16
    topEdge: top ? rel(top, mr).bottom + 16 : 84,
    dockH: lowest.length ? Math.max(...lowest) + 12 : 0,
    rightInset: 140, // the east-most chip

  })
}

function FitToRaster({ bounds, enabled, refit }) {
  const map = useMap()
  const key = JSON.stringify(bounds ?? null)
  const first = useRef(true)
  useEffect(() => {
    if (!bounds || !enabled) return undefined
    const initial = first.current
    first.current = false
    const id = setTimeout(() => {
      map.invalidateSize()
      const pad = measureFit(map)
      map.fitBounds(bounds, { ...pad, animate: !initial && !reduced() })
    }, 0)
    return () => clearTimeout(id)
  }, [map, key, enabled, refit]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

function RevealSelected({ selected }) {
  const map = useMap()
  const selectedKey = selected ? selected.key : null
  useEffect(() => {
    if (!selected) return undefined
    let alive = true
    const reveal = () => {
      if (!alive) return
      const mr = map.getContainer().getBoundingClientRect()
      const stage = stageOf(map)
      const p = map.latLngToContainerPoint([selected.lat, selected.lng])
      const pin = stage?.querySelector('.gl-pin[data-selected="true"] .gl-pin-chip')
      const chipW = pin ? pin.offsetWidth + 7 : 0
      const topbar = stage?.querySelector('.gl-top')
      const safe = { left: 24, right: mr.width - 16, top: topbar ? rel(topbar, mr).bottom + 12 : 96, bottom: mr.height - 24 }
      const right = stage?.querySelector('.gl-right')
      if (visible(right)) {
        const r = rel(right, mr)
        if (r.right - r.left >= mr.width * 0.9) safe.bottom = r.top - 12
        else safe.right = r.left - 12
      }
      const ctl = ['.gl-controls', '.gl-ndci'].map((s) => stage?.querySelector(s)).filter(visible).map((el) => rel(el, mr))
      ctl.forEach((c) => { if (p.x + 9 > c.left && p.x - 9 < c.right) safe.bottom = Math.min(safe.bottom, c.top - 8) })
      const { shiftX, shiftY } = revealShift({ x: p.x, y: p.y, labelW: chipW, safe })
      if (Math.abs(shiftX) >= 1 || Math.abs(shiftY) >= 1) map.panBy([-Math.round(shiftX), -Math.round(shiftY)], { animate: !reduced(), duration: 0.5 })
    }
    // Zoom in on the pin (never zoom out), then keep it clear of the panels.
    const zoomTo = Math.max(map.getZoom(), CLOSE_ZOOM)
    if (reduced()) map.setView([selected.lat, selected.lng], zoomTo, { animate: false })
    else map.flyTo([selected.lat, selected.lng], zoomTo, { duration: 0.9 })
    const first = setTimeout(reveal, reduced() ? 80 : 1100)
    map.on('moveend', reveal)
    const stop = setTimeout(() => map.off('moveend', reveal), SETTLE_MS)
    return () => { alive = false; clearTimeout(first); clearTimeout(stop); map.off('moveend', reveal) }
  }, [map, selectedKey]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

function PinLabels() {
  const map = useMap()
  useEffect(() => {
    const container = map.getContainer()
    const apply = () => {
      const mr = container.getBoundingClientRect()
      const stage = stageOf(map)
      const obstacles = panels(stage, mr)
      const free = { left: 8, right: mr.width - 8, top: 8, bottom: mr.height - 8 }
      const pins = [...container.querySelectorAll('.gl-pin')].map((el) => {
        const d = el.querySelector('.gl-pin-dot').getBoundingClientRect()
        const c = el.querySelector('.gl-pin-chip')
        const r = d.width / 2
        return { el, cx: d.left + r - mr.left, cy: d.top + r - mr.top, r, w: c.offsetWidth, h: c.offsetHeight, sel: el.dataset.selected === 'true' }
      }).filter((p) => p.cx > -50 && p.cx < mr.width + 50 && p.cy > -50 && p.cy < mr.height + 50)
      pins.sort((a, b) => Number(b.sel) - Number(a.sel))
      const dots = pins.map((p) => ({ left: p.cx - p.r - 3, right: p.cx + p.r + 3, top: p.cy - p.r - 3, bottom: p.cy + p.r + 3, owner: p }))
      const placed = []
      pins.forEach((p) => {
        const g = 7
        const boxes = {
          right: { left: p.cx + p.r + g, top: p.cy - p.h / 2 },
          left: { left: p.cx - p.r - g - p.w, top: p.cy - p.h / 2 },
          below: { left: p.cx - p.w / 2, top: p.cy + p.r + g },
          above: { left: p.cx - p.w / 2, top: p.cy - p.r - g - p.h },
        }
        const score = (b) => {
          const box = { left: b.left, right: b.left + p.w, top: b.top, bottom: b.top + p.h }
          let bad = 0
          if (box.left < free.left || box.right > free.right || box.top < free.top || box.bottom > free.bottom) bad += 3
          obstacles.forEach((o) => { if (hit(box, o)) bad += 2 })
          dots.forEach((d) => { if (d.owner !== p && hit(box, d)) bad += 2 })
          placed.forEach((o) => { if (hit(box, o)) bad += 2 })
          return { bad, box }
        }
        let best = null
        for (const side of ['right', 'left', 'below', 'above']) {
          const s = score(boxes[side])
          if (!best || s.bad < best.bad) best = { side, ...s }
          if (s.bad === 0) break
        }
        placed.push(best.box)
        if (p.el.dataset.side !== best.side) p.el.dataset.side = best.side
      })
    }
    let timer = 0
    const schedule = () => { clearTimeout(timer); timer = setTimeout(apply, 16) }
    schedule()
    map.on('moveend zoomend resize', schedule)
    const observer = new MutationObserver(schedule)
    observer.observe(map.getPane('markerPane'), { childList: true, subtree: true })
    const stage = stageOf(map)
    if (stage) observer.observe(stage, { childList: true })
    window.addEventListener('resize', schedule)
    return () => {
      clearTimeout(timer)
      map.off('moveend zoomend resize', schedule)
      observer.disconnect()
      window.removeEventListener('resize', schedule)
    }
  }, [map])
  return null
}

export default function MapViewport({ bounds, fitEnabled = true, refit = 0, selected = null }) {
  return (
    <>
      <FitToRaster bounds={bounds} enabled={fitEnabled} refit={refit} />
      <RevealSelected selected={selected} />
      <PinLabels />
    </>
  )
}
