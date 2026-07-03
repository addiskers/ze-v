import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate } from './CallLogs.jsx'

// The campaign's recipient roster: who is in the campaign and each one's dial state
// (with last_error surfaced, so misconfig like a missing PUBLIC_URL is visible here).
export default function CampaignRecipients({ campaignId }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/campaigns/${campaignId}/contacts`)
      .then((d) => { setItems(d.items || []); setTotal(d.total || 0); setErr('') })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [campaignId])

  useEffect(() => { load() }, [load])

  async function callNow(cc) {
    try { await api.post(`/campaigns/${campaignId}/contacts/${cc.id}/retry`); load() }
    catch (e) { alert(e.message) }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Recipients</h3>
        <button className="btn ghost sm" onClick={load}>Refresh</button>
      </div>
      {err && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{err}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="no-sort">Name</th>
              <th className="no-sort">Phone Number</th>
              <th className="no-sort">Status</th>
              <th className="no-sort num">Attempts</th>
              <th className="no-sort">Last Attempt</th>
              <th className="no-sort">Last Error</th>
              <th className="no-sort">Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="empty">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={7} className="empty">No recipients.</td></tr>
            ) : items.map((c) => (
              <tr key={c.id}>
                <td>{c.name || <span className="muted">—</span>}</td>
                <td style={{ fontFamily: 'var(--mono)' }}>{c.phone}</td>
                <td><span className={`pill ${c.call_status}`}>{c.call_status}</span></td>
                <td className="num">{c.attempts}</td>
                <td>{c.last_attempt_at ? fmtDate(c.last_attempt_at) : <span className="muted">—</span>}</td>
                <td style={{ maxWidth: 260, color: c.last_error ? '#fca5a5' : 'var(--muted)', fontSize: '0.78rem' }}>
                  {c.last_error || '—'}
                </td>
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
      <div className="pager"><span>{total} recipients</span></div>
    </div>
  )
}
