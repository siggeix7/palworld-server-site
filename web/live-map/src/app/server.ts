import { createContext, useContext } from 'react'
import type { Snapshot } from '../api/contracts'
import type { ResourceState } from '../api/useApiResource'

export const ServerContext = createContext<ResourceState<Snapshot> | null>(null)

export function useServerSnapshot() {
  const resource = useContext(ServerContext)
  if (!resource) throw new Error('ServerContext non disponibile')
  return resource
}
