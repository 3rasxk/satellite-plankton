import { useRef, useState, useCallback } from 'react'
import { RISK_LABEL_TH, RISK_MEANING, RISK_COLOR_VAR } from '../constants.js'

const LEVELS = ['normal', 'elevated', 'watch', 'warning']

/**
 * Fixed legend for the risk map. Shows what each colour means, not just
 * the swatch (docs/FRONTEND_PLAN.md §5: "showing the three [now four]
 * levels *with what they mean*"). The no-data hatch pattern is listed
 * separately and explicitly labelled as "not a risk reading" so it can
 * never be misread as the lowest risk tier. Draggable (pointer events)
 * so it never permanently blocks the map beneath it; when `mode ===
 * 'ndci'` it swaps to a gradient bar — this is chrome for the illustrative
 * overlay (NdciRasterOverlay.jsx), not a claim about a real calibrated
 * index scale.
 */
export default function RiskLegend({ mode = 'risk' }) {
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

  return (
    <div
      className="risk-legend glass"
      style={{ left: pos.x, bottom: pos.y }}
      onPointerDown={onPointerDown}
    >
      {mode === 'ndci' ? (
        <>
          <h3>NDCI Index</h3>
          <div className="ndci-gradient-bar" />
          <div className="ndci-gradient-labels">
            <span>−0.10</span>
            <span>0.10</span>
            <span>&gt;0.35</span>
          </div>
        </>
      ) : (
        <>
          <h3>ระดับความเสี่ยง</h3>
          {LEVELS.map((level) => (
            <div className="legend-row" key={level}>
              <span className="legend-swatch" style={{ background: `var(${RISK_COLOR_VAR[level]})` }} />
              <span>
                <span className="legend-label">{RISK_LABEL_TH[level]}</span>
                <span className="legend-meaning">{RISK_MEANING[level]}</span>
              </span>
            </div>
          ))}
        </>
      )}
      <div className="legend-row">
        <span className="legend-swatch no-data" />
        <span>
          <span className="legend-label">ไม่มีค่าอ่าน</span>
          <span className="legend-meaning">ไม่ใช่ระดับเสี่ยง — เมฆบัง ไม่มีข้อมูลฐาน หรือยังไม่ได้ตรวจสอบ</span>
        </span>
      </div>
    </div>
  )
}
