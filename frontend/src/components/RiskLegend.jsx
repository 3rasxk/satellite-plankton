import { useRef, useState, useCallback } from 'react'
import { getOverlayLegendLevels } from '../utils/watchOverlay.js'

/**
 * Draggable explanatory legend for the two non-basemap map modes. The
 * illustrative NDCI gradient is distinct from the cached orange watch tile.
 */
export default function RiskLegend({ mode = 'true_color', watchOverlay = null }) {
  const [pos, setPos] = useState({ x: 16, y: 16 })
  const dragRef = useRef(null)
  const levels = getOverlayLegendLevels(mode, watchOverlay)
  const resolutions = watchOverlay?.analysis_metadata?.resolutions

  const onPointerDown = useCallback((e) => {
    const start = { x: e.clientX, y: e.clientY, origin: pos }
    dragRef.current = start
    const onMove = (ev) => {
      const dx = ev.clientX - start.x
      const dy = ev.clientY - start.y
      setPos({ x: start.origin.x + dx, y: start.origin.y + dy })
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos])

  if (mode !== 'ndci' && levels.length !== 3) return null

  return (
    <div
      className="risk-legend glass"
      style={{ left: pos.x, bottom: pos.y }}
      onPointerDown={onPointerDown}
    >
      {mode === 'true_color' || mode === 'watch' ? (
        <>
          <h3>สัญญาณ NDCI (3 ระดับ)</h3>
          {levels.map((level) => (
            <div className="legend-row" key={level.code}>
              <span className="legend-swatch" style={{ background: level.color }} />
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
