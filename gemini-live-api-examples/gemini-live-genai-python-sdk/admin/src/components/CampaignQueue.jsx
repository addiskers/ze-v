import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate } from './CallLogs.jsx'
import RemarkCell from './RemarkCell.jsx'

// Campaign auto-dial queue (distinct from <Callbacks>, which handles RSVP "call me back later").
// onMeta (optional, pass a stable fn) reports { scheduler_enabled, active_campaign } to the parent.
export default function CampaignQueue({ title = 'Callback attempts', desc = '', onMeta }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api.get('/scheduler/campaign-queue')
      .then((d) => {
        setItems(d.items || [])
        onMeta?.({ scheduler_enabled: d.scheduler_enabled, active_campaign: d.active_campaign })
        setErr('')
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [onMeta])

  useEffect(() => { load() }, [load])

  async function callNow(c) {
    const at = c.campaign_status === 'scheduled' ? c.campaign_start_at : c.next_attempt_at
    const when = at ? fmtDate(at) : 'as soon as the queue allows'
    if (!window.confirm(`Call ${c.name || c.phone} NOW instead of waiting for ${when}?\n\n"Call now" dials immediately.`)) return
    try { await api.post(`/campaigns/${c.campaign_id}/contacts/${c.id}/retry`); load() }
    catch (e) { setErr(e.message) }
  }

  async function cancelRetry(c) {
    if (!window.confirm(`Cancel the pending retry for ${c.name || c.phone}?\n\nNo more automatic calls will be made.`)) return
    try { await api.post(`/campaigns/${c.campaign_id}/contacts/${c.id}/cancel`); load() }
    catch (e) { setErr(e.message) }
  }

  function nextDueCell(c) {
    if (c.call_status === 'calling') return <span className="muted">In progress</span>
    if (c.next_attempt_at) return fmtDate(c.next_attempt_at)
    if (c.campaign_status === 'scheduled' && c.campaign_start_at) return fmtDate(c.campaign_start_at)
    return <span className="muted">—</span>
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <h3>{title}</h3>
          {desc && <div className="muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>{desc}</div>}
        </div>
        <button className="btn ghost sm" onClick={load}>Refresh</button>
      </div>
      {err && <div style={{ color: '#fca5a5', fontSize: '0.8rem', marginBottom: 10 }}>{err}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="no-sort">Name</th>
              <th className="no-sort">Phone</th>
              <th className="no-sort">Campaign</th>
              <th className="no-sort">Last Attempt</th>
              <th className="no-sort">Next Call Due</th>
              <th className="no-sort num">Attempts</th>
              <th className="no-sort">Status</th>
              <th className="no-sort">Remark</th>
              <th className="no-sort">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="empty">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={9} className="empty">No callback attempts yet.</td></tr>
            ) : items.map((c) => (
              <tr key={c.id}>
                <td>{c.name || <span className="muted">—</span>}</td>
                <td style={{ fontFamily: 'var(--mono)' }}>{c.phone}</td>
                <td>{c.campaign_name || <span className="muted">—</span>}</td>
                <td>{fmtDate(c.last_attempt_at)}</td>
                <td>{nextDueCell(c)}</td>
                <td className="num">{c.attempts} / {(c.campaign_max_per_day || 3) * (c.campaign_days || 1)}</td>
                <td>
                  <span className={`pill ${c.display_variant || 'amber'}`} title={c.last_error || undefined}>
                    {c.display_status || c.call_status}
                  </span>
                </td>
                <td>
                  <RemarkCell value={c.remark} onSave={(v) => api.patch(`/campaigns/${c.campaign_id}/contacts/${c.id}/remark`, { remark: v })} />
                </td>
                <td style={{ display: 'flex', gap: 6 }}>
                  {['pending', 'failed', 'no_answer', 'cancelled'].includes(c.call_status)
                    ? <button className="btn sm" onClick={() => callNow(c)}>Call now</button>
                    : <span className="muted">—</span>}
                  {c.call_status === 'pending' &&
                    <button className="btn ghost sm" onClick={() => cancelRetry(c)}>Cancel</button>}
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
