import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate } from './CallLogs.jsx'

// Scheduler / callbacks panel — reused on Dashboard and the Scheduler page.
export default function Callbacks({ title = 'Callbacks', canToggle = true }) {
  const [items, setItems] = useState([])
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api.get('/callbacks')
      .then((d) => { setItems(d.items || []); setEnabled(!!d.scheduler_enabled); setErr('') })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function toggle() {
    try {
      const r = await api.post('/scheduler/toggle', { enabled: !enabled })
      setEnabled(r.enabled)
    } catch (e) { setErr(e.message) }
  }

  async function act(id, path) {
    try { await api.post(`/callbacks/${encodeURIComponent(id)}/${path}`); load() }
    catch (e) { setErr(e.message) }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{title}</h3>
        <div className="toggle" onClick={canToggle ? toggle : undefined} style={{ cursor: canToggle ? 'pointer' : 'default' }}>
          Scheduler: {enabled ? 'ON' : 'OFF'}
          <span className={`track ${enabled ? 'on' : ''}`}><span className="knob" /></span>
        </div>
      </div>
      {err && <div style={{ color: '#fca5a5', fontSize: '0.8rem', marginBottom: 10 }}>{err}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="no-sort">Caller</th>
              <th className="no-sort">Due</th>
              <th className="no-sort num">Attempts</th>
              <th className="no-sort">Status</th>
              <th className="no-sort">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="empty">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={5} className="empty">No pending callbacks.</td></tr>
            ) : items.map((c) => {
              const cb = c.callback || c
              const id = c.id || c.call_sid
              return (
                <tr key={id}>
                  <td>{c.caller || c.phone || '—'}</td>
                  <td>{fmtDate(cb.due_at || cb.next_retry_at)}</td>
                  <td className="num">{cb.attempts ?? 0}</td>
                  <td><span className={`pill ${(cb.status || 'pending')}`}>{cb.status || 'pending'}</span></td>
                  <td style={{ display: 'flex', gap: 6 }}>
                    <button className="btn sm" onClick={() => act(id, 'call-now')}>Call now</button>
                    <button className="btn ghost sm" onClick={() => act(id, 'cancel')}>Cancel</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
