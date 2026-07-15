export default function Modal({ title, sub, onClose, children, footer, width }) {
  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal" style={width ? { maxWidth: `min(${width}px, calc(100vw - 24px))` } : undefined} onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        {sub && <div className="sub">{sub}</div>}
        {children}
        {footer && <div className="actions">{footer}</div>}
      </div>
    </div>
  )
}
