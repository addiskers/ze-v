import { useEffect, useMemo, useState } from 'react'
import { api, qs, getToken } from '../api.js'
import { useAuth } from '../auth.jsx'
import { IconSearch, IconDownload, IconPhone } from './icons.jsx'

export function fmtDur(s) {
  s = Math.round(Number(s) || 0)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}
export function fmtDate(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}
export function fmtCost(v) {
  const n = Number(v)
  return Number.isFinite(n) ? `$${n.toFixed(4)}` : '—'
}

function StatusPill({ call }) {
  const s = (call.status || call.rsvp_outcome_status || '').toLowerCase()
  const cls = s.includes('complete') || call.booking_created ? 'green'
    : s.includes('fail') || s.includes('abandon') ? 'red'
    : s.includes('progress') || s.includes('live') ? 'blue' : 'amber'
  return <span className={`pill ${cls}`}><span className="dot" />{call.status || call.rsvp_outcome_status || 'done'}</span>
}

// Reusable call-logs panel. Pass `campaignId` to scope to one campaign.
export default function CallLogs({ campaignId, title = 'Call Logs', showCampaignColumn = true }) {
  const { isAdmin } = useAuth()
  const colCount = 7 + (showCampaignColumn ? 1 : 0) + (isAdmin ? 1 : 0)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [detail, setDetail] = useState(null)

  const [q, setQ] = useState('')
  const [source, setSource] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [sort, setSort] = useState({ key: 'started_at', dir: 'desc' })
  const [page, setPage] = useState(0)
  const pageSize = 25

  const filters = useMemo(() => ({
    q, source, from, to, campaign_id: campaignId || '',
    limit: pageSize, offset: page * pageSize,
  }), [q, source, from, to, campaignId, page])

  useEffect(() => {
    let cancel = false
    setLoading(true)
    api.get(`/calls${qs(filters)}`)
      .then((d) => { if (!cancel) { setItems(d.items || []); setTotal(d.total ?? (d.items || []).length); setErr('') } })
      .catch((e) => { if (!cancel) setErr(e.message) })
      .finally(() => { if (!cancel) setLoading(false) })
    return () => { cancel = true }
  }, [filters])

  const sorted = useMemo(() => {
    const arr = [...items]
    const { key, dir } = sort
    arr.sort((a, b) => {
      let x = a[key], y = b[key]
      if (key === 'duration_seconds' || key === 'total_cost_usd') { x = Number(x) || 0; y = Number(y) || 0 }
      if (x == null) return 1
      if (y == null) return -1
      return (x > y ? 1 : x < y ? -1 : 0) * (dir === 'asc' ? 1 : -1)
    })
    return arr
  }, [items, sort])

  function th(key, label, extra = '') {
    const active = sort.key === key
    return (
      <th className={extra} onClick={() => setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))}>
        {label}{active && <span className="arrow">{sort.dir === 'desc' ? '▾' : '▴'}</span>}
      </th>
    )
  }

  function reset() { setQ(''); setSource(''); setFrom(''); setTo(''); setPage(0) }

  function exportCsv() {
    const url = `/api/eo/calls.csv${qs({ q, source, from, to, campaign_id: campaignId || '' })}`
    fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => r.blob())
      .then((b) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(b)
        a.download = 'call_logs.csv'
        a.click()
        URL.revokeObjectURL(a.href)
      })
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{title}</h3>
        <button className="btn ghost sm" onClick={exportCsv} style={{ display: 'flex', gap: 6 }}><IconDownload /> Export CSV</button>
      </div>

      <div className="toolbar">
        <div className="search">
          <span className="ic"><IconSearch /></span>
          <input placeholder="Search caller / phone…" value={q} onChange={(e) => { setPage(0); setQ(e.target.value) }} />
        </div>
        <select value={source} onChange={(e) => { setPage(0); setSource(e.target.value) }}>
          <option value="">All Sources</option>
          <option value="plivo">Plivo</option>
          <option value="browser">Browser</option>
        </select>
        <input type="date" value={from} onChange={(e) => { setPage(0); setFrom(e.target.value) }} title="From" />
        <input type="date" value={to} onChange={(e) => { setPage(0); setTo(e.target.value) }} title="To" />
        <button className="btn ghost sm" onClick={reset}>Reset</button>
      </div>

      {err && <div className="err" style={{ color: '#fca5a5', marginBottom: 10 }}>{err}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {th('started_at', 'Started')}
              {th('source', 'Source')}
              {th('caller', 'Caller')}
              {showCampaignColumn && th('campaign_name', 'Campaign')}
              {th('duration_seconds', 'Duration', 'num')}
              {th('language', 'Language')}
              {th('status', 'Status')}
              <th className="no-sort">RSVP</th>
              {isAdmin && th('total_cost_usd', 'Cost', 'num')}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={colCount} className="empty">Loading…</td></tr>
            ) : sorted.length === 0 ? (
              <tr><td colSpan={colCount} className="empty">No calls yet.</td></tr>
            ) : sorted.map((c) => (
              <tr key={c.id || c.call_sid} className="clickable" onClick={() => openDetail(c)}>
                <td>{fmtDate(c.started_at)}</td>
                <td><span className="pill src">{c.source || '—'}</span></td>
                <td>{c.caller || c.phone || '—'}</td>
                {showCampaignColumn && <td>{c.campaign_name || <span className="muted">—</span>}</td>}
                <td className="num">{fmtDur(c.duration_seconds)}</td>
                <td>{c.language || '—'}</td>
                <td><StatusPill call={c} /></td>
                <td>{c.rsvp_outcome_status || (c.booking_created ? 'yes' : '—')}</td>
                {isAdmin && <td className="num">{fmtCost(c.total_cost_usd)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="pager">
        <span>{total} total</span>
        <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</button>
        <span>Page {page + 1}</span>
        <button disabled={(page + 1) * pageSize >= total} onClick={() => setPage((p) => p + 1)}>Next</button>
      </div>

      {detail && <CallDrawer call={detail} onClose={() => setDetail(null)} />}
    </div>
  )

  function openDetail(c) {
    const id = c.id || c.call_sid
    setDetail({ ...c, _loading: true })
    api.get(`/calls/${encodeURIComponent(id)}`)
      .then((full) => setDetail(full))
      .catch(() => setDetail((d) => (d ? { ...d, _loading: false } : d)))
  }
}

function CallDrawer({ call, onClose }) {
  const { isAdmin } = useAuth()
  const msgs = call.messages || call.transcript || []
  const hasCost = isAdmin && (call.total_cost_usd != null || call.gemini_cost_usd != null)
  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 540, maxHeight: '85vh', overflowY: 'auto' }} onClick={(e) => e.stopPropagation()}>
        <div className="row-between">
          <h3 style={{ display: 'flex', gap: 8, alignItems: 'center' }}><IconPhone /> {call.caller || call.phone || 'Call'}</h3>
          <button className="btn ghost sm" onClick={onClose}>Close</button>
        </div>
        <div className="sub">{fmtDate(call.started_at)} · {call.source} · {fmtDur(call.duration_seconds)}</div>
        <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', marginBottom: 14 }}>
          <div><label>Status</label><StatusPill call={call} /></div>
          <div><label>RSVP</label>{call.rsvp_outcome_status || (call.booking_created ? 'yes' : '—')}</div>
          {call.campaign_name && <div><label>Campaign</label>{call.campaign_name}</div>}
          {call.language && <div><label>Language</label>{call.language}</div>}
        </div>
        {hasCost && (
          <div className="card" style={{ marginBottom: 14, padding: 12 }}>
            <label>Cost (admin only)</label>
            <div className="grid" style={{ gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
              <div><span className="muted" style={{ fontSize: '0.7rem' }}>Total</span><div style={{ fontFamily: 'var(--mono)' }}>{fmtCost(call.total_cost_usd)}</div></div>
              <div><span className="muted" style={{ fontSize: '0.7rem' }}>Gemini</span><div style={{ fontFamily: 'var(--mono)' }}>{fmtCost(call.gemini_cost_usd)}</div></div>
              <div><span className="muted" style={{ fontSize: '0.7rem' }}>Tokens</span><div style={{ fontFamily: 'var(--mono)' }}>{call.tokens?.total ?? '—'}</div></div>
            </div>
          </div>
        )}
        <label>Transcript</label>
        <div className="stack" style={{ gap: 8 }}>
          {call._loading ? <div className="muted">Loading transcript…</div>
            : Array.isArray(msgs) && msgs.length ? msgs.map((m, i) => (
              <div key={i} style={{ fontSize: '0.82rem' }}>
                <b style={{ color: (m.role === 'user' || m.speaker === 'user') ? 'var(--blue)' : 'var(--green)' }}>
                  {(m.role || m.speaker) === 'user' ? 'Caller' : 'GvoxAi'}:
                </b>{' '}
                {m.text || m.content || m.transcript}
              </div>
            )) : <div className="muted">No transcript recorded.</div>}
        </div>
      </div>
    </div>
  )
}
