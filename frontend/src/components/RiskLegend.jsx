import { useRef, useState, useCallback, useEffect } from 'react'
import { clampOverlayPosition, getDraggedOverlayPosition } from '../utils/mapOverlay.js'
import { getOverlayLegendLevels, getSafeWatchColor } from '../utils/watchOverlay.js'

/**
 * Draggable explanatory legend for the two non-basemap map modes. The
 * illustrative NDCI gradient is distinct from the cached orange watch tile.
 */
export default function RiskLegend({ mode = 'true_color', watchOverlay = null }) {
  const [pos, setPos] = useState({ x: 16, y: 16 })
  const legendRef = useRef(null)
  const dragRef = useRef(null)
  const levels = getOverlayLegendLevels(mode, watchOverlay)
  const resolutions = watchOverlay?.analysis_metadata?.resolutions

  const clampToMap = useCallback((position) => {
    const element = legendRef.current
    const container = element?.parentElement
    if (!element || !container) return position

    const containerRect = container.getBoundingClientRect()
    const legendRect = element.getBoundingClientRect()
    return clampOverlayPosition(
      position,
      { width: containerRect.width, height: containerRect.height },
      { width: legendRect.width, height: legendRect.height },
    )
  }, [])

  useEffect(() => {
    const keepInsideMap = () => setPos((current) => clampToMap(current))
    keepInsideMap()
    window.addEventListener('resize', keepInsideMap)
    return () => window.removeEventListener('resize', keepInsideMap)
  }, [clampToMap, mode, watchOverlay])

  useEffect(() => () => {
    const drag = dragRef.current
    const element = legendRef.current
    if (drag && element?.hasPointerCapture(drag.pointerId)) {
      element.releasePointerCapture(drag.pointerId)
    }
    dragRef.current = null
  }, [])

  const onPointerDown = useCallback((event) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    event.currentTarget.focus({ preventScroll: true })
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      pointerId: event.pointerId,
      start: { x: event.clientX, y: event.clientY },
      origin: pos,
    }
    event.preventDefault()
  }, [pos])

  const onPointerMove = useCallback((event) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const next = getDraggedOverlayPosition(
      drag.origin,
      drag.start,
      { x: event.clientX, y: event.clientY },
    )
    setPos(clampToMap(next))
  }, [clampToMap])

  const finishDrag = useCallback((event) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    dragRef.current = null
  }, [])

  const onKeyDown = useCallback((event) => {
    const deltas = {
      ArrowLeft: { x: -8, y: 0 },
      ArrowRight: { x: 8, y: 0 },
      ArrowUp: { x: 0, y: 8 },
      ArrowDown: { x: 0, y: -8 },
    }
    const delta = deltas[event.key]
    if (!delta) return
    event.preventDefault()
    setPos((current) => clampToMap({ x: current.x + delta.x, y: current.y + delta.y }))
  }, [clampToMap])

  if (mode !== 'ndci' && levels.length !== 3) return null

  return (
    <div
      ref={legendRef}
      className="risk-legend glass"
      style={{ left: pos.x, bottom: pos.y }}
      role="region"
      tabIndex={0}
      aria-label="คำอธิบายแผนที่ ใช้ปุ่มลูกศรหรือลากเพื่อย้าย"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
      onKeyDown={onKeyDown}
    >
      {mode === 'true_color' || mode === 'watch' ? (
        <>
          <h3>สัญญาณ NDCI (3 ระดับ)</h3>
          {levels.map((level) => (
            <div className="legend-row" key={level.code}>
              <span className="legend-swatch" style={{ backgroundColor: getSafeWatchColor(level.color, level.code) }} aria-hidden="true" />
              <span className="legend-label">{level.label_th}</span>
            </div>
          ))}
          <div className="legend-row">
            <span className="legend-swatch transparent-overlay" />
            <span className="legend-meaning">โปร่งใส: ต่ำกว่าเกณฑ์ เมฆบัง ไม่ใช่น้ำทะเลเชื่อมต่ออ่าว หรือข้อมูลฐานไม่พอ</span>
          </div>
          <span className="legend-meaning">กริดผลลัพธ์ {resolutions?.output_grid_m ?? '—'} m; NDCI {resolutions?.ndci_m ?? '—'} m; เทรนด์ {resolutions?.trend_m ?? '—'} m; SST ประมาณ {Number.isFinite(resolutions?.sst_m) ? (resolutions.sst_m / 1000).toFixed(1) : '—'} km</span>
        </>
      ) : mode === 'ndci' ? (
        <>
          <h3>NDCI Index</h3>
          <div className="ndci-gradient-bar" />
          <div className="ndci-gradient-labels">
            <span>−0.10</span>
            <span>0.10</span>
            <span>&gt;0.35</span>
          </div>
        </>
      ) : null}
    </div>
  )
}
