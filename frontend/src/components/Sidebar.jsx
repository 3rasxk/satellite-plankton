import { NavLink } from 'react-router-dom'
import Icon from './Icon.jsx'

const NAV_ITEMS = [
  { to: '/', label: 'ภาพรวม/แผนที่', icon: 'map', end: true },
  { to: '/ndci', label: 'Sentinel-2 NDCI', icon: 'satellite' },
  { to: '/anomaly', label: 'ความผิดปกติตามฤดูกาล', icon: 'trend' },
  { to: '/aquaculture', label: 'พื้นที่เพาะเลี้ยงสัตว์น้ำ', icon: 'fish' },
  { to: '/reports', label: 'รายงานและการส่งออก', icon: 'file' },
]

/** Sidebar nav shell (HAB Sentinel design spec). */
export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-logo" aria-hidden="true"><Icon name="satellite" size={17} /></span>
        <div className="sidebar-brand-copy">
          <div className="sidebar-title">HAB Sentinel</div>
          <div className="sidebar-subtitle">อ่าวไทยตอนบน</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`}
            title={item.label}
          >
            <span className="sidebar-nav-icon" aria-hidden="true"><Icon name={item.icon} /></span>
            <span className="sidebar-nav-label">{item.label}</span>
          </NavLink>
        ))}
      </nav>

    </aside>
  )
}
