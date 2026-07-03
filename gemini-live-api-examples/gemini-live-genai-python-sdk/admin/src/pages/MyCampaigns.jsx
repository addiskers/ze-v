import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs } from '../api.js'
import { fmtDate } from '../components/CallLogs.jsx'
import { IconSearch } from '../components/icons.jsx'
import PageHeader from '../components/PageHeader.jsx'

const PAGE = 25

export default function MyCampaigns() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState({ key: 'created_at', dir: 'desc' })
  const [page, setPage] = useState(0)
  const [refreshKey, setRefreshKey] = useState(0)

  const filters = useMemo(() => ({ q, sort: sort.key, dir: sort.dir, limit: PAGE, offset: page * PAGE }), [q, sort, page])

  useEffect(() => {
    let cancel = false
    setLoading(true)
    api.get(`/campaigns${qs(filters)}`)
      .then((d) => { if (!cancel) { setItems(d.items || []); setTotal(d.total || 0); setErr('') } })
      .catch((e) => { if (!cancel) setErr(e.message) })
      .finally(() => { if (!cancel) setLoading(false) })
    return () => { cancel = true }
  }, [filters, refreshKey])

  function th(key, label, extra = '') {
    const active = sort.key === key
    return (
      <th className={extra} onClick={() => { setPage(0); setSort((s) => ({ key, dir: s.key === key && s.dir === 'asc' ? 'desc' : 'asc' })) }}>
        {label}{active && <span className="arrow">{sort.dir === 'asc' ? '▴' : '▾'}</span>}
      </th>
    )
  }

  async function cancelCampaign(e, id, name) {
    e.preventDefault(); e.stopPropagation()
    if (!confirm(`Cancel campaign "${name}"? Pending calls will stop.`)) return
    try { await api.post(`/campaigns/${id}/cancel`); setRefreshKey((k) => k + 1) }
    catch (err) { alert(err.message) }
  }

  return (
    <div className="stack">
      <PageHeader
        title="My Campaigns"
        sub="All your calling campaigns"
        actions={<Link to="/create-campaign" className="btn">+ Create Campaign</Link>}
      />

      <div className="panel">
        <div className="toolbar">
          <div className="search">
            <span className="ic"><IconSearch /></span>
            <input placeholder="Search campaigns…" value={q} onChange={(e) => { setPage(0); setQ(e.target.value) }} />
          </div>
        </div>
        {err && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{err}</div>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {th('name', 'Campaign Name')}
                {th('start_at', 'Start Date')}
                {th('status', 'Status')}
                {th('contact_count', 'Contacts', 'num')}
                {th('created_at', 'Created At')}
                <th className="no-sort">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="empty">Loading…</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={6} className="empty">No campaigns yet. Create one to get started.</td></tr>
              ) : items.map((c) => {
                const done = (c.progress?.done || 0) + (c.progress?.failed || 0)
                return (
                  <tr key={c.id}>
                    <td><Link to={`/campaigns/${c.id}`} style={{ color: 'var(--green)', fontWeight: 600 }}>{c.name}</Link></td>
                    <td>{fmtDate(c.start_at)}</td>
                    <td>
                      <span className={`pill ${c.status}`}>
                        {c.status === 'live' && <span className="dot" />}{c.status}
                      </span>
                    </td>
                    <td className="num">
                      {c.contact_count}
                      {c.contact_count > 0 && (c.status === 'live' || c.status === 'completed') &&
                        <span className="muted" style={{ fontSize: '0.72rem' }}> ({done} done)</span>}
                    </td>
                    <td>{fmtDate(c.created_at)}</td>
                    <td>
                      {(c.status === 'scheduled' || c.status === 'live')
                        ? <button className="btn danger sm" onClick={(e) => cancelCampaign(e, c.id, c.name)}>Cancel Campaign</button>
                        : <span className="muted">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <span>{total} total</span>
          <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</button>
          <span>Page {page + 1} / {Math.max(1, Math.ceil(total / PAGE))}</span>
          <button disabled={(page + 1) * PAGE >= total} onClick={() => setPage((p) => p + 1)}>Next</button>
        </div>
      </div>
    </div>
  )
}
