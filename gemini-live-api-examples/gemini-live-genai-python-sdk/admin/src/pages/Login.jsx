import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth.jsx'

export default function Login() {
  const { login, user } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) { navigate('/', { replace: true }) }

  async function submit(e) {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      await login(username.trim(), password)
      navigate('/', { replace: true })
    } catch (e) {
      setErr(e.message || 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">
          <div className="logo">EO</div>
          <div>
            <div className="name">EO AI Calling</div>
            <div className="sub">Admin Platform</div>
          </div>
        </div>
        {err && <div className="err">{err}</div>}
        <div className="row">
          <label>Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
        </div>
        <div className="row">
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        <button className="btn" style={{ width: '100%', marginTop: 6 }} disabled={busy || !username || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
