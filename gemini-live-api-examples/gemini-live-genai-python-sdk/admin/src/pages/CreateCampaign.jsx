import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import ContactUpload from '../components/ContactUpload.jsx'
import ContactsTable from '../components/ContactsTable.jsx'
import Modal from '../components/Modal.jsx'
import PageHeader from '../components/PageHeader.jsx'

function todayStr() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export default function CreateCampaign() {
  const navigate = useNavigate()
  const [refreshKey, setRefreshKey] = useState(0)
  const [selected, setSelected] = useState(new Set())
  const [total, setTotal] = useState(0)
  const [showStart, setShowStart] = useState(false)

  // modal fields
  const [name, setName] = useState('')
  const [startDate, setStartDate] = useState(todayStr())
  const [startTime, setStartTime] = useState('10:00')
  const [delayH, setDelayH] = useState(4)
  const [maxDay, setMaxDay] = useState(3)
  const [days, setDays] = useState(1)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = () => setRefreshKey((k) => k + 1)
  function toggle(id) {
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  function toggleMany(ids, checked) {
    setSelected((s) => { const n = new Set(s); ids.forEach((id) => checked ? n.add(id) : n.delete(id)); return n })
  }

  async function startCampaign() {
    setErr(''); setBusy(true)
    try {
      if (!name.trim()) throw new Error('Campaign name is required')
      if (!startDate || !startTime) throw new Error('Start date and time are required')
      const start_at = new Date(`${startDate}T${startTime}`).toISOString()
      const c = await api.post('/campaigns', {
        name: name.trim(),
        contact_ids: [...selected],
        start_at,
        callback_delay_hours: Number(delayH),
        callback_max_per_day: Number(maxDay),
        callback_days: Number(days),
      })
      navigate(`/campaigns/${c.id}`)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack" style={{ paddingBottom: 72 }}>
      <PageHeader title="Create Campaign" sub="Upload contacts, pick recipients, and launch a calling campaign" />

      <ContactUpload step={1} onImported={refresh} />

      <div className="panel">
        <div className="panel-head"><h3>2. Contacts</h3></div>
        <ContactsTable
          selectable selected={selected} onToggle={toggle} onToggleMany={toggleMany}
          onTotal={setTotal} refreshKey={refreshKey}
        />
      </div>

      <div style={{
        position: 'fixed', left: 'var(--sidebar-w)', right: 0, bottom: 0, padding: '12px 26px',
        background: 'rgba(13,19,32,0.94)', borderTop: '1px solid var(--border)', backdropFilter: 'blur(8px)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', zIndex: 30,
      }}>
        <span className="muted"><b style={{ color: 'var(--text)' }}>{selected.size}</b> of {total} selected</span>
        <button className="btn" disabled={selected.size === 0} onClick={() => { setErr(''); setShowStart(true) }}>Start Campaign</button>
      </div>

      {showStart && (
        <Modal
          title="Start Campaign"
          onClose={() => !busy && setShowStart(false)}
          footer={<>
            <button className="btn ghost" disabled={busy} onClick={() => setShowStart(false)}>Cancel</button>
            <button className="btn" disabled={busy} onClick={startCampaign}>{busy ? 'Starting…' : 'Start Campaign'}</button>
          </>}
        >
          {err && <div className="err" style={{ color: '#fca5a5', marginBottom: 12 }}>{err}</div>}
          <div className="row">
            <label>Campaign Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Varun Dhawan Evening — Batch 1" autoFocus />
          </div>
          <div className="row">
            <label>Selected Contacts</label>
            <input value={`${selected.size} contacts`} readOnly style={{ opacity: 0.7 }} />
          </div>
          <div className="two">
            <div><label>Start Date</label><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></div>
            <div><label>Start Time</label><input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} /></div>
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <label>Call back if no answer (hours)</label>
            <input type="number" min="0" step="1" value={delayH} onChange={(e) => setDelayH(e.target.value)} />
          </div>
          <div className="two">
            <div><label>Attempts per day (1–10)</label><input type="number" min="1" max="10" step="1" value={maxDay} onChange={(e) => setMaxDay(e.target.value)} /></div>
            <div><label>For how many days (1–10)</label><input type="number" min="1" max="10" step="1" value={days} onChange={(e) => setDays(e.target.value)} /></div>
          </div>
        </Modal>
      )}
    </div>
  )
}
