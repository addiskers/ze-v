import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { useAuth } from '../auth.jsx'
import CallLogs, { fmtDate, fmtCost } from '../components/CallLogs.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Dashboard() {
  const { isAdmin } = useAuth()
  const [s, setS] = useState(null)
  const [active, setActive] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get('/summary').then(setS).catch((e) => setErr(e.message))
    api.get('/campaigns/active').then((r) => setActive(r.campaign)).catch(() => {})
  }, [])

  const bySource = s?.by_source || {}
  const yesRate = s ? Math.round((s.booking_conversion_rate || 0) * 100) : 0

  return (
    <div className="stack">
      <PageHeader title="Dashboard" sub="Overview of your EO calling activity" />

      {active && (
        <Link to={`/campaigns/${active.id}`} className="card" style={{ display: 'block', borderColor: 'rgba(16,185,129,0.35)' }}>
          <div className="row-between">
            <div>
              <div className="label" style={{ color: 'var(--green)' }}>
                Current {active.status === 'live' ? 'Live' : 'Scheduled'} Campaign
                {active.status === 'live' && <span className="live-dot" style={{ marginLeft: 8 }} />}
              </div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, marginTop: 6 }}>{active.name}</div>
              <div className="page-sub">Starts {fmtDate(active.start_at)} · {active.contact_count} contacts</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="value" style={{ fontSize: '1.4rem' }}>
                {(active.progress?.done || 0)}/{active.contact_count}
              </div>
              <div className="page-sub">completed</div>
            </div>
          </div>
        </Link>
      )}

      {err && <div style={{ color: '#fca5a5' }}>{err}</div>}

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="label">Total Calls</div>
          <div className="value">{s ? s.total_calls : '—'}</div>
          <div className="sub">Plivo {bySource.plivo || bySource.twilio || 0} · Browser {bySource.browser || 0}</div>
        </div>
        <div className="card stat">
          <div className="label">Total Minutes</div>
          <div className="value">{s ? s.total_minutes : '—'}</div>
          <div className="sub">{s ? `${s.total_seconds || 0}s across all calls` : ''}</div>
        </div>
        <div className="card stat">
          <div className="label">RSVP Yes-Rate</div>
          <div className="value">{s ? `${yesRate}%` : '—'}</div>
          <div className="sub">{s ? `${s.bookings || 0} coming` : ''}</div>
        </div>
      </div>

      {isAdmin && s && (
        <div className="grid stat-grid">
          <div className="card stat">
            <div className="label">Total Cost</div>
            <div className="value" style={{ color: 'var(--green)' }}>{fmtCost(s.total_cost_usd)}</div>
            <div className="sub">Gemini {fmtCost(s.gemini_cost_usd)}</div>
          </div>
          <div className="card stat">
            <div className="label">Avg / Call</div>
            <div className="value">{fmtCost(s.avg_cost_per_call)}</div>
            <div className="sub">across {s.total_calls || 0} calls</div>
          </div>
          <div className="card stat">
            <div className="label">This Month</div>
            <div className="value">{fmtCost(s.this_month?.cost_usd)}</div>
            <div className="sub">projected {fmtCost(s.projected_month_cost)}</div>
          </div>
        </div>
      )}

      <CallLogs title="Call Logs" showSource={false} />
    </div>
  )
}
