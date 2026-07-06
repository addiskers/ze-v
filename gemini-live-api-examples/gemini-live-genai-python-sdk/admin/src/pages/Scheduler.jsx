import Callbacks from '../components/Callbacks.jsx'
import CampaignQueue from '../components/CampaignQueue.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Scheduler() {
  return (
    <div className="stack">
      <PageHeader title="Scheduler" sub="Pending callbacks and the upcoming campaign dial queue" />
      <Callbacks title="Scheduled Callbacks" />
      <CampaignQueue title="Upcoming Campaign Calls" />
    </div>
  )
}
