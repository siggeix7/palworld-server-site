import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DataState } from '../shared/ui'
import { useApiResource } from './useApiResource'

function Harness({
  load,
  clearOnError = false
}: {
  load: (signal: AbortSignal) => Promise<string>
  clearOnError?: boolean
}) {
  const resource = useApiResource(load, { key: 'test-resource', clearOnError })
  return (
    <DataState
      loading={resource.loading}
      error={resource.error}
      onRetry={resource.reload}
      hasData={Boolean(resource.data)}
    >
      <p>{resource.data}</p>
      {resource.data ? (
        <button type="button" onClick={resource.reload}>
          Aggiorna test
        </button>
      ) : null}
    </DataState>
  )
}

afterEach(cleanup)

describe('useApiResource', () => {
  it('keeps the last valid payload visible when a refresh fails', async () => {
    const load = vi.fn().mockResolvedValueOnce('dato valido').mockRejectedValueOnce(new Error('collector offline'))
    const user = userEvent.setup()
    render(<Harness load={load} />)

    expect(await screen.findByText('dato valido')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Aggiorna test' }))
    expect(await screen.findByText(/Continuo a mostrare gli ultimi dati validi/)).toBeVisible()
    expect(screen.getByText('dato valido')).toBeVisible()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('removes a sensitive payload when a refresh fails', async () => {
    const load = vi.fn().mockResolvedValueOnce('dato riservato').mockRejectedValueOnce(new Error('accesso scaduto'))
    const user = userEvent.setup()
    render(<Harness load={load} clearOnError />)

    expect(await screen.findByText('dato riservato')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Aggiorna test' }))

    expect(await screen.findByText('accesso scaduto')).toBeVisible()
    expect(screen.queryByText('dato riservato')).not.toBeInTheDocument()
    expect(screen.queryByText(/Continuo a mostrare gli ultimi dati validi/)).not.toBeInTheDocument()
  })
})
