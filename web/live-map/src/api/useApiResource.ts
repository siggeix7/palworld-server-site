import { useEffect, useEffectEvent, useRef, useState } from 'react'

interface ResourceOptions {
  key: string
  intervalMs?: number
  enabled?: boolean
  clearOnError?: boolean
}

export interface ResourceState<T> {
  data: T | null
  error: Error | null
  loading: boolean
  refreshing: boolean
  reload: () => void
}

export function useApiResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  options: ResourceOptions
): ResourceState<T> {
  const { key, intervalMs, enabled = true, clearOnError = false } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [revision, setRevision] = useState(0)
  const previousKey = useRef(key)
  const loadLatest = useEffectEvent(load)

  // biome-ignore lint/correctness/useExhaustiveDependencies: key and revision deliberately restart the request lifecycle
  useEffect(() => {
    if (previousKey.current !== key) {
      previousKey.current = key
      setData(null)
      setError(null)
    }
    if (!enabled) {
      setData(null)
      setError(null)
      setRefreshing(false)
      return
    }
    let stopped = false
    let activeController: AbortController | null = null
    let timer: number | undefined
    let failures = 0
    let requestSequence = 0

    const schedule = () => {
      if (intervalMs && !stopped && !document.hidden) {
        const delay = Math.min(300_000, intervalMs * 2 ** Math.min(failures, 3))
        timer = window.setTimeout(execute, delay)
      }
    }
    const execute = async () => {
      if (document.hidden || stopped || activeController) return
      const sequence = ++requestSequence
      const controller = new AbortController()
      activeController = controller
      setRefreshing(true)
      try {
        const nextData = await loadLatest(controller.signal)
        if (!stopped && sequence === requestSequence) {
          setData(nextData)
          setError(null)
          failures = 0
        }
      } catch (cause) {
        if (!stopped && !controller.signal.aborted && sequence === requestSequence) {
          failures += 1
          if (clearOnError) setData(null)
          setError(cause instanceof Error ? cause : new Error(String(cause)))
        }
      } finally {
        if (activeController === controller) activeController = null
        if (!stopped && sequence === requestSequence) {
          setRefreshing(false)
          schedule()
        }
      }
    }
    const onVisibility = () => {
      if (document.hidden) {
        if (timer !== undefined) window.clearTimeout(timer)
        activeController?.abort('hidden')
      } else {
        void execute()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    void execute()
    return () => {
      stopped = true
      requestSequence += 1
      activeController?.abort('unmount')
      if (timer !== undefined) window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [clearOnError, enabled, intervalMs, key, revision])

  return {
    data,
    error,
    loading: enabled && !data && !error,
    refreshing,
    reload: () => setRevision((value) => value + 1)
  }
}
