import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './auth.jsx'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import CallLogsPage from './pages/CallLogsPage.jsx'
import Scheduler from './pages/Scheduler.jsx'
import Contacts from './pages/Contacts.jsx'
import CreateCampaign from './pages/CreateCampaign.jsx'
import MyCampaigns from './pages/MyCampaigns.jsx'
import CampaignDetails from './pages/CampaignDetails.jsx'
import Users from './pages/Users.jsx'
import Settings from './pages/Settings.jsx'
import Profile from './pages/Profile.jsx'

function Protected({ children, adminOnly }) {
  const { user, ready, isAdmin } = useAuth()
  const loc = useLocation()
  if (!ready) return <div className="center">Loading…</div>
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/create-campaign" element={<CreateCampaign />} />
        <Route path="/campaigns" element={<MyCampaigns />} />
        <Route path="/campaigns/:id" element={<CampaignDetails />} />
        <Route path="/call-logs" element={<CallLogsPage />} />
        <Route path="/scheduler" element={<Scheduler />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/users" element={<Protected adminOnly><Users /></Protected>} />
        <Route path="/settings" element={<Protected adminOnly><Settings /></Protected>} />
        <Route path="/profile" element={<Profile />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
