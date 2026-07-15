import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth.jsx'
import {
  IconDashboard, IconPlus, IconCampaigns, IconClock, IconUsers, IconSettings, IconUser, IconLogout, IconMenu,
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
  const s = (name || username || 'ZN').trim()
  const parts = s.split(/\s+/)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || 'ZN'
}

export default function Layout() {
  const { user, isAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const nav = isAdmin ? FULL_NAV : AGENT_NAV

  // Mobile off-canvas drawer (<900px). Desktop (≥900px) ignores this state entirely.
  const [menuOpen, setMenuOpen] = useState(false)

  // Close the drawer on any route navigation.
  useEffect(() => { setMenuOpen(false) }, [location.pathname])

  // While open: lock body scroll and close on Escape.
  useEffect(() => {
    if (!menuOpen) return
    document.body.classList.add('no-scroll')
    const onKey = (e) => { if (e.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.classList.remove('no-scroll')
      window.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  // If the viewport grows back to desktop width, reset the drawer state.
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 900px)')
    const onChange = (e) => { if (e.matches) setMenuOpen(false) }
    if (mq.addEventListener) mq.addEventListener('change', onChange)
    else mq.addListener(onChange)
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', onChange)
      else mq.removeListener(onChange)
    }
  }, [])

  function doLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <aside className={menuOpen ? 'sidebar open' : 'sidebar'}>
        <div className="brand">
          <div className="logo">Z</div>
          <div>
            <div className="name">Zenon AI Calling</div>
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

      {menuOpen && <div className="sidebar-backdrop" onClick={() => setMenuOpen(false)} />}

      <div className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="nav-toggle"
              aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((o) => !o)}
            >
              <IconMenu />
            </button>
            <div id="topbar-title" />
          </div>
          <div className="userchip">
            <div className="userchip-meta" style={{ textAlign: 'right' }}>
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
