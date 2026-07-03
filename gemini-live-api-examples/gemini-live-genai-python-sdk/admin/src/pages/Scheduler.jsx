import Callbacks from '../components/Callbacks.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Scheduler() {
  return (
    <div className="stack">
      <PageHeader title="Scheduler" sub="Pending callbacks and the calling scheduler" />
      <Callbacks title="Scheduled Callbacks" />
    </div>
  )
}
