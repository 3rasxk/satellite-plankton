/**
 * The system states of the design reference, one component each, used by
 * the real pages (Summary: loading / unreachable / no signal) and shown
 * side by side on /states. Each non-reading says what occurred, the likely
 * cause and the next step -- and never borrows a risk colour.
 */
export function Skeleton() {
  return (
    <div className="gl-state-box" aria-busy="true" role="status">
      <div className="gl-skel" style={{ width: '72%' }} /><div className="gl-skel" style={{ width: '46%' }} /><div className="gl-skel" style={{ width: '60%' }} />
    </div>
  )
}

export function Unreachable({ onRetry }) {
  return (
    <div className="gl-state-box" style={{ alignItems: 'flex-start', gap: 10 }} role="alert">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#1D1D1F" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4M12 17h.01" /></svg>
      <strong style={{ fontSize: 16 }}>Couldn’t reach the data service.</strong>
      <button type="button" className="gl-btn gl-btn--sm" onClick={onRetry}>Retry</button>
    </div>
  )
}

export function NoReading() {
  return (
    <div className="gl-state-box" style={{ background: 'repeating-linear-gradient(135deg,#F2F2F4 0 8px,#E5E5EA 8px 16px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1D1D1F" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" /></svg>
        <strong style={{ fontSize: 16 }}>No reading</strong>
      </div>
      <span style={{ fontSize: 13 }}>Cloud prevented the satellite pass. This is not “all clear”.</span>
    </div>
  )
}

export function NoSignal({ text = 'No monitored station currently shows a bloom-like reading.' }) {
  return (
    <div className="gl-state-box">
      <span style={{ fontSize: 22, fontWeight: 600 }}>No recent signal.</span>
      <span style={{ fontSize: 13, color: '#3A3A3C' }}>{text}</span>
    </div>
  )
}

export function NotChecked() {
  return (
    <div className="gl-state-box">
      <span style={{ fontSize: 22, fontWeight: 600 }}>Not checked yet</span>
      <span style={{ fontSize: 13, color: '#3A3A3C' }}>The first scheduled check has not finished. This is loading, not a finding.</span>
    </div>
  )
}

export function OutOfDate({ age = '2 days old', label = 'Watch' }) {
  return (
    <div className="gl-state-box" style={{ alignItems: 'flex-start', gap: 8 }}>
      <span className="gl-chip" style={{ padding: '3px 10px' }}>Out of date · {age}</span>
      <span style={{ fontSize: 22, fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: 13, color: '#3A3A3C' }}>The last update failed. Showing the most recent good reading.</span>
    </div>
  )
}
