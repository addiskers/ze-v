import { useCallback, useState } from 'react'
import Callbacks from '../components/Callbacks.jsx'
import CampaignQueue from '../components/CampaignQueue.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Scheduler() {
  // { scheduler_enabled, active_campaign } — reported by the queue fetch; the
  // Callbacks panel's toggle also updates the enabled flag so the banner tracks it.
  const [meta, setMeta] = useState(null)
  // Stable callback (identity matters: it feeds a useCallback dep in <Callbacks>).
  // Only patch the flag once the queue meta exists so we never show a half-built meta.
  const onEnabledChange = useCallback((en) => {
    setMeta((m) => (m ? { ...m, scheduler_enabled: en } : m))
  }, [])

  return (
    <div className="stack">
      <PageHeader title="Scheduler" sub="Member-requested callbacks and automatic no-answer retries" />
      {meta && meta.scheduler_enabled === false && (
        <div style={{
          background: 'var(--amber-soft)', color: 'var(--amber)',
          border: '1px solid rgba(251,191,36,0.3)', borderRadius: 'var(--radius-sm)',
          padding: '10px 14px', fontSize: '0.85rem', fontWeight: 600,
        }}>
          Scheduler is OFF — no calls will be dialed until it's turned on
        </div>
      )}
      {meta && !meta.active_campaign && (
        <div className="muted" style={{ fontSize: '0.8rem' }}>
          No campaign is active — campaign retries resume when a campaign is live
        </div>
      )}
      <Callbacks
        title="User requested callbacks"
        desc="Callbacks scheduled at the user's requested time"
        onEnabledChange={onEnabledChange}
      />
      <CampaignQueue title="Callback attempts" desc="Automatic callbacks when the user does not answer" onMeta={setMeta} />
    </div>
  )
}
