import { useEffect, useRef, useState } from 'react'

// Inline-editable remark cell: Enter/blur saves via async onSave (optimistic, reverts on failure), Escape cancels; stops click propagation so row clicks never fire.
export default function RemarkCell({ value, onSave, disabled = false, disabledTitle = '' }) {
  const [text, setText] = useState(value || '')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [err, setErr] = useState('')
  const inputRef = useRef(null)
  const cancelRef = useRef(false)

  useEffect(() => { setText(value || '') }, [value])
  useEffect(() => { if (editing) inputRef.current?.focus() }, [editing])

  function start(e) {
    e.stopPropagation()
    if (disabled) return
    setErr(''); setDraft(text); setEditing(true)
  }

  async function save() {
    setEditing(false)
    const next = draft.trim()
    if (next === text) return
    const prev = text
    setText(next) // optimistic
    try { await onSave(next); setErr('') }
    catch (e) { setText(prev); setErr(e.message || 'Save failed') }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter') { e.preventDefault(); e.target.blur() } // blur → save
    else if (e.key === 'Escape') { e.stopPropagation(); cancelRef.current = true; setEditing(false) }
  }

  function onBlur() {
    if (cancelRef.current) { cancelRef.current = false; return }
    save()
  }

  if (editing) {
    return (
      <span onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          value={draft}
          placeholder="Add remark…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={onBlur}
          style={{ width: 160, height: 28, fontSize: '0.78rem', padding: '2px 8px' }}
        />
      </span>
    )
  }

  const shown = text.length > 40 ? `${text.slice(0, 40)}…` : text
  return (
    <span
      onClick={start}
      title={disabled ? disabledTitle : (text || 'Click to add a remark')}
      style={{ cursor: disabled ? 'default' : 'pointer', display: 'inline-block', maxWidth: 200 }}
    >
      {text
        ? <span style={{ fontSize: '0.78rem' }}>{shown}</span>
        : <span className="muted" style={{ fontSize: '0.75rem', opacity: disabled ? 0.5 : 1 }}>+ remark</span>}
      {err && <span style={{ display: 'block', color: '#fca5a5', fontSize: '0.7rem' }}>{err}</span>}
    </span>
  )
}
