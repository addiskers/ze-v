import { useState } from 'react'
import { api } from '../api.js'
import ContactUpload from '../components/ContactUpload.jsx'
import ContactsTable from '../components/ContactsTable.jsx'
import Modal from '../components/Modal.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function Contacts() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [selected, setSelected] = useState(new Set())
  const [showAdd, setShowAdd] = useState(false)
  const [addName, setAddName] = useState('')
  const [addPhone, setAddPhone] = useState('')
  const [addErr, setAddErr] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = () => { setSelected(new Set()); setRefreshKey((k) => k + 1) }

  function toggle(id) {
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  function toggleMany(ids, checked) {
    setSelected((s) => { const n = new Set(s); ids.forEach((id) => checked ? n.add(id) : n.delete(id)); return n })
  }

  async function addContact() {
    setBusy(true); setAddErr('')
    try {
      await api.post('/contacts', { name: addName, phone: addPhone })
      setShowAdd(false); setAddName(''); setAddPhone(''); refresh()
    } catch (e) { setAddErr(e.message) } finally { setBusy(false) }
  }

  async function deleteSelected() {
    if (!selected.size) return
    if (!confirm(`Delete ${selected.size} contact(s)?`)) return
    await api.post('/contacts/delete', { ids: [...selected] })
    refresh()
  }

  return (
    <div className="stack">
      <PageHeader
        title="Contacts"
        sub="Your global contacts pool"
        actions={<>
          {selected.size > 0 && <button className="btn danger" onClick={deleteSelected}>Delete ({selected.size})</button>}
          <button className="btn" onClick={() => setShowAdd(true)}>+ Add Contact</button>
        </>}
      />

      <ContactUpload onImported={refresh} />

      <div className="panel">
        <ContactsTable
          selectable
          selected={selected}
          onToggle={toggle}
          onToggleMany={toggleMany}
          refreshKey={refreshKey}
        />
      </div>

      {showAdd && (
        <Modal
          title="Add Contact"
          sub="Add a single contact to the pool"
          onClose={() => setShowAdd(false)}
          footer={<>
            <button className="btn ghost" onClick={() => setShowAdd(false)}>Cancel</button>
            <button className="btn" disabled={busy || !addPhone} onClick={addContact}>{busy ? 'Adding…' : 'Add'}</button>
          </>}
        >
          {addErr && <div className="err" style={{ color: '#fca5a5', marginBottom: 10 }}>{addErr}</div>}
          <div className="row"><label>Name</label><input value={addName} onChange={(e) => setAddName(e.target.value)} autoFocus /></div>
          <div className="row"><label>Phone</label><input value={addPhone} onChange={(e) => setAddPhone(e.target.value)} placeholder="9876543210 or +9198…" /></div>
        </Modal>
      )}
    </div>
  )
}
