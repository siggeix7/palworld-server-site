import { useEffect, useState } from 'react'

export const AUTHENTICATION_REQUIRED_EVENT = 'palworld-live-map:authentication-required'

export function notifyAuthenticationRequired() {
  window.dispatchEvent(new Event(AUTHENTICATION_REQUIRED_EVENT))
}

export interface PollResult<T> {
  data: T | null
  error: Error | null
}

export function usePolling<T>(path: string, intervalMs: number, enabled = true): PollResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    if (!enabled) return

    const controller = new AbortController()
    let timeout: number | undefined

    const refresh = async () => {
      try {
        const response = await fetch(path, { cache: 'no-store', signal: controller.signal })
        if (response.status === 401 || response.status === 403) {
          setData(null)
          notifyAuthenticationRequired()
          throw new Error(`${path} requires authentication`)
        }
        if (!response.ok) throw new Error(`${path} returned ${response.status}`)
        setData((await response.json()) as T)
        setError(null)
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause : new Error(String(cause)))
      } finally {
        if (!controller.signal.aborted) timeout = window.setTimeout(refresh, intervalMs)
      }
    }

    void refresh()
    return () => {
      controller.abort()
      if (timeout !== undefined) window.clearTimeout(timeout)
    }
  }, [enabled, intervalMs, path])

  return { data, error }
}
