import { useRef, useState, useCallback } from 'react'

/**
 * Draggable explanatory legend for the two non-basemap map modes. The
 * illustrative NDCI gradient is distinct from the cached orange watch tile.
 */
export default function RiskLegend({ mode = 'true_color', watchOverlay = null }) {
  const [pos, setPos] = useState({ x: 16, y: 16 })
  const dragRef = useRef(null)

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

  if (mode === 'true_color') return null

  return (
    <div
      className="risk-legend glass"
      style={{ left: pos.x, bottom: pos.y }}
      onPointerDown={onPointerDown}
    >
      {mode === 'watch' ? (
        <>
          <h3>NDCI watch signal</h3>
          <div className="legend-row">
            <span className="legend-swatch watch-overlay" />
            <span><span className="legend-label">เฝ้าระวัง: z ≥ {watchOverlay?.threshold_z ?? 1.5}</span><span className="legend-meaning">สีส้มคือสัญญาณ NDCI สูงกว่าฐานฤดูกาล</span></span>
          </div>
          <div className="legend-row">
            <span className="legend-swatch transparent-overlay" />
            <span className="legend-meaning">โปร่งใส: ต่ำกว่าเกณฑ์ เมฆบัง ไม่ใช่น้ำทะเลเชื่อมต่ออ่าว หรือข้อมูลฐานไม่พอ</span>
          </div>
          <span className="legend-meaning">กริด {watchOverlay?.output_grid_m ?? 10} m; ความละเอียดต้นทาง NDCI {watchOverlay?.effective_resolution_m ?? 20} m</span>
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
