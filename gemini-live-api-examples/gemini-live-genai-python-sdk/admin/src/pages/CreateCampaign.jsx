import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import ContactUpload from '../components/ContactUpload.jsx'
import ContactsTable from '../components/ContactsTable.jsx'
import Modal from '../components/Modal.jsx'
import PageHeader from '../components/PageHeader.jsx'

const pad = (n) => String(n).padStart(2, '0')
function todayStr() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` }
function nowTimeStr() { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}` }

// whole-number-only helpers for the callback config fields
const blockDecimalKeys = (e) => { if (['.', ',', 'e', 'E', '+', '-'].includes(e.key)) e.preventDefault() }
function toWhole(v) {
  if (v === '') return ''
  const n = Math.floor(Number(v))
  return Number.isFinite(n) ? String(Math.max(0, n)) : ''
}

export default function CreateCampaign() {
  const navigate = useNavigate()
  const [refreshKey, setRefreshKey] = useState(0)
  const [selected, setSelected] = useState(new Set())
  const [total, setTotal] = useState(0)

  // start-campaign modal
  const [showStart, setShowStart] = useState(false)
  const [name, setName] = useState('')
  const [startDate, setStartDate] = useState(todayStr())
  const [startTime, setStartTime] = useState(nowTimeStr())
  const [delayH, setDelayH] = useState(4)
  const [maxDay, setMaxDay] = useState(3)
  const [days, setDays] = useState(1)
  const [callStart, setCallStart] = useState('09:00')
  const [callEnd, setCallEnd] = useState('21:00')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  // Prefill the retry/calling-hours fields from the admin-tuned defaults (Settings page).
  useEffect(() => {
    api.get('/campaign-defaults').then((d) => {
      if (d.campaign_delay_hours != null) setDelayH(d.campaign_delay_hours)
      if (d.campaign_max_per_day != null) setMaxDay(d.campaign_max_per_day)
      if (d.campaign_days != null) setDays(d.campaign_days)
      if (d.campaign_call_start) setCallStart(d.campaign_call_start)
      if (d.campaign_call_end) setCallEnd(d.campaign_call_end)
    }).catch(() => {})   // endpoint unavailable → keep the hardcoded defaults
  }, [])

  // add-contact modal
  const [showAdd, setShowAdd] = useState(false)
  const [addName, setAddName] = useState('')
  const [addPhone, setAddPhone] = useState('')
  const [addErr, setAddErr] = useState('')
  const [addBusy, setAddBusy] = useState(false)

  const refresh = () => setRefreshKey((k) => k + 1)
  function toggle(id) { setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n }) }
  function toggleMany(ids, checked) { setSelected((s) => { const n = new Set(s); ids.forEach((id) => checked ? n.add(id) : n.delete(id)); return n }) }

  // block past date/time in the picker; today's min time is "now"
  const minTime = startDate === todayStr() ? nowTimeStr() : undefined

  async function startCampaign() {
    setErr(''); setBusy(true)
    try {
      if (!name.trim()) throw new Error('Campaign name is required')
      if (!startDate || !startTime) throw new Error('Start date and time are required')
      const start = new Date(`${startDate}T${startTime}`)
      if (start.getTime() < Date.now() - 60000) throw new Error('Start time is in the past — pick the current time or later')
      const dH = Number(delayH), mD = Number(maxDay), dY = Number(days)
      if (!Number.isInteger(dH) || dH < 0) throw new Error('Call-back hours must be a whole number (0 or more)')
      if (!Number.isInteger(mD) || mD < 1 || mD > 10) throw new Error('Attempts per day must be a whole number between 1 and 10')
      if (!Number.isInteger(dY) || dY < 1 || dY > 10) throw new Error('Call-back days must be a whole number between 1 and 10')
      if (!callStart || !callEnd) throw new Error('Set the calling hours (start and end time)')
      const c = await api.post('/campaigns', {
        name: name.trim(),
        contact_ids: [...selected],
        start_at: start.toISOString(),
        callback_delay_hours: dH,
        callback_max_per_day: mD,
        callback_days: dY,
        call_start: callStart,
        call_end: callEnd,
      })
      navigate(`/campaigns/${c.id}`)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function addContact() {
    setAddBusy(true); setAddErr('')
    try {
      await api.post('/contacts', { name: addName, phone: addPhone })
      setShowAdd(false); setAddName(''); setAddPhone(''); refresh()
    } catch (e) { setAddErr(e.message) } finally { setAddBusy(false) }
  }

  async function deleteSelected() {
    if (!selected.size) return
    if (!confirm(`Delete ${selected.size} contact(s) from your pool? They won't be available for any campaign.`)) return
    await api.post('/contacts/delete', { ids: [...selected] })
    setSelected(new Set()); refresh()
  }

  return (
    <div className="stack" style={{ paddingBottom: 72 }}>
      <PageHeader title="Create Campaign" sub="Upload contacts, pick recipients, and launch a calling campaign" />

      <ContactUpload step={1} onImported={refresh} />

      <div className="panel">
        <div className="panel-head">
          <h3>2. Contacts</h3>
          <div style={{ display: 'flex', gap: 10 }}>
            {selected.size > 0 && <button className="btn danger sm" onClick={deleteSelected}>Delete from pool ({selected.size})</button>}
            <button className="btn ghost sm" onClick={() => { setAddErr(''); setShowAdd(true) }}>+ Add Contact</button>
          </div>
        </div>
        <ContactsTable
          selectable selected={selected} onToggle={toggle} onToggleMany={toggleMany}
          onTotal={setTotal} refreshKey={refreshKey}
        />
      </div>

      <div style={{
        position: 'fixed', left: 'var(--sidebar-w)', right: 0, bottom: 0, padding: '12px 26px',
        background: 'rgba(19,14,34,0.94)', borderTop: '1px solid var(--border)', backdropFilter: 'blur(8px)',
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
          {err && <div className="err" style={{ marginBottom: 12 }}>{err}</div>}
          <div className="row">
            <label>Campaign Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Personal Loan Follow-up — Batch 1" autoFocus />
          </div>
          <div className="row">
            <label>Selected Contacts</label>
            <input value={`${selected.size} contacts`} readOnly style={{ opacity: 0.7 }} />
          </div>
          <div className="two">
            <div><label>Start Date</label><input type="date" min={todayStr()} value={startDate} onChange={(e) => setStartDate(e.target.value)} /></div>
            <div><label>Start Time</label><input type="time" min={minTime} value={startTime} onChange={(e) => setStartTime(e.target.value)} /></div>
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <label>Call back if no answer (hours)</label>
            <input type="number" min="0" step="1" inputMode="numeric" value={delayH}
                   onKeyDown={blockDecimalKeys} onChange={(e) => setDelayH(toWhole(e.target.value))} />
          </div>
          <div className="two">
            <div><label>Attempts per day (1–10)</label>
              <input type="number" min="1" max="10" step="1" inputMode="numeric" value={maxDay}
                     onKeyDown={blockDecimalKeys} onChange={(e) => setMaxDay(toWhole(e.target.value))} /></div>
            <div><label>For how many days (1–10)</label>
              <input type="number" min="1" max="10" step="1" inputMode="numeric" value={days}
                     onKeyDown={blockDecimalKeys} onChange={(e) => setDays(toWhole(e.target.value))} /></div>
          </div>
          <div className="two" style={{ marginTop: 14 }}>
            <div><label>Call only after (IST)</label>
              <input type="time" value={callStart} onChange={(e) => setCallStart(e.target.value)} /></div>
            <div><label>…and before (IST)</label>
              <input type="time" value={callEnd} onChange={(e) => setCallEnd(e.target.value)} /></div>
          </div>
          <div className="row" style={{ marginTop: 6, fontSize: '0.78rem', color: 'var(--muted)' }}>
            No calls (campaign or callbacks) are placed outside these hours.
          </div>
        </Modal>
      )}

      {showAdd && (
        <Modal
          title="Add Contact"
          sub="Add a single contact to the pool"
          onClose={() => !addBusy && setShowAdd(false)}
          footer={<>
            <button className="btn ghost" disabled={addBusy} onClick={() => setShowAdd(false)}>Cancel</button>
            <button className="btn" disabled={addBusy || !addPhone} onClick={addContact}>{addBusy ? 'Adding…' : 'Add'}</button>
          </>}
        >
          {addErr && <div className="err" style={{ marginBottom: 10 }}>{addErr}</div>}
          <div className="row"><label>Name</label><input value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus /></div>
          <div className="row"><label>Phone</label><input value={addPhone} onChange={(e) => setAddPhone(e.target.value)} placeholder="9876543210 or +9198…" /></div>
        </Modal>
      )}
    </div>
  )
}
