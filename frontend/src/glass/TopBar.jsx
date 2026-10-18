/**
 * Floating glass top bar (design reference): brand, segmented nav
 * (Map | Summary | States), the data-freshness chip with a green dot, and
 * the round help button that opens the reading guide.
 *
 * Data source: `status` from src/lib/mapListModel.js `buildUpdateChip` over
 * GET /raster-scan (poll health + newest scene), passed in by the shell.
 * Narrow screens: the tagline hides first, "Updated" collapses to its dot
 * at 720px, and below 900px the nav sits behind a Menu button.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { HelpIcon } from './ui.jsx'
import { renderMessage } from '../lib/overviewModel.js'
import { createT } from '../i18n/index.js'

const t = createT('en')

const ITEMS = [['/map', 'Map'], ['/summary', 'Summary'], ['/states', 'States']]

function current(pathname) {
  if (pathname === '/' || pathname.startsWith('/map')) return '/map'
  if (pathname.startsWith('/summary')) return '/summary'
  if (pathname.startsWith('/states')) return '/states'
  return null
}

export default function TopBar({ status, onHelp }) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const menuId = useId()
  const btn = useRef(null)
  const active = current(pathname)

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') { setOpen(false); btn.current?.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  const text = status ? renderMessage(t, status.short) : ''
  return (
    <header className="gl-top gl-glass">
      <Link to="/map" className="gl-brand" onClick={() => setOpen(false)}>
        <span className="gl-brand-name">Plankton Watch</span>
        <span className="gl-brand-tag">Upper Gulf of Thailand</span>
      </Link>
      <nav className="gl-nav" id={menuId} aria-label="Main" data-open={open ? 'true' : 'false'}>
        <div className="gl-seg">
          {ITEMS.map(([to, label]) => (
            <button
              key={to}
              type="button"
              aria-current={active === to ? 'page' : undefined}
              onClick={() => { setOpen(false); navigate(to) }}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>
      <div className="gl-top-right">
        {status && (
          <span className="gl-updated" data-tone={status.tone} title={text}>
            <span className="gl-updated-dot" aria-hidden="true" />
            <span className="gl-updated-text">{text}</span>
          </span>
        )}
        <button type="button" className="gl-round gl-menu" ref={btn} aria-expanded={open} aria-controls={menuId} aria-label="Menu" onClick={() => setOpen((v) => !v)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#1D1D1F" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
        </button>
        <button type="button" className="gl-round" aria-label="Reading guide" onClick={() => onHelp?.()}><HelpIcon /></button>
      </div>
    </header>
  )
}
