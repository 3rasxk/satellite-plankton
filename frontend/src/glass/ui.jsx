/** Small shared pieces of the glass UI (design reference). */
import { swatchStyle } from './model.js'

/** iOS segmented control: `options` [[value, label]], white selected pill. */
export function Seg({ options, value, onChange, label, className = '' }) {
  return (
    <div className={`gl-seg ${className}`} role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  )
}

export function CloseIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#6E6E73" strokeWidth="2.6" strokeLinecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
  )
}

export function HelpIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#1D1D1F" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><path d="M12 17h.01" />
    </svg>
  )
}

export function Chevron() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#AEAEB2" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
  )
}

/** A class swatch dot: filled, or hollow white with a #AEAEB2 ring. */
export function Dot({ cls, size = 10 }) {
  return <span className="gl-sw" style={{ width: size, height: size, ...swatchStyle(cls) }} aria-hidden="true" />
}

/** The server's disclaimer, verbatim, behind a disclosure. */
export function Disclaimer({ text, endpoint }) {
  if (typeof text !== 'string' || text === '') return null
  return (
    <details>
      <summary>Server disclaimer (verbatim)</summary>
      <p className="gl-verbatim" lang="en">{text}</p>
      {endpoint && <span>from GET {endpoint}</span>}
    </details>
  )
}
