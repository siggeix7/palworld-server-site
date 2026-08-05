import type { ZodType } from 'zod'

export const AUTH_REQUIRED_EVENT = 'palworld:auth-required'
export const FORBIDDEN_EVENT = 'palworld:forbidden'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly code: 'http' | 'timeout' | 'network' | 'invalid-json' | 'invalid-response',
    readonly actionUrl?: string,
    readonly actionLabel?: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  timeoutMs?: number
  json?: unknown
  etagKey?: string
  forbidden?: 'throw' | 'home'
}

const etagCache = new Map<string, { etag: string; data: unknown }>()

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

function errorMessage(body: unknown, status: number) {
  if (body && typeof body === 'object' && 'error' in body && typeof body.error === 'string') return body.error
  return `Richiesta non riuscita (HTTP ${status})`
}

function forbiddenGuidance(message: string) {
  const next = `${window.location.pathname}${window.location.search}`
  if (message === 'account approval required') return { url: '/accounts/pending/', label: 'Verifica approvazione' }
  if (message === 'password change required') return { url: '/accounts/password-change/', label: 'Cambia password' }
  if (message === 'terms acceptance required') {
    return { url: `/accounts/accept-terms/?next=${encodeURIComponent(next)}`, label: 'Accetta le condizioni' }
  }
  return null
}

function handleAccessError(status: number, forbidden: RequestOptions['forbidden'], message: string) {
  if (status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT))
    if (import.meta.env.MODE !== 'test') {
      const next = `${window.location.pathname}${window.location.search}`
      window.location.assign(`/accounts/login/?next=${encodeURIComponent(next)}`)
    }
  }
  if (status === 403) {
    const guidance = forbiddenGuidance(message)
    window.dispatchEvent(new CustomEvent(FORBIDDEN_EVENT, { detail: guidance }))
    if (import.meta.env.MODE !== 'test') {
      if (guidance) window.location.assign(guidance.url)
      else if (forbidden === 'home') window.location.assign('/')
    }
    return guidance
  }
  return null
}

export async function requestJson<T>(path: string, schema: ZodType<T>, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 10_000, json, etagKey, forbidden = 'throw', headers, signal, ...init } = options
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort(signal?.reason)
  if (signal?.aborted) abort()
  else signal?.addEventListener('abort', abort, { once: true })
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const method = (init.method || (json === undefined ? 'GET' : 'POST')).toUpperCase()
  const requestHeaders = new Headers(headers)
  requestHeaders.set('Accept', 'application/json')
  if (json !== undefined) {
    requestHeaders.set('Content-Type', 'application/json')
    init.method = method
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) requestHeaders.set('X-CSRFToken', csrfToken())
  const cached = etagKey ? etagCache.get(etagKey) : undefined
  if (cached) requestHeaders.set('If-None-Match', cached.etag)

  try {
    const response = await fetch(path, {
      ...init,
      body: json === undefined ? undefined : JSON.stringify(json),
      cache: 'no-store',
      credentials: 'same-origin',
      headers: requestHeaders,
      signal: controller.signal
    })
    if (response.status === 304 && cached) return cached.data as T

    let body: unknown = null
    if (response.status !== 204) {
      try {
        body = await response.json()
      } catch (_cause) {
        if (response.ok) throw new ApiError('Il server ha restituito JSON non valido.', response.status, 'invalid-json')
        body = null
      }
    }
    if (!response.ok) {
      const message = errorMessage(body, response.status)
      const guidance = handleAccessError(response.status, forbidden, message)
      throw new ApiError(message, response.status, 'http', guidance?.url, guidance?.label)
    }
    const parsed = schema.safeParse(body)
    if (!parsed.success) {
      throw new ApiError('La risposta API non rispetta il contratto previsto.', response.status, 'invalid-response')
    }
    const etag = response.headers.get('ETag')
    if (etagKey && etag) etagCache.set(etagKey, { etag, data: parsed.data })
    return parsed.data
  } catch (cause) {
    if (cause instanceof ApiError) throw cause
    if (timedOut) throw new ApiError('Tempo massimo della richiesta superato.', null, 'timeout')
    if (controller.signal.aborted) throw cause
    throw new ApiError('Impossibile contattare il server.', null, 'network')
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
}

export function clearApiCache() {
  etagCache.clear()
}
