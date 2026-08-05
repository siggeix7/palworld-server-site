import { useEffect, useState } from 'react'
import type { ZodType } from 'zod'

export const AUTHENTICATION_REQUIRED_EVENT = 'palworld-live-map:authentication-required'
export const ACCESS_FORBIDDEN_EVENT = 'palworld-live-map:access-forbidden'

export function notifyAuthenticationRequired() {
  window.dispatchEvent(new Event(AUTHENTICATION_REQUIRED_EVENT))
}

export function notifyAccessForbidden() {
  window.dispatchEvent(new Event(ACCESS_FORBIDDEN_EVENT))
}

export interface PollResult<T> {
  data: T | null
  error: Error | null
}

export function usePolling<T>(path: string, intervalMs: number, schema: ZodType<T>, enabled = true): PollResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    if (!enabled) return

    let stopped = false
    let activeController: AbortController | null = null
    let timeout: number | undefined
    let etag: string | null = null
    let requesting = false

    const refresh = async () => {
      if (stopped || document.hidden || requesting) return
      requesting = true
      activeController = new AbortController()
      const requestTimer = window.setTimeout(() => activeController?.abort('timeout'), 10_000)
      try {
        const headers = new Headers()
        if (etag) headers.set('If-None-Match', etag)
        const response = await fetch(path, {
          cache: 'no-store',
          credentials: 'same-origin',
          headers,
          signal: activeController.signal
        })
        if (response.status === 401) {
          setData(null)
          notifyAuthenticationRequired()
          throw new Error(`${path} requires authentication`)
        }
        if (response.status === 403) {
          setData(null)
          notifyAccessForbidden()
          throw new Error(`${path} is forbidden`)
        }
        if (response.status === 304) {
          setError(null)
          return
        }
        if (!response.ok) throw new Error(`${path} returned ${response.status}`)
        etag = response.headers.get('ETag')
        const parsed = schema.safeParse(await response.json())
        if (!parsed.success) throw new Error(`${path} returned an invalid response`)
        setData(parsed.data)
        setError(null)
      } catch (cause) {
        if (!stopped && activeController?.signal.reason !== 'hidden') {
          setError(cause instanceof Error ? cause : new Error(String(cause)))
        }
      } finally {
        window.clearTimeout(requestTimer)
        requesting = false
        activeController = null
        if (!stopped && !document.hidden) timeout = window.setTimeout(refresh, intervalMs)
      }
    }

    const onVisibility = () => {
      if (document.hidden) {
        if (timeout !== undefined) window.clearTimeout(timeout)
        activeController?.abort('hidden')
      } else {
        void refresh()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    void refresh()
    return () => {
      stopped = true
      activeController?.abort()
      if (timeout !== undefined) window.clearTimeout(timeout)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [enabled, intervalMs, path, schema])

  return { data, error }
}
