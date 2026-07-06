import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate } from './CallLogs.jsx'

// Upcoming campaign dial queue — the pending/calling contacts the runner will call
// next across the live/scheduled campaign(s). Sibling of <Callbacks> on the Scheduler
// page: callbacks are RSVP "call me back later"; this is the campaign auto-dial queue.
export default function CampaignQueue({ title = 'Callback attempts' }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api.get('/scheduler/campaign-queue')
      .then((d) => { setItems(d.items || []); setErr('') })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function callNow(c) {
    try { await api.post(`/campaigns/${c.campaign_id}/contacts/${c.id}/retry`); load() }
    catch (e) { setErr(e.message) }
  }

  // When this contact is expected to ring next.
  function whenCell(c) {
    if (c.call_status === 'calling') return <span className="muted">In progress</span>
    // A not-yet-started campaign rings at its start time; a live one at next_attempt_at.
    const at = c.campaign_status === 'scheduled' ? c.campaign_start_at : c.next_attempt_at
    return at ? fmtDate(at) : <span className="muted">Queued</span>
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{title}</h3>
        <button className="btn ghost sm" onClick={load}>Refresh</button>
      </div>
      {err && <div style={{ color: '#fca5a5', fontSize: '0.8rem', marginBottom: 10 }}>{err}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="no-sort">Campaign</th>
              <th className="no-sort">Name</th>
              <th className="no-sort">Phone Number</th>
              <th className="no-sort">Next Call</th>
              <th className="no-sort num">Attempts</th>
              <th className="no-sort num">Total attempts</th>
              <th className="no-sort">Status</th>
              <th className="no-sort">Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="empty">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8} className="empty">No callback attempts pending.</td></tr>
            ) : items.map((c) => (
              <tr key={c.id}>
                <td>{c.campaign_name || <span className="muted">—</span>}</td>
                <td>{c.name || <span className="muted">—</span>}</td>
                <td style={{ fontFamily: 'var(--mono)' }}>{c.phone}</td>
                <td>{whenCell(c)}</td>
                <td className="num">{c.attempts}</td>
                <td className="num">{(c.campaign_max_per_day || 3) * (c.campaign_days || 1)}</td>
                <td><span className={`pill ${c.call_status}`}>{c.call_status}</span></td>
                <td>
                  {c.call_status === 'pending'
                    ? <button className="btn sm" onClick={() => callNow(c)}>Call now</button>
                    : <span className="muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager"><span>{items.length} upcoming</span></div>
    </div>
  )
}
