// Consistent page header used across every admin page.
export default function PageHeader({ title, sub, actions, back }) {
  return (
    <div className="page-head">
      <div className="page-head-text">
        {back}
        <h1 className="page-h1">{title}</h1>
        {sub && <p className="page-desc">{sub}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}
