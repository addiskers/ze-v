// Placeholder for pages landing in a later build phase. Keeps the nav/routing
// wired and the app building while the real UI is filled in.
export default function Stub({ title, sub, note }) {
  return (
    <div className="stack">
      <div>
        <div style={{ fontSize: '1.02rem', fontWeight: 700 }}>{title}</div>
        {sub && <div className="page-sub">{sub}</div>}
      </div>
      <div className="card center" style={{ minHeight: 220 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--secondary)' }}>{title}</div>
          <div className="muted" style={{ marginTop: 6 }}>{note || 'Coming in the next build phase.'}</div>
        </div>
      </div>
    </div>
  )
}
