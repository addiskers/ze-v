import Callbacks from '../components/Callbacks.jsx'
import CampaignQueue from '../components/CampaignQueue.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Scheduler() {
  return (
    <div className="stack">
      <PageHeader title="Scheduler" sub="Callbacks the member asked for, and the campaign's no-answer retry attempts" />
      <Callbacks title="User requested callbacks" statuses="pending,in_flight" />
      <CampaignQueue title="Callback attempts" />
    </div>
  )
}
