import {
  IconActivity,
  IconChartHistogram,
  IconChevronRight,
  IconClock,
  IconKey,
  IconMap,
  IconMenu2,
  IconPlanet,
  IconShieldLock,
  IconSwords,
  IconUsers,
  IconUsersGroup,
  IconX
} from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { api } from '../api/resources'
import { useApiResource } from '../api/useApiResource'
import { readStorage, writeStorage } from '../shared/storage'
import { DataState, StatusBadge } from '../shared/ui'
import { ServerContext } from './server'
import { SessionContext, sessionIsAdmin } from './session'

const themes = [
  ['observatory', 'Osservatorio'],
  ['tron', 'Tron'],
  ['ares', 'Ares'],
  ['clu', 'Clu'],
  ['athena', 'Athena'],
  ['aphrodite', 'Aphrodite'],
  ['poseidon', 'Poseidon']
] as const
type ThemeId = (typeof themes)[number][0]
const themeIds = new Set<string>(themes.map(([id]) => id))

const pageTitles: Record<string, string> = {
  '/': 'Comando',
  '/telemetria/': 'Telemetria',
  '/giocatori/': 'Giocatori',
  '/accesso/': 'Accesso',
  '/mondo/': 'Mondo',
  '/attivita/': 'Attività',
  '/classifica/': 'Classifica',
  '/orari/': 'Orari di punta',
  '/gilde/': 'Gilde',
  '/admin-panel/': 'Admin'
}

const primary = [
  ['/', 'Comando', IconChartHistogram],
  ['/mappa/', 'Mappa', IconMap],
  ['/telemetria/', 'Telemetria', IconActivity],
  ['/mondo/', 'Mondo', IconPlanet],
  ['/accesso/', 'Accesso', IconKey]
] as const
const community = [
  ['/giocatori/', 'Giocatori', IconUsers],
  ['/attivita/', 'Attività', IconSwords],
  ['/classifica/', 'Classifica', IconChartHistogram],
  ['/orari/', 'Orari', IconClock],
  ['/gilde/', 'Gilde', IconUsersGroup]
] as const

export function AppShell() {
  const location = useLocation()
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() =>
    typeof window.matchMedia === 'function' ? window.matchMedia('(max-width: 760px)').matches : window.innerWidth <= 760
  )
  const [theme, setTheme] = useState<ThemeId>(() => {
    const stored = readStorage('observatory.theme')
    return stored && themeIds.has(stored) ? (stored as ThemeId) : 'observatory'
  })
  const session = useApiResource((signal) => api.session(signal), { key: 'session', clearOnError: true })
  const server = useApiResource((signal) => api.snapshot(signal), { key: 'shell-snapshot', intervalMs: 20_000 })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    writeStorage('observatory.theme', theme)
  }, [theme])

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(max-width: 760px)')
    const update = () => {
      setIsMobile(query.matches)
      if (!query.matches) setMenuOpen(false)
    }
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!menuOpen || !isMobile) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setMenuOpen(false)
      window.requestAnimationFrame(() => menuButtonRef.current?.focus())
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [isMobile, menuOpen])

  useEffect(() => {
    const isPlayer = location.pathname.startsWith('/giocatori/') && location.pathname !== '/giocatori/'
    const title = isPlayer ? 'Profilo giocatore' : pageTitles[location.pathname] || 'Palworld Server Observatory'
    document.title = title === 'Palworld Server Observatory' ? title : `${title} · Palworld Server Observatory`
    setMenuOpen(false)
    const main = mainRef.current
    if (main && typeof main.scrollTo === 'function') main.scrollTo({ top: 0 })
    window.requestAnimationFrame(() => main?.focus({ preventScroll: true }))
  }, [location.pathname])

  const toggleMenu = () => {
    if (menuOpen) {
      setMenuOpen(false)
      window.requestAnimationFrame(() => menuButtonRef.current?.focus())
      return
    }
    setMenuOpen(true)
    window.requestAnimationFrame(() => sidebarRef.current?.querySelector<HTMLElement>('a')?.focus())
  }

  return (
    <SessionContext value={session.data}>
      <ServerContext value={server}>
        <div className="dashboard-root">
          <a className="skip-link" href="#main-content">
            Vai al contenuto
          </a>
          <div className="cartographic-grid" aria-hidden="true" />
          <header className="dash-topbar">
            <NavLink to="/" className="dash-brand" aria-label="Palworld Server Observatory">
              <span className="brand-radar">
                <i />
              </span>
              <span>
                <strong>PALWORLD</strong>
                <small>SERVER OBSERVATORY</small>
              </span>
            </NavLink>
            <div className="topbar-signal">
              <StatusBadge online={Boolean(server.data?.status.online)} stale={Boolean(server.data?.status.stale)} />
              <span>{server.error ? 'SEGNALE ASSENTE' : server.loading ? 'SINCRONIZZAZIONE' : 'STATO SERVER'}</span>
            </div>
            <button
              ref={menuButtonRef}
              type="button"
              className="nav-toggle"
              aria-label={menuOpen ? 'Chiudi menu' : 'Apri menu'}
              aria-expanded={menuOpen}
              aria-controls="dashboard-navigation"
              onClick={toggleMenu}
            >
              {menuOpen ? <IconX /> : <IconMenu2 />}
            </button>
          </header>

          <aside
            ref={sidebarRef}
            id="dashboard-navigation"
            className={`dash-sidebar ${menuOpen ? 'open' : ''}`}
            aria-label="Navigazione principale"
            aria-hidden={isMobile && !menuOpen}
            inert={isMobile && !menuOpen}
          >
            <NavGroup label="Server" links={primary} onNavigate={() => setMenuOpen(false)} />
            <NavGroup label="Comunità" links={community} onNavigate={() => setMenuOpen(false)} />
            {sessionIsAdmin(session.data) ? (
              <nav className="nav-cluster" aria-label="Amministrazione">
                <span>AMMINISTRAZIONE</span>
                <NavLink to="/admin-panel/" onClick={() => setMenuOpen(false)}>
                  <IconShieldLock />
                  <b>Admin panel</b>
                  <IconChevronRight />
                </NavLink>
              </nav>
            ) : null}
            <div className="sidebar-account">
              <span>ACCOUNT</span>
              <strong>{session.data?.user?.username || 'Membro'}</strong>
              <a href={session.data?.routes?.profile || '/accounts/change-username/'}>Profilo</a>
              <a href={session.data?.routes?.password || '/accounts/password-change/'}>Password</a>
              {sessionIsAdmin(session.data) ? (
                <a href={session.data?.routes?.members || '/accounts/members/'}>Membri</a>
              ) : null}
              <form className="sidebar-logout" method="post" action="/accounts/logout/">
                <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
                <button type="submit">Esci</button>
              </form>
            </div>
            <label className="theme-select">
              <span>TEMA INTERFACCIA</span>
              <select
                value={theme}
                onChange={(event) =>
                  setTheme(themeIds.has(event.target.value) ? (event.target.value as ThemeId) : 'observatory')
                }
              >
                {themes.map(([id, label]) => (
                  <option value={id} key={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </aside>

          <main ref={mainRef} id="main-content" className="dash-main" tabIndex={-1}>
            <DataState
              loading={session.loading}
              error={session.error}
              onRetry={session.reload}
              hasData={Boolean(session.data)}
            >
              <Outlet />
            </DataState>
            <footer className="dash-footer">
              <span>PALWORLD SERVER OBSERVATORY · BUILD {session.data?.appVersion || '--'}</span>
              <span>
                <a href="/static/dashboard/THIRD_PARTY_NOTICES.txt">Licenze e crediti</a>
                {' · '}
                <a href={session.data?.routes?.terms || '/termini/'}>Condizioni d'uso e privacy</a>
              </span>
            </footer>
          </main>
        </div>
      </ServerContext>
    </SessionContext>
  )
}

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

function NavGroup({
  label,
  links,
  onNavigate
}: {
  label: string
  links: typeof primary | typeof community
  onNavigate: () => void
}) {
  return (
    <nav className="nav-cluster" aria-label={label}>
      <span>{label.toUpperCase()}</span>
      {links.map(([path, title, Icon]) => (
        <NavLink key={path} to={path} end={path === '/'} onClick={onNavigate}>
          <Icon aria-hidden="true" />
          <b>{title}</b>
          <IconChevronRight aria-hidden="true" />
        </NavLink>
      ))}
    </nav>
  )
}
