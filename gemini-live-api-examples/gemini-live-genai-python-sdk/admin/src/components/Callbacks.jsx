import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate } from './CallLogs.jsx'
import Modal from './Modal.jsx'

const pad = (n) => String(n).padStart(2, '0')
const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` }
const nowTimeStr = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}` }

// Scheduler / callbacks panel — reused on Dashboard and the Scheduler page.
export default function Callbacks({ title = 'Callbacks', canToggle = true }) {
  const [items, setItems] = useState([])
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [resch, setResch] = useState(null)   // { id, date, time }
  const [reschErr, setReschErr] = useState('')
  const [busy, setBusy] = useState(false)

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

  async function doReschedule() {
    setBusy(true); setReschErr('')
    try {
      if (!resch.date || !resch.time) throw new Error('Pick a date and time')
      const dt = new Date(`${resch.date}T${resch.time}`)
      if (dt.getTime() < Date.now() - 60000) throw new Error('Pick a time in the future')
      await api.post(`/callbacks/${encodeURIComponent(resch.id)}/reschedule`, { due_at: dt.toISOString() })
      setResch(null); load()
    } catch (e) { setReschErr(e.message) } finally { setBusy(false) }
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
              <th className="no-sort">Name</th>
              <th className="no-sort">Caller</th>
              <th className="no-sort">Due</th>
              <th className="no-sort num">Attempts</th>
              <th className="no-sort">Status</th>
              <th className="no-sort">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="empty">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={6} className="empty">No pending callbacks.</td></tr>
            ) : items.map((c) => {
              const cb = c.callback || c
              const id = c.id || c.call_sid
              const done = ['completed', 'cancelled', 'in_flight'].includes(cb.status)
              return (
                <tr key={id}>
                  <td>{c.contact_name || <span className="muted">—</span>}</td>
                  <td>{c.caller || c.phone || '—'}</td>
                  <td>{fmtDate(cb.due_at || cb.next_retry_at)}</td>
                  <td className="num">{cb.attempts ?? 0}</td>
                  <td><span className={`pill ${(cb.status || 'pending')}`}>{cb.status || 'pending'}</span></td>
                  <td style={{ display: 'flex', gap: 6 }}>
                    <button className="btn sm" disabled={done} onClick={() => act(id, 'call-now')}>Call now</button>
                    <button className="btn ghost sm" disabled={done} onClick={() => { setReschErr(''); setResch({ id, date: todayStr(), time: nowTimeStr() }) }}>Reschedule</button>
                    <button className="btn ghost sm" disabled={cb.status === 'cancelled'} onClick={() => act(id, 'cancel')}>Cancel</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {resch && (
        <Modal
          title="Reschedule callback"
          sub="Pick a new date and time to call back"
          width={400}
          onClose={() => !busy && setResch(null)}
          footer={<>
            <button className="btn ghost" disabled={busy} onClick={() => setResch(null)}>Cancel</button>
            <button className="btn" disabled={busy} onClick={doReschedule}>{busy ? 'Saving…' : 'Reschedule'}</button>
          </>}
        >
          {reschErr && <div className="err" style={{ marginBottom: 12 }}>{reschErr}</div>}
          <div className="two">
            <div><label>Date</label><input type="date" min={todayStr()} value={resch.date} onChange={(e) => setResch({ ...resch, date: e.target.value })} /></div>
            <div><label>Time</label><input type="time" value={resch.time} onChange={(e) => setResch({ ...resch, time: e.target.value })} /></div>
          </div>
        </Modal>
      )}
    </div>
  )
}
