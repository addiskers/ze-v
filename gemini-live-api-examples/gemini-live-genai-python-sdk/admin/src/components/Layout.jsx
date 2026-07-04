import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth.jsx'
import {
  IconDashboard, IconPlus, IconCampaigns, IconClock, IconUsers, IconSettings, IconUser, IconLogout,
} from './icons.jsx'

// Superadmin nav — Call Logs lives on the Dashboard, Contacts live in Create Campaign.
// Scheduler is its own item so callbacks are findable + manageable.
const FULL_NAV = [
  { to: '/', label: 'Dashboard', icon: IconDashboard, end: true },
  { to: '/create-campaign', label: 'Create Campaign', icon: IconPlus },
  { to: '/campaigns', label: 'My Campaigns', icon: IconCampaigns },
  { to: '/scheduler', label: 'Scheduler', icon: IconClock },
  { to: '/users', label: 'Users', icon: IconUsers, adminOnly: true },
  { to: '/settings', label: 'Settings', icon: IconSettings, adminOnly: true },
]

const AGENT_NAV = [
  { to: '/', label: 'Dashboard', icon: IconDashboard, end: true },
  { to: '/create-campaign', label: 'Create Campaign', icon: IconPlus },
  { to: '/campaigns', label: 'My Campaigns', icon: IconCampaigns },
  { to: '/scheduler', label: 'Scheduler', icon: IconClock },
  { to: '/profile', label: 'My Profile', icon: IconUser },
]

function initials(name, username) {
  const s = (name || username || 'EO').trim()
  const parts = s.split(/\s+/)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || 'EO'
}

export default function Layout() {
  const { user, isAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const nav = isAdmin ? FULL_NAV : AGENT_NAV

  function doLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">EO</div>
          <div>
            <div className="name">EO AI Calling</div>
            <div className="sub">Admin Platform</div>
          </div>
        </div>
        <nav className="nav">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              <n.icon />
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="btn ghost" style={{ width: '100%', display: 'flex', gap: 8, justifyContent: 'center' }} onClick={doLogout}>
            <IconLogout /> Sign out
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div id="topbar-title" />
          <div className="userchip">
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '0.82rem', fontWeight: 600 }}>{user?.name || user?.username}</div>
              <div className="page-sub">{isAdmin ? 'Superadmin' : 'Admin'}</div>
            </div>
            <div className="avatar">{initials(user?.name, user?.username)}</div>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
