/**
 * NavBar: the site header -- product name and one-line subtitle, the
 * language toggle, and the main navigation of the five pages (dashboard
 * spec §3).
 *
 * Data source: i18n `app.*` and `nav.*`; the router's location (NavLink
 * marks the current page with `aria-current="page"`; `/sites/:id` keeps
 * "Monitoring sites" current).
 *
 * Layout: two tiers -- masthead (brand, subtitle, TH|EN) above a tab row of
 * the five routes. Below 640 px the tab row collapses behind a Menu button
 * (`aria-expanded`/`aria-controls`); choosing a page or pressing Esc closes
 * it (Esc returns focus to the button).
 *
 * Limitations: the nav lists pages only; per-page actions (cite, export)
 * live on the pages that own the data.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import Icon from '../Icon.jsx'
import LangToggle from './LangToggle.jsx'
import { useLang } from '../../i18n/useLang.js'

const ROUTES = Object.freeze([
  Object.freeze({ to: '/', key: 'overview', end: true }),
  Object.freeze({ to: '/map', key: 'map', end: false }),
  Object.freeze({ to: '/sites', key: 'sites', end: false }),
  Object.freeze({ to: '/methods', key: 'methods', end: false }),
  Object.freeze({ to: '/data', key: 'data', end: false }),
])

/** A 3 x 3 pixel grid with one measured cell: what the product reads. */
function BrandMark() {
  return (
    <svg className="pw-brand-mark" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="1.5" y="1.5" width="21" height="21" rx="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8.5 1.5v21M15.5 1.5v21M1.5 8.5h21M1.5 15.5h21" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.32" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="0.75" fill="currentColor" />
    </svg>
  )
}

export default function NavBar() {
  const { t } = useLang()
  const [open, setOpen] = useState(false)
  const menuId = useId()
  const buttonRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <header className="pw-header">
      <div className="pw-container pw-header-top">
        <div className="pw-brand">
          <Link to="/" className="pw-brand-link" onClick={() => setOpen(false)}>
            <BrandMark />
            <span className="pw-brand-name">{t('app.name')}</span>
          </Link>
          <p className="pw-brand-tagline">{t('app.tagline')}</p>
        </div>
        <div className="pw-header-tools">
          <LangToggle />
          <button
            type="button"
            ref={buttonRef}
            className="pw-menu-btn"
            aria-expanded={open}
            aria-controls={menuId}
            onClick={() => setOpen((v) => !v)}
          >
            <Icon name={open ? 'close' : 'menu'} size={18} strokeWidth={2} />
            <span>{t('nav.menu')}</span>
          </button>
        </div>
      </div>
      <nav className="pw-nav" id={menuId} aria-label={t('nav.main_label')} data-open={open ? 'true' : 'false'}>
        <ul className="pw-container pw-nav-list">
          {ROUTES.map((route) => (
            <li key={route.to}>
              <NavLink to={route.to} end={route.end} className="pw-nav-link" onClick={() => setOpen(false)}>
                {t(`nav.${route.key}`)}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
