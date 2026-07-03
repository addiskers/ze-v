import { useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Profile() {
  const { user, isAdmin } = useAuth()
  const [cur, setCur] = useState('')
  const [nw, setNw] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function change() {
    setBusy(true); setErr(''); setMsg('')
    try {
      await api.post('/me/password', { current: cur, new: nw })
      setMsg('Password updated.'); setCur(''); setNw('')
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="stack">
      <PageHeader title="My Profile" sub="Your account details" />

      <div className="card" style={{ maxWidth: 460 }}>
        <div className="stack" style={{ gap: 14 }}>
          <div><label>Name</label><div>{user?.name || '—'}</div></div>
          <div><label>Username</label><div>{user?.username}</div></div>
          <div><label>Role</label><span className={`pill ${isAdmin ? 'green' : 'blue'}`}>{isAdmin ? 'EO Admin' : 'EO Agent'}</span></div>
        </div>
      </div>

      <div className="card" style={{ maxWidth: 460 }}>
        <div className="panel-head"><h3>Change Password</h3></div>
        {msg && <div style={{ color: 'var(--green)', fontSize: '0.82rem', marginBottom: 10 }}>{msg}</div>}
        {err && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{err}</div>}
        <div className="row"><label>Current Password</label><input type="password" value={cur} onChange={(e) => setCur(e.target.value)} /></div>
        <div className="row"><label>New Password</label><input type="password" value={nw} onChange={(e) => setNw(e.target.value)} placeholder="min 6 characters" /></div>
        <button className="btn" style={{ marginTop: 6 }} disabled={busy || !cur || !nw} onClick={change}>{busy ? 'Updating…' : 'Update Password'}</button>
      </div>
    </div>
  )
}
