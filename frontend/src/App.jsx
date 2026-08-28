import { Outlet } from 'react-router-dom'

/**
 * Layout shell — map-only, no sidebar.
 */
export default function App() {
  return (
    <div className="app-shell no-sidebar">
      <div className="app-body">
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
