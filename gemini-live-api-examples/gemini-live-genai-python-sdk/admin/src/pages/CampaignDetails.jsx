import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import CallLogs, { fmtDate } from '../components/CallLogs.jsx'
import CampaignRecipients from '../components/CampaignRecipients.jsx'
import PageHeader from '../components/PageHeader.jsx'
import { minToHHMM } from './MyCampaigns.jsx'

export default function CampaignDetails() {
  const { id } = useParams()
  const [c, setC] = useState(null)
  const [err, setErr] = useState('')

  async function load() {
    try { setC(await api.get(`/campaigns/${id}`)) }
    catch (e) { setErr(e.message) }
  }
  useEffect(() => { load() }, [id])

  async function cancelCampaign() {
    if (!confirm(`Cancel campaign "${c.name}"?`)) return
    try { await api.post(`/campaigns/${id}/cancel`); load() }
    catch (e) { alert(e.message) }
  }

  const p = c?.progress || {}
  const stat = [
    ['Total', c?.contact_count || 0],
    ['Pending', p.pending || 0],
    ['Calling', p.calling || 0],
    ['Done', p.done || 0],
    ['Failed', p.failed || 0],
    ['Cancelled', p.cancelled || 0],
    ['No answer', p.no_answer || 0],
  ]

  return (
    <div className="stack">
      <PageHeader
        back={<Link to="/campaigns" className="backlink">← My Campaigns</Link>}
        title={c
          ? <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              {c.name}
              <span className={`pill ${c.status}`}>{c.status === 'live' && <span className="dot" />}{c.status}</span>
            </span>
          : 'Campaign'}
        sub={c ? `Starts ${fmtDate(c.start_at)} · ${c.contact_count} contacts` : ''}
        actions={c && (c.status === 'scheduled' || c.status === 'live')
          ? <button className="btn danger" onClick={cancelCampaign}>Cancel Campaign</button>
          : null}
      />
      {err && <div className="err" style={{ marginTop: -8 }}>{err}</div>}

      {c && (
        <div className="grid stat-grid tight">
          {stat.map(([label, val]) => (
            <div className="card stat" key={label}>
              <div className="label">{label}</div>
              <div className="value" style={{ fontSize: '1.35rem' }}>{val}</div>
            </div>
          ))}
        </div>
      )}

      {c && (
        <div className="muted" style={{ fontSize: '0.8rem' }}>
          Calling hours {minToHHMM(c.call_start_min ?? 540)}–{minToHHMM(c.call_end_min ?? 1260)}
          {' · '}Retries: up to {c.callback_max_per_day || 3}/day for {c.callback_days || 1} day{(c.callback_days || 1) > 1 ? 's' : ''}, every {c.callback_delay_hours ?? 4}h
          {' · '}Created {fmtDate(c.created_at)}
        </div>
      )}

      <CampaignRecipients campaignId={id} />

      <CallLogs title="Campaign Call Logs" campaignId={id} showCampaignColumn={false} showSource={false} />
    </div>
  )
}
