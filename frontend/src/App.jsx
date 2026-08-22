import { NavLink, Outlet } from 'react-router-dom'
import Disclaimer from './components/Disclaimer.jsx'
import { DISCLAIMER_TEXT } from './constants.js'

/**
 * Layout shell shared by every route: header/nav + routed page content +
 * the persistent disclaimer banner. The banner lives here, outside any
 * page's own loading/error branches, so it is never dropped while a fetch
 * is pending or has failed (CLAUDE.md truth boundary, mandatory in every
 * output).
 */
export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">Algal Bloom Watch</span>
          <span className="brand-sub">Upper Gulf of Thailand</span>
        </div>
        <nav className="app-nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Risk map
          </NavLink>
          <NavLink to="/summary" className={({ isActive }) => (isActive ? 'active' : '')}>
            Summary
          </NavLink>
          <NavLink to="/validation" className={({ isActive }) => (isActive ? 'active' : '')}>
            Validation
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
      <Disclaimer text={DISCLAIMER_TEXT} />
    </div>
  )
}
