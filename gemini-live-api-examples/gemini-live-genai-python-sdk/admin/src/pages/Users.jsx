import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import { fmtDate } from '../components/CallLogs.jsx'
import Modal from '../components/Modal.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Users() {
  const { user: me } = useAuth()
  const [items, setItems] = useState([])
  const [err, setErr] = useState('')
  const [show, setShow] = useState(false)
  const [f, setF] = useState({ username: '', name: '', password: '', role: 'eo_agent' })
  const [formErr, setFormErr] = useState('')
  const [busy, setBusy] = useState(false)

  function load() {
    api.get('/users').then((d) => setItems(d.items || [])).catch((e) => setErr(e.message))
  }
  useEffect(() => { load() }, [])

  async function create() {
    setBusy(true); setFormErr('')
    try {
      await api.post('/users', f)
      setShow(false); setF({ username: '', name: '', password: '', role: 'eo_agent' }); load()
    } catch (e) { setFormErr(e.message) } finally { setBusy(false) }
  }

  async function toggleActive(u) {
    try { await api.patch(`/users/${u.id}`, { active: !u.active }); load() }
    catch (e) { alert(e.message) }
  }

  return (
    <div className="stack">
      <PageHeader
        title="Users"
        sub="Manage Zenon admin and agent accounts"
        actions={<button className="btn" onClick={() => { setFormErr(''); setShow(true) }}>+ Add User</button>}
      />

      {err && <div style={{ color: '#fca5a5' }}>{err}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="no-sort">Username</th>
              <th className="no-sort">Name</th>
              <th className="no-sort">Role</th>
              <th className="no-sort">Status</th>
              <th className="no-sort">Created</th>
              <th className="no-sort">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={6} className="empty">No users.</td></tr>
            ) : items.map((u) => (
              <tr key={u.id}>
                <td style={{ fontWeight: 600 }}>{u.username}{u.id === me?.id && <span className="muted"> (you)</span>}</td>
                <td>{u.name || <span className="muted">—</span>}</td>
                <td><span className={`pill ${u.role === 'eo_admin' ? 'green' : 'blue'}`}>{u.role === 'eo_admin' ? 'Superadmin' : 'Admin'}</span></td>
                <td><span className={`pill ${u.active ? 'valid' : 'invalid'}`}>{u.active ? 'Active' : 'Disabled'}</span></td>
                <td>{fmtDate(u.created_at)}</td>
                <td>
                  {u.id === me?.id
                    ? <span className="muted">—</span>
                    : <button className={`btn sm ${u.active ? 'danger' : ''}`} onClick={() => toggleActive(u)}>{u.active ? 'Disable' : 'Enable'}</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {show && (
        <Modal
          title="Add User"
          sub="Create a Zenon admin or agent account"
          onClose={() => !busy && setShow(false)}
          footer={<>
            <button className="btn ghost" disabled={busy} onClick={() => setShow(false)}>Cancel</button>
            <button className="btn" disabled={busy || !f.username || !f.password} onClick={create}>{busy ? 'Creating…' : 'Create User'}</button>
          </>}
        >
          {formErr && <div className="err" style={{ color: '#fca5a5', marginBottom: 12 }}>{formErr}</div>}
          <div className="row"><label>Username</label><input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoFocus /></div>
          <div className="row"><label>Name</label><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div className="row"><label>Password</label><input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} placeholder="min 6 characters" /></div>
          <div className="row"><label>Role</label>
            <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="eo_agent">Admin — their own campaigns &amp; logs only, no cost</option>
              <option value="eo_admin">Superadmin — full access, all data, cost, Users &amp; Settings</option>
            </select>
          </div>
        </Modal>
      )}
    </div>
  )
}
