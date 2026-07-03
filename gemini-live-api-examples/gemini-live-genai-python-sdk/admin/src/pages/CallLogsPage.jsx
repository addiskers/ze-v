import CallLogs from '../components/CallLogs.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function CallLogsPage() {
  return (
    <div className="stack">
      <PageHeader title="Call Logs" sub="Every call across all campaigns" />
      <CallLogs title="All Calls" />
    </div>
  )
}
