import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import { usePolling } from './usePolling'

const POLL_INTERVAL_MS = 60_000
const schema = z.object({ value: z.string() })

async function flushAsyncWork() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('usePolling ETag validation', () => {
  it('reuses an ETag after its response passes schema validation', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ value: 'valid' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json', ETag: '"valid"' }
        })
      )
      .mockResolvedValueOnce(new Response(null, { status: 304 }))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => usePolling('/api/test', POLL_INTERVAL_MS, schema))

    await flushAsyncWork()
    expect(result.current.data).toEqual({ value: 'valid' })
    const firstRequest = fetchMock.mock.calls[0][1] as RequestInit
    expect(firstRequest).toEqual(expect.objectContaining({ cache: 'no-store', credentials: 'same-origin' }))

    await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS))

    const secondRequest = fetchMock.mock.calls[1][1] as RequestInit
    expect(new Headers(secondRequest.headers).get('If-None-Match')).toBe('"valid"')
  })

  it('does not store an ETag from a response that fails schema validation', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ value: 42 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json', ETag: '"invalid"' }
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ value: 'recovered' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => usePolling('/api/test', POLL_INTERVAL_MS, schema))

    await flushAsyncWork()
    expect(result.current.error?.message).toBe('/api/test returned an invalid response')
    await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS))
    await flushAsyncWork()

    const secondRequest = fetchMock.mock.calls[1][1] as RequestInit
    expect(new Headers(secondRequest.headers).get('If-None-Match')).toBeNull()
    expect(result.current.data).toEqual({ value: 'recovered' })
  })
})
