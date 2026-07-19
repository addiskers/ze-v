import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, downloadFile } from '../api.js'
import PageHeader from '../components/PageHeader.jsx'

// Settings is a Superadmin-only route (App.jsx <Protected adminOnly>). The write
// endpoints (/admin/settings) are additionally role-gated server-side.

const fmtUsd = (v) => (v == null ? '—' : `$${Number(v).toFixed(2)}`)
const pick = (obj, keys) => Object.fromEntries(keys.map((k) => [k, obj?.[k]]))

// Each card owns its OWN keys, form state and save — a failure or success in one
// card can never silently drop or commit edits made in the other.
const DEF_KEYS = ['campaign_call_start', 'campaign_call_end', 'campaign_max_per_day',
                  'campaign_days', 'campaign_delay_hours', 'campaign_max_concurrent', 'campaign_max_per_tick']
const AGENT_KEYS = ['agent_voice', 'agent_language']

const VOICES = [
  { value: 'Aoede', label: 'Aoede — warm female (default)' },
  { value: 'Kore', label: 'Kore — female (crisper on phone audio)' },
]
const LANGUAGES = [
  { value: 'hi-IN', label: 'Hindi (hi-IN) — default' },
  { value: 'en-IN', label: 'Indian English (en-IN)' },
  { value: 'gu-IN', label: 'Gujarati (gu-IN)' },
]

const fieldsetStyle = { border: 0, padding: 0, margin: 0, minWidth: 0 }

export default function Settings() {
  const [counts, setCounts] = useState({ contacts: null, campaigns: null })
  const [summary, setSummary] = useState(null)          // cost stats (Superadmin gets cost fields)
  const [activeCampaign, setActiveCampaign] = useState(null)

  // Master scheduler switch (queue tables live on the Scheduler page)
  const [enabled, setEnabled] = useState(null)
  const [schedErr, setSchedErr] = useState('')

  // Server snapshot of effective settings + one independent form per card
  const [settings, setSettings] = useState(null)
  const [loadErr, setLoadErr] = useState('')
  const [defForm, setDefForm] = useState(null)
  const [defMsg, setDefMsg] = useState(''); const [defErr, setDefErr] = useState(''); const [defSaving, setDefSaving] = useState(false)
  const [agForm, setAgForm] = useState(null)
  const [agMsg, setAgMsg] = useState(''); const [agErr, setAgErr] = useState(''); const [agSaving, setAgSaving] = useState(false)

  // Change password
  const [cur, setCur] = useState('')
  const [nw, setNw] = useState('')
  const [pwMsg, setPwMsg] = useState('')
  const [pwErr, setPwErr] = useState('')
  const [pwBusy, setPwBusy] = useState(false)

  const [exportErr, setExportErr] = useState('')

  useEffect(() => {
    Promise.all([
      api.get('/contacts?limit=1').then((d) => d.total).catch(() => null),
      api.get('/campaigns?limit=1').then((d) => d.total).catch(() => null),
    ]).then(([contacts, campaigns]) => setCounts({ contacts, campaigns }))
    api.get('/summary').then(setSummary).catch(() => {})
    api.get('/campaigns?limit=100')
      .then((d) => setActiveCampaign((d.items || []).find((c) => c.status === 'live' || c.status === 'scheduled') || null))
      .catch(() => {})
    api.get('/callbacks')
      .then((d) => setEnabled(!!d.scheduler_enabled))
      .catch((e) => setSchedErr(e.message))
    api.get('/admin/settings')
      .then((d) => {
        setSettings(d.settings)
        setDefForm(pick(d.settings, DEF_KEYS))
        setAgForm(pick(d.settings, AGENT_KEYS))
      })
      .catch((e) => setLoadErr(e.message))
  }, [])

  async function toggle() {
    if (enabled && !window.confirm(
      'Switch the scheduler OFF?\n\nWhile it is off, scheduled callbacks will NOT be attempted — they will stay pending until you switch the scheduler back on.'
    )) return
    try {
      const r = await api.post('/scheduler/toggle', { enabled: !enabled })
      setEnabled(!!r.enabled)
      setSchedErr('')
    } catch (e) { setSchedErr(e.message) }
  }

  const dirtyOf = (form) => form && settings && Object.keys(form).some((k) => String(form[k]) !== String(settings[k]))

  // Save ONLY this card's changed keys; on success reset ONLY this card's form to the
  // fresh server snapshot (inputs are disabled while in flight, so no keystrokes race it).
  async function saveCard(form, keys, setForm, setSaving, setErr, setMsg, okMsg) {
    setSaving(true); setErr(''); setMsg('')
    try {
      const changed = {}
      for (const k of keys) {
        if (String(form[k]) !== String(settings[k])) changed[k] = form[k]
      }
      const r = await api.post('/admin/settings', changed)
      setSettings(r.settings)
      setForm(pick(r.settings, keys))
      setMsg(okMsg)
    } catch (e) { setErr(e.message) } finally { setSaving(false) }
  }

  const saveDefaults = () => saveCard(defForm, DEF_KEYS, setDefForm, setDefSaving, setDefErr, setDefMsg,
    'Saved. New campaigns use these defaults; pacing applies within ~30 seconds.')
  const saveAgent = () => saveCard(agForm, AGENT_KEYS, setAgForm, setAgSaving, setAgErr, setAgMsg,
    'Saved — applies from the next call.')

  async function changePassword() {
    setPwBusy(true); setPwErr(''); setPwMsg('')
    try {
      await api.post('/me/password', { current: cur, new: nw })
      setPwMsg('Password updated.'); setCur(''); setNw('')
    } catch (e) { setPwErr(e.message) } finally { setPwBusy(false) }
  }

  function exportAll() {
    setExportErr('')
    downloadFile('/calls.csv', 'call_logs.csv').catch((e) => setExportErr(e.message))
  }

  const num = (form, setForm, key, min, max) => (
    <input type="number" min={min} max={max} value={form[key] ?? ''} className="input-num"
           onChange={(e) => { setForm((f) => ({ ...f, [key]: e.target.value })); setDefMsg('') }} />
  )
  const time = (form, setForm, key) => (
    <input type="time" value={form[key] ?? ''} className="input-time"
           onChange={(e) => { setForm((f) => ({ ...f, [key]: e.target.value })); setDefMsg('') }} />
  )

  return (
    <div className="stack">
      <PageHeader title="Settings" sub="Platform overview, cost, defaults and your account" />

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="label">Contacts in pool</div>
          <div className="value">{counts.contacts ?? '—'}</div>
        </div>
        <div className="card stat">
          <div className="label">Total campaigns</div>
          <div className="value">{counts.campaigns ?? '—'}</div>
        </div>
        <div className="card stat">
          <div className="label">Cost this month</div>
          <div className="value">{fmtUsd(summary?.this_month?.cost_usd)}</div>
          <div className="muted" style={{ fontSize: '0.72rem' }}>{summary?.this_month?.calls ?? '—'} calls · projected {fmtUsd(summary?.projected_month_cost)}</div>
        </div>
        <div className="card stat">
          <div className="label">Avg cost / call</div>
          <div className="value">{fmtUsd(summary?.avg_cost_per_call)}</div>
          <div className="muted" style={{ fontSize: '0.72rem' }}>all-time {fmtUsd(summary?.total_cost_usd)}</div>
        </div>
      </div>

      <div className="card">
        <div className="panel-head">
          <div>
            <h3>Active Campaign</h3>
            <div className="muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>Only one campaign can be scheduled or live at a time.</div>
          </div>
          {activeCampaign
            ? <Link className="btn sm" to={`/campaigns/${activeCampaign.id}`}>Open “{activeCampaign.name}”</Link>
            : <Link className="btn sm" to="/create-campaign">Create campaign</Link>}
        </div>
        <div className="muted" style={{ fontSize: '0.85rem' }}>
          {activeCampaign
            ? <>Status: <b>{activeCampaign.status}</b> · {activeCampaign.done_count ?? 0}/{activeCampaign.contact_count ?? 0} done</>
            : 'No campaign is scheduled or live right now.'}
        </div>
      </div>

      <div className="card">
        <div className="panel-head">
          <div>
            <h3>Calling Scheduler</h3>
            <div className="muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>
              Master switch — OFF pauses all outbound dialing (campaigns, retries and requested callbacks).
              Manage the actual call queue on the Scheduler page.
            </div>
          </div>
          <div className="toggle" onClick={enabled === null ? undefined : toggle}
               style={{ cursor: enabled === null ? 'default' : 'pointer' }}>
            Scheduler: {enabled === null ? '…' : enabled ? 'ON' : 'OFF'}
            <span className={`track ${enabled ? 'on' : ''}`}><span className="knob" /></span>
          </div>
        </div>
        {schedErr && <div style={{ color: '#fca5a5', fontSize: '0.8rem' }}>{schedErr}</div>}
      </div>

      <div className="card">
        <div className="panel-head">
          <div>
            <h3>Campaign Defaults &amp; Pacing</h3>
            <div className="muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>
              Prefills for new campaigns and live dialer pacing. Existing campaigns keep the values they were created with.
            </div>
          </div>
          <button className="btn sm" disabled={!dirtyOf(defForm) || defSaving} onClick={saveDefaults}>{defSaving ? 'Saving…' : 'Save changes'}</button>
        </div>
        {loadErr && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{loadErr}</div>}
        {defErr && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{defErr}</div>}
        {defMsg && <div style={{ color: 'var(--green)', fontSize: '0.82rem', marginBottom: 10 }}>{defMsg}</div>}
        {!defForm ? (!loadErr && <div className="muted">Loading…</div>) : (
          <fieldset disabled={defSaving} style={fieldsetStyle}>
            <div className="stack" style={{ gap: 12 }}>
              <div className="field-row">
                <div className="row"><label>Calling hours (IST)</label>
                  <div className="field-inline">
                    {time(defForm, setDefForm, 'campaign_call_start')} <span className="muted">to</span> {time(defForm, setDefForm, 'campaign_call_end')}
                  </div>
                </div>
              </div>
              <div className="field-row">
                <div className="row"><label>Attempts per day</label>{num(defForm, setDefForm, 'campaign_max_per_day', 1, 10)}</div>
                <div className="row"><label>Retry for (days)</label>{num(defForm, setDefForm, 'campaign_days', 1, 10)}</div>
                <div className="row"><label>Retry every (hours)</label>{num(defForm, setDefForm, 'campaign_delay_hours', 0, 720)}</div>
              </div>
              <div className="field-row">
                <div className="row"><label>Max simultaneous calls</label>{num(defForm, setDefForm, 'campaign_max_concurrent', 1, 20)}</div>
                <div className="row"><label>New dials per tick (~30s)</label>{num(defForm, setDefForm, 'campaign_max_per_tick', 1, 10)}</div>
              </div>
            </div>
          </fieldset>
        )}
      </div>

      <div className="card">
        <div className="panel-head">
          <div>
            <h3>Voice Agent</h3>
            <div className="muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>
              Aria's voice and opening-language bias. Changes apply from the <b>next</b> call — no restart needed.
            </div>
          </div>
          <button className="btn sm" disabled={!dirtyOf(agForm) || agSaving} onClick={saveAgent}>{agSaving ? 'Saving…' : 'Save changes'}</button>
        </div>
        {agErr && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{agErr}</div>}
        {agMsg && <div style={{ color: 'var(--green)', fontSize: '0.82rem', marginBottom: 10 }}>{agMsg}</div>}
        {!agForm ? (!loadErr && <div className="muted">Loading…</div>) : (
          <fieldset disabled={agSaving} style={fieldsetStyle}>
            <div className="field-row">
              <div className="row"><label>Voice</label>
                <select value={agForm.agent_voice ?? ''} onChange={(e) => { setAgForm((f) => ({ ...f, agent_voice: e.target.value })); setAgMsg('') }}>
                  {VOICES.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
                </select>
              </div>
              <div className="row"><label>Opening language</label>
                <select value={agForm.agent_language ?? ''} onChange={(e) => { setAgForm((f) => ({ ...f, agent_language: e.target.value })); setAgMsg('') }}>
                  {LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
                </select>
              </div>
            </div>
          </fieldset>
        )}
      </div>

      <div className="card">
        <div className="panel-head">
          <div>
            <h3>Export Data</h3>
            <div className="muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>Download every call log as CSV (name, phone, time, status, outcome, duration, total duration, language, attempts, remark).</div>
          </div>
          <button className="btn sm" onClick={exportAll}>Export call logs (CSV)</button>
        </div>
        {exportErr && <div style={{ color: '#fca5a5', fontSize: '0.8rem' }}>{exportErr}</div>}
      </div>

      <div className="card" style={{ maxWidth: 460 }}>
        <div className="panel-head"><h3>Change Password</h3></div>
        {pwMsg && <div style={{ color: 'var(--green)', fontSize: '0.82rem', marginBottom: 10 }}>{pwMsg}</div>}
        {pwErr && <div style={{ color: '#fca5a5', fontSize: '0.82rem', marginBottom: 10 }}>{pwErr}</div>}
        <div className="row"><label>Current Password</label><input type="password" value={cur} onChange={(e) => setCur(e.target.value)} /></div>
        <div className="row"><label>New Password</label><input type="password" value={nw} onChange={(e) => setNw(e.target.value)} placeholder="min 6 characters" /></div>
        <button className="btn" style={{ marginTop: 6 }} disabled={pwBusy || !cur || !nw} onClick={changePassword}>{pwBusy ? 'Updating…' : 'Update Password'}</button>
      </div>

      <div className="card">
        <div className="panel-head"><h3>About</h3></div>
        <div className="muted" style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
          Zenon AI Calling Platform. Campaigns dial paced outbound calls with Aria, the Zenon voice agent.
          Only one campaign can be scheduled or live at a time. Turning the scheduler off pauses all
          outbound dialing and callbacks.
        </div>
      </div>
    </div>
  )
}
