import { Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'

/**
 * Layout shell shared by every route: sidebar nav + routed page content.
 */
export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-body">
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
