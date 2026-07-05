// Tiny fetch wrapper for /api/eo/*. Attaches the bearer token, JSON-encodes
// bodies, and throws Error(message) on non-2xx so callers can show it.

const TOKEN_KEY = 'eo_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request(method, path, body, opts = {}) {
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  let payload
  if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(`/api/eo${path}`, { method, headers, body: payload })
  if (res.status === 401) {
    setToken('')
    // let the app's auth guard redirect; surface a clear error too
    throw new Error('Not authenticated')
  }
  const ct = res.headers.get('content-type') || ''
  if (opts.raw) return res
  const data = ct.includes('application/json') ? await res.json() : await res.text()
  if (!res.ok) {
    const msg = (data && data.detail) || (typeof data === 'string' ? data : 'Request failed')
    throw new Error(msg)
  }
  return data
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b),
  patch: (p, b) => request('PATCH', p, b),
  del: (p, b) => request('DELETE', p, b),
  raw: (p) => request('GET', p, null, { raw: true }),
}

// Multipart upload (bearer auth, no JSON content-type).
export async function uploadFile(path, file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`/api/eo${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
    body: fd,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || 'Upload failed')
  return data
}

// Authenticated file download → browser save dialog.
export async function downloadFile(path, filename) {
  const res = await fetch(`/api/eo${path}`, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!res.ok) throw new Error('Download failed')
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

// Authenticated binary fetch → Blob (e.g. a call recording for an <audio> player).
// Keeps the bearer token in the header, out of the URL. Aborts after timeoutMs so
// a stuck request can never leave the UI hanging on "Loading…".
export async function getBlob(path, { timeoutMs = 15000 } = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`/api/eo${path}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
      signal: ctrl.signal,
    })
    if (!res.ok) throw new Error('Fetch failed')
    return await res.blob()
  } finally {
    clearTimeout(timer)
  }
}

// Build a query string from a filters object (skips empty values).
export function qs(params) {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') u.set(k, v)
  }
  const s = u.toString()
  return s ? `?${s}` : ''
}
