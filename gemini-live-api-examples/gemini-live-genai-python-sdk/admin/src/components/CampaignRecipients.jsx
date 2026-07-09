import { useCallback, useEffect, useState } from 'react'
import { api, qs } from '../api.js'
import { fmtDate, CallDrawer } from './CallLogs.jsx'
import RemarkCell from './RemarkCell.jsx'
import { IconSearch } from './icons.jsx'

// The campaign's recipient roster: who is in the campaign and each one's dial state
// (with last_error surfaced). Click a recipient that has been attempted to open its call
// (transcript / recording / outcome) in the shared call drawer.
export default function CampaignRecipients({ campaignId }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [detail, setDetail] = useState(null)
  const [note, setNote] = useState('')
  const [q, setQ] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/campaigns/${campaignId}/contacts${qs({ q: q || undefined })}`)
      .then((d) => { setItems(d.items || []); setTotal(d.total || 0); setErr('') })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }, [campaignId, q])

  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t) }, [load, q])

  async function callNow(cc) {
    if (!window.confirm(`Call ${cc.name || cc.phone} now?`)) return
    try { await api.post(`/campaigns/${campaignId}/contacts/${cc.id}/retry`); load() }
    catch (e) { alert(e.message) }
  }

  async function cancelRetry(cc) {
    if (!window.confirm(`Cancel the pending retry for ${cc.name || cc.phone}?\n\nNo more automatic calls will be made.`)) return
    try { await api.post(`/campaigns/${campaignId}/contacts/${cc.id}/cancel`); load() }
    catch (e) { alert(e.message) }
  }

  // Open this recipient's most-recent call in THIS campaign (caller search + campaign scope).
  async function openCall(cc) {
    setNote('')
    try {
      const list = await api.get(`/calls${qs({ campaign_id: campaignId, q: cc.phone, limit: 1 })}`)
      const item = (list.items || [])[0]
      if (!item) {
        setNote(`${cc.name || cc.phone}: attempted ${cc.attempts || 0} time(s)`
          + (cc.last_attempt_at ? `, last ${fmtDate(cc.last_attempt_at)}` : '')
          + ' — no answered call to open yet.')
        return
      }
      setDetail(await api.get(`/calls/${encodeURIComponent(item.id)}`))
    } catch (e) { setNote(e.message) }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Recipients</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div className="search">
            <span className="ic"><IconSearch /></span>
            <input placeholder="Search name / phone…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <button className="btn ghost sm" onClick={load}>Refresh</button>
        </div>
      </div>
      {err && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{err}</div>}
      {note && <div className="muted" style={{ fontSize: '0.8rem', marginBottom: 10 }}>{note}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="no-sort">Name</th>
              <th className="no-sort">Phone Number</th>
              <th className="no-sort">Last Attempt</th>
              <th className="no-sort">Next Call Due</th>
              <th className="no-sort num">Attempts</th>
              <th className="no-sort">Status</th>
              <th className="no-sort">Remark</th>
              <th className="no-sort">Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="empty">Loading…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8} className="empty">{q ? 'No recipients match your search.' : 'No recipients.'}</td></tr>
            ) : items.map((c) => {
              const clickable = (c.attempts || 0) > 0
              return (
                <tr key={c.id} className={clickable ? 'clickable' : ''}
                    onClick={clickable ? () => openCall(c) : undefined}
                    title={clickable ? 'View this recipient’s call' : ''}>
                  <td>{c.name || <span className="muted">—</span>}</td>
                  <td style={{ fontFamily: 'var(--mono)' }}>{c.phone}</td>
                  <td>{c.last_attempt_at ? fmtDate(c.last_attempt_at) : <span className="muted">—</span>}</td>
                  <td>
                    {c.call_status === 'pending'
                      ? (c.next_attempt_at ? fmtDate(c.next_attempt_at) : <span className="muted">Queued</span>)
                      : <span className="muted">—</span>}
                  </td>
                  <td className="num">{c.attempts}</td>
                  <td>
                    <span className={`pill ${c.display_variant || 'amber'}`} title={c.last_error || undefined}>
                      {c.display_status || c.call_status}
                    </span>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <RemarkCell value={c.remark} onSave={(v) => api.patch(`/campaigns/${campaignId}/contacts/${c.id}/remark`, { remark: v })} />
                  </td>
                  <td onClick={(e) => e.stopPropagation()} style={{ display: 'flex', gap: 6 }}>
                    {['pending', 'failed', 'no_answer', 'cancelled'].includes(c.call_status)
                      ? <button className="btn sm" onClick={() => callNow(c)}>Call now</button>
                      : <span className="muted">—</span>}
                    {c.call_status === 'pending' &&
                      <button className="btn ghost sm" onClick={() => cancelRetry(c)}>Cancel</button>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="pager"><span>{total} recipients</span></div>
      {detail && <CallDrawer call={detail} onClose={() => setDetail(null)} />}
    </div>
  )
}
