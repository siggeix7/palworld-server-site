import { createContext, useContext } from 'react'
import type { Session } from '../api/contracts'

export const SessionContext = createContext<Session | null>(null)

export function useSession() {
  return useContext(SessionContext)
}

export function sessionIsAdmin(session: Session | null) {
  return session?.siteAdmin === true
}
