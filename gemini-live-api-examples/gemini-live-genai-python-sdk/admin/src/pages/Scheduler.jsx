import Callbacks from '../components/Callbacks.jsx'
import CampaignQueue from '../components/CampaignQueue.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Scheduler() {
  return (
    <div className="stack">
      <PageHeader title="Scheduler" sub="Member-requested callbacks and automatic no-answer retries" />
      <Callbacks title="User requested callbacks" desc="Callbacks scheduled at the user's requested time" />
      <CampaignQueue title="Callback attempts" desc="Automatic callbacks when the user does not answer" />
    </div>
  )
}
