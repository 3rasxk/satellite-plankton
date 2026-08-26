import { NavLink } from 'react-router-dom'
import { useApi } from '../hooks/useApi.js'
import { getMeta } from '../api/client.js'

const NAV_ITEMS = [
  { to: '/', label: 'ภาพรวม/แผนที่', icon: '🗺️', end: true },
  { to: '/ndci', label: 'Sentinel-2 NDCI', icon: '📡' },
  { to: '/anomaly', label: 'ความผิดปกติตามฤดูกาล', icon: '📈' },
  { to: '/aquaculture', label: 'พื้นที่เพาะเลี้ยงสัตว์น้ำ', icon: '🐟' },
  { to: '/reports', label: 'รายงานและการส่งออก', icon: '📄' },
]

/**
 * Sidebar nav shell (HAB Sentinel design spec, docs/superpowers/specs/
 * 2026-08-26-hab-sentinel-dashboard-design.md). The connectivity pill is a
 * real signal, not decoration: it fires GET / (backend/src/main.py's meta
 * route) once on mount and reflects whether that call actually succeeded —
 * never a hardcoded "connected" claim (CLAUDE.md: never fabricate).
 */
export default function Sidebar() {
  const { data, error } = useApi(getMeta, [])
  const connected = !!data && !error

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-logo" aria-hidden="true">🛰️</span>
        <div>
          <div className="sidebar-title">HAB Sentinel</div>
          <div className="sidebar-subtitle">อ่าวไทยตอนบน</div>
        </div>
      </div>

      <div className={`sidebar-status-pill${connected ? '' : ' offline'}`}>
        <span className="dot" />
        {connected ? 'ระบบทำงานปกติ' : 'เชื่อมต่อ API ไม่ได้'}
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`}
          >
            <span className="sidebar-nav-icon" aria-hidden="true">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className={`sidebar-pill outline${connected ? '' : ' offline'}`}>
          <span className="dot" />
          GEE API {connected ? 'Connected' : 'Unreachable'}
        </div>
        <button type="button" className="sidebar-settings-btn">
          <span aria-hidden="true">⚙️</span> ตั้งค่าระบบ
        </button>
      </div>
    </aside>
  )
}
