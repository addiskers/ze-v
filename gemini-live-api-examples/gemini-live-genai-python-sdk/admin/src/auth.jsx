import { createContext, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api.js'

const AuthCtx = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function boot() {
      if (!getToken()) { setReady(true); return }
      try {
        const r = await api.get('/me')
        if (!cancelled) setUser(r.user)
      } catch {
        setToken('')
      } finally {
        if (!cancelled) setReady(true)
      }
    }
    boot()
    return () => { cancelled = true }
  }, [])

  async function login(username, password) {
    const r = await api.post('/login', { username, password })
    setToken(r.token)
    setUser(r.user)
    return r.user
  }

  function logout() {
    setToken('')
    setUser(null)
  }

  return (
    <AuthCtx.Provider value={{ user, ready, login, logout, isAdmin: user?.role === 'eo_admin' }}>
      {children}
    </AuthCtx.Provider>
  )
}

export function useAuth() {
  return useContext(AuthCtx)
}
