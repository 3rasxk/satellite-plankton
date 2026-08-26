import { Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import Disclaimer from './components/Disclaimer.jsx'
import { DISCLAIMER_TEXT } from './constants.js'

/**
 * Layout shell shared by every route: sidebar nav + routed page content +
 * the persistent disclaimer banner. The banner lives here, outside any
 * page's own loading/error branches, so it is never dropped while a fetch
 * is pending or has failed (CLAUDE.md truth boundary, mandatory in every
 * output).
 */
export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-body">
        <main className="app-main">
          <Outlet />
        </main>
        <Disclaimer text={DISCLAIMER_TEXT} />
      </div>
    </div>
  )
}
