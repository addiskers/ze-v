import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Callbacks from '../components/Callbacks.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Settings() {
  const [counts, setCounts] = useState({ contacts: null, campaigns: null })

  useEffect(() => {
    Promise.all([
      api.get('/contacts?limit=1').then((d) => d.total).catch(() => null),
      api.get('/campaigns?limit=1').then((d) => d.total).catch(() => null),
    ]).then(([contacts, campaigns]) => setCounts({ contacts, campaigns }))
  }, [])

  return (
    <div className="stack">
      <PageHeader title="Settings" sub="Platform overview and the calling scheduler" />

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="label">Contacts in pool</div>
          <div className="value">{counts.contacts ?? '—'}</div>
        </div>
        <div className="card stat">
          <div className="label">Total campaigns</div>
          <div className="value">{counts.campaigns ?? '—'}</div>
        </div>
      </div>

      <Callbacks title="Calling Scheduler" />

      <div className="card">
        <div className="panel-head"><h3>About</h3></div>
        <div className="muted" style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
          EO AI Calling Platform. Campaigns dial paced outbound calls with GvoxAi, the EO voice agent.
          Only one campaign can be scheduled or live at a time. Turning the scheduler off pauses all
          outbound dialing and callbacks.
        </div>
      </div>
    </div>
  )
}
