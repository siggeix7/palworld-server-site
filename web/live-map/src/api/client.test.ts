import { afterEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import { AUTH_REQUIRED_EVENT, clearApiCache, FORBIDDEN_EVENT, requestJson } from './client'

afterEach(() => {
  clearApiCache()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.history.replaceState({}, '', '/')
  // biome-ignore lint/suspicious/noDocumentCookie: cookie parsing is the behavior under test
  document.cookie = 'csrftoken=; Max-Age=0; path=/'
})

describe('API client', () => {
  it('uses same-origin credentials and validates successful JSON', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson('/api/test', z.object({ ok: z.boolean() }))).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/test',
      expect.objectContaining({ cache: 'no-store', credentials: 'same-origin' })
    )
  })

  it('adds JSON and CSRF headers to mutations', async () => {
    // biome-ignore lint/suspicious/noDocumentCookie: cookie parsing is the behavior under test
    document.cookie = 'csrftoken=token%2D123; path=/'
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await requestJson('/api/test', z.object({ ok: z.boolean() }), { json: { value: 1 } })

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = new Headers(init.headers)
    expect(headers.get('X-CSRFToken')).toBe('token-123')
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"value":1}')
  })

  it('surfaces JSON error messages and emits the authentication event', async () => {
    const listener = vi.fn()
    window.addEventListener(AUTH_REQUIRED_EVENT, listener)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'sessione scaduta' }), { status: 401 }))
    )

    await expect(requestJson('/api/private', z.object({ ok: z.boolean() }))).rejects.toMatchObject({
      message: 'sessione scaduta',
      status: 401
    })
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener(AUTH_REQUIRED_EVENT, listener)
  })

  it('aborts a request when its real timeout expires', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_path: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
          })
      )
    )

    const request = requestJson('/api/slow', z.object({ ok: z.boolean() }), { timeoutMs: 25 })
    const rejection = expect(request).rejects.toEqual(expect.objectContaining({ code: 'timeout' }))
    await vi.advanceTimersByTimeAsync(30)
    await rejection
    vi.useRealTimers()
  })

  it('returns guided recovery for terms acceptance failures', async () => {
    const listener = vi.fn()
    window.addEventListener(FORBIDDEN_EVENT, listener)
    window.history.replaceState({}, '', '/mondo/?tab=regole')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'terms acceptance required' }), { status: 403 }))
    )

    await expect(requestJson('/api/private', z.object({ ok: z.boolean() }))).rejects.toMatchObject({
      status: 403,
      actionLabel: 'Accetta le condizioni',
      actionUrl: '/accounts/accept-terms/?next=%2Fmondo%2F%3Ftab%3Dregole'
    })
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener(FORBIDDEN_EVENT, listener)
  })
})
