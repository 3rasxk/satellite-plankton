/**
 * Reading guide (design reference): a centred glass sheet over a blurred,
 * dimmed backdrop with three cards -- "Colour denotes risk class" (with the
 * legend), "Select a station", "Estimates, not certainties" -- and a
 * Continue pill. Shown on a first visit only (localStorage, src/lib/guide.js)
 * and reopened from the help button. Methods and Data & limits are linked
 * from here (they left the top bar).
 *
 * Honesty: while the backend returns no risk class the first card says so,
 * and the "recommended action" mentioned in card 2 appears only when the
 * API supplies one.
 */
import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { CloseIcon, Dot } from './ui.jsx'
import { LV, RISK_KEYS } from './model.js'

const FOCUSABLE = 'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'

export default function GuideSheet({ open, onClose, classified = false }) {
  const sheet = useRef(null)
  const returnTo = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    returnTo.current = document.activeElement
    sheet.current?.querySelector('.gl-btn')?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose?.() }
      if (e.key === 'Tab' && sheet.current) {
        const f = [...sheet.current.querySelectorAll(FOCUSABLE)]
        if (f.length === 0) return
        const first = f[0]
        const last = f[f.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      returnTo.current?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="gl-guide-back" onClick={onClose}>
      <div className="gl-guide" role="dialog" aria-modal="true" aria-label="Reading guide" ref={sheet} onClick={(e) => e.stopPropagation()}>
        <div className="gl-guide-head">
          <div>
            <div className="gl-eyebrow">Reading guide</div>
            <h2>How to interpret this map</h2>
          </div>
          <button type="button" className="gl-round gl-round--sm" aria-label="Close" onClick={onClose}><CloseIcon /></button>
        </div>
        <div className="gl-guide-cards">
          <div className="gl-guide-card">
            <span className="gl-guide-n gl-mono">01</span>
            <strong>Colour denotes risk class</strong>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {RISK_KEYS.map((k) => (
                <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}><Dot cls={k} />{LV[k].label}</div>
              ))}
            </div>
            <span style={{ color: '#6E6E73' }}>
              Colour is reserved for bloom risk. Hollow grey: no observation.
              {!classified && ' Levels shown are provisional statistics against each place’s own seasonal history, not validated risk classes.'}
            </span>
          </div>
          <div className="gl-guide-card">
            <span className="gl-guide-n gl-mono">02</span>
            <strong>Select a station</strong>
            <span>Click a marker or a list entry for its readings, sources and the classification. A recommended action appears only when the API supplies one.</span>
          </div>
          <div className="gl-guide-card">
            <span className="gl-guide-n gl-mono">03</span>
            <strong>Estimates, not certainties</strong>
            <span>Presence and absence are reliable; concentrations are approximate. Cloud may obscure a station for days, and small blooms may be missed.</span>
          </div>
        </div>
        <div className="gl-guide-links">
          <Link to="/methods" onClick={onClose}>Methods</Link>
          <Link to="/data" onClick={onClose}>Data &amp; limits</Link>
          <Link to="/sites" onClick={onClose}>Monitoring sites</Link>
        </div>
        <div className="gl-guide-foot">
          <span>Reopen from the help button at any time.</span>
          <button type="button" className="gl-btn gl-btn--lg" onClick={onClose}>Continue</button>
        </div>
      </div>
    </div>
  )
}
