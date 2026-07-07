import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate } from './CallLogs.jsx'

// Campaign RETRY attempts — only contacts the campaign runner is re-dialing after an
// unanswered attempt (retry scheduled, retry in progress, or retried and still
// unreached). Fresh first dials and answered contacts are NOT shown. Sibling of
// <Callbacks> on the Scheduler page: that panel is the member's own "call me back
// later" requests; this one is the automatic no-answer redials.
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
    const at = c.campaign_status === 'scheduled' ? c.campaign_start_at : c.next_attempt_at
    const when = at ? fmtDate(at) : 'as soon as the queue allows'
    if (!window.confirm(`Call ${c.name || c.phone} NOW instead of waiting for ${when}?\n\n"Call now" dials immediately.`)) return
    try { await api.post(`/campaigns/${c.campaign_id}/contacts/${c.id}/retry`); load() }
    catch (e) { setErr(e.message) }
  }

  // When this contact rings next (open rows) or last rang (history rows).
  function whenCell(c) {
    if (c.call_status === 'calling') return <span className="muted">In progress</span>
    if (['done', 'failed', 'no_answer'].includes(c.call_status))   // history — show when it last rang
      return c.last_attempt_at ? <span className="muted">{fmtDate(c.last_attempt_at)}</span> : <span className="muted">—</span>
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
              <th className="no-sort">Next / last call</th>
              <th className="no-sort num">Attempts</th>
              <th className="no-sort num">Total attempts</th>
              <th className="no-sort">Outcome</th>
              <th className="no-sort">Status</th>
              <th className="no-sort">Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="empty">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={9} className="empty">No callback attempts yet.</td></tr>
            ) : items.map((c) => (
              <tr key={c.id}>
                <td>{c.campaign_name || <span className="muted">—</span>}</td>
                <td>{c.name || <span className="muted">—</span>}</td>
                <td style={{ fontFamily: 'var(--mono)' }}>{c.phone}</td>
                <td>{whenCell(c)}</td>
                <td className="num">{c.attempts}</td>
                <td className="num">{(c.campaign_max_per_day || 3) * (c.campaign_days || 1)}</td>
                <td>{c.rsvp_outcome ? <span className={`pill ${c.rsvp_outcome}`}>{c.rsvp_outcome}</span> : <span className="muted">—</span>}</td>
                <td><span className={`pill ${c.call_status}`}>{c.call_status}</span></td>
                <td>
                  {['pending', 'failed', 'no_answer'].includes(c.call_status)
                    ? <button className="btn sm" onClick={() => callNow(c)}>Call now</button>
                    : <span className="muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager"><span>{items.length} callback attempt{items.length === 1 ? '' : 's'}</span></div>
    </div>
  )
}
