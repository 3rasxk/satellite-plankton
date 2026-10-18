/**
 * Left glass card (328px), hidden while a station is selected: a status
 * eyebrow with the newest scene date, the headline and one-line list of
 * affected stations, count chips per class, the station list sorted by
 * severity (selected row tinted rgba(0,113,227,.12), chevron on the right),
 * and -- outside NDCI mode -- the "Risk classes" legend with a "Reading
 * guide" link.
 *
 * Data source: `stations` (./model.js over GET /risk-map), `sceneDate`
 * from GET /raster-scan. With no backend risk class the headline reads
 * "N of M stations have an index reading" and the legend explains
 * "Not evaluated" instead of inventing classes.
 */
import { Chevron, Dot } from './ui.jsx'
import { LV, RISK_KEYS, TEST_MEANING, headlineOf, testBased } from './model.js'

export default function LeftCard({ stations, state, selectedId, onSelect, onOpenGuide, showLegend, sceneDate, onRetry, onClose }) {
  const ready = Array.isArray(stations) && stations.length > 0
  const head = ready ? headlineOf(stations) : null
  // Only the three classes that call for a look; always shown, even at 0.
  const counts = ready ? ['warning', 'watch', 'elevated'].map((key) => ({ key, label: LV[key].label, n: stations.filter((s) => s.cls === key).length })) : []
  const classified = ready && stations.some((s) => s.rated || s.testClass)
  const test = ready && testBased(stations)
  return (
    <aside className="gl-left gl-glass" aria-label="Monitoring stations">
      <div className="gl-left-head">
        <div className="gl-eyebrow">Status{sceneDate ? ` · ${sceneDate}` : ''}</div>
        {state === 'loading' && <h2>Loading stations…</h2>}
        {state === 'error' && (
          <>
            <h2>Couldn’t reach the data service.</h2>
            <p style={{ marginTop: 8 }}><button type="button" className="gl-btn gl-btn--sm" onClick={onRetry}>Retry</button></p>
          </>
        )}
        {state === 'empty' && <h2>No stations to show.</h2>}
        {head && (
          <>
            <h2>{head.headline}</h2>
            <div className="gl-chips">
              {counts.map((c) => (
                <span className="gl-chip" key={c.key}><Dot cls={c.key} size={8} /><span className="gl-mono">{c.n}</span>{c.label}</span>
              ))}
            </div>
          </>
        )}
        {onClose && <button type="button" className="gl-link" onClick={onClose} style={{ marginTop: 8 }}>Hide panel</button>}
      </div>
      <div className="gl-list">
        {ready && stations.map((s) => (
          <button key={s.id} type="button" className="gl-row" aria-pressed={s.id === selectedId} onClick={() => onSelect(s.id)}>
            <Dot cls={s.cls} size={12} />
            <span><b>{s.short}</b><small>{s.province}{s.stale ? ' · out of date' : ''}</small></span>
            <span className="gl-lvl">{LV[s.cls].label}</span>
            <Chevron />
          </button>
        ))}
      </div>
      {showLegend && (
        <div className="gl-legend">
          <div className="gl-legend-head">
            <span className="gl-eyebrow">Risk classes</span>
            <button type="button" className="gl-link" onClick={onOpenGuide}>Reading guide</button>
          </div>
          {classified
            ? RISK_KEYS.map((k) => (
              <div className="gl-legend-row" key={k}><Dot cls={k} /><strong>{LV[k].label}</strong><span>{(test && TEST_MEANING[k]) || LV[k].meaning}</span></div>
            ))
            : (
              <>
                <div className="gl-legend-row"><Dot cls="unrated" /><strong>Not evaluated</strong><span>Reading present; no validated baseline, so no risk class.</span></div>
                <div className="gl-legend-row"><Dot cls="none" /><strong>No data</strong><span>No usable observation (cloud, no scene).</span></div>
              </>
            )}
        </div>
      )}
    </aside>
  )
}
