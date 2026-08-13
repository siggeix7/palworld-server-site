import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashboardApp } from './DashboardApp'

const session = {
  authenticated: true,
  user: { username: 'luke', email: 'luke@example.test' },
  siteAdmin: true,
  appVersion: 'test',
  routes: {
    terms: '/termini/',
    profile: '/accounts/username/',
    password: '/accounts/password/change/',
    members: '/accounts/members/',
    admin: '/admin-panel/'
  }
}

const snapshot = {
  status: {
    online: true,
    reachable: true,
    stale: false,
    data_age_seconds: 2,
    last_updated: '2026-08-05T12:00:00Z',
    started_at: '2026-08-05T10:00:00Z'
  },
  info: { servername: 'Test Palpagos', description: 'Server di test', version: '1.0' },
  metrics: { currentplayernum: 1, maxplayernum: 32, serverfps: 60, uptime: 7200, days: 10, basecampnum: 2 },
  players: [
    {
      id: '0123456789abcdef01234567',
      name: 'Luke',
      accountName: 'steam',
      level: 55,
      ping: 32,
      building_count: 10,
      location_x: 12,
      location_y: 34,
      location_available: true,
      session: { current_session: 600, online_7d: 3600 }
    }
  ],
  settings: { ExpRate: 2, bIsPvP: false },
  events: [{ type: 'join', player: 'Luke', player_id: 'p1', timestamp: '2026-08-05T11:50:00Z' }],
  summary_24h: { peak_players: 3, average_players: 1.5, average_fps: 59.5, minimum_fps: 51 },
  version: 'test'
}

const responses: Record<string, unknown> = {
  '/api/v1/session': session,
  '/api/v1/snapshot': snapshot,
  '/api/v1/server/access': {
    host: 'pal.example.test',
    port: '8211',
    password: 'secret',
    address: 'pal.example.test:8211',
    configured: true
  },
  '/api/v1/history': {
    range: '24h',
    window: { from: '2026-08-04T12:00:00Z', to: '2026-08-05T12:00:00Z' },
    fps_health: {
      state: 'ok',
      label: 'Regolare',
      score: 95,
      sample_count: 2,
      median_fps: 59.5,
      recent_median_fps: 60,
      average_fps: 59.5,
      under_30_percent: 0,
      longest_dip_seconds: 0,
      coverage_seconds: 3600,
      newest_sample_age_seconds: 60,
      nominal_cadence_seconds: 60,
      gap_threshold_seconds: 180,
      components: {}
    },
    samples: [
      {
        timestamp: '2026-08-05T10:00:00Z',
        fps: 59,
        fps_average: 59,
        frame_time: 16,
        players: 1,
        max_players: 32,
        bases: 2,
        gap_before: false
      },
      {
        timestamp: '2026-08-05T11:00:00Z',
        fps: 60,
        fps_average: 60,
        frame_time: 16,
        players: 2,
        max_players: 32,
        bases: 2,
        gap_before: false
      }
    ]
  },
  '/api/v1/telemetry/stats': {
    generated_at: '2026-08-05T12:00:00Z',
    data_age_threshold_seconds: 180,
    uptime: { pct_24h: 99, pct_7d: 98, gaps_24h: [], gap_count_24h: 0 },
    fps: { mean_24h: 59, min_24h: 50, max_24h: 60, stability_cv_24h: 0.03, average_24h: 59 },
    players: { average_24h: 1.5, peak_24h: 3 },
    world: { day: 10, uptime_seconds: 7200 }
  },
  '/api/v1/players': {
    generated_at: '2026-08-05T12:00:00Z',
    windows: { month_days: 30, year_days: 365 },
    save_updated_at: null,
    players: [
      {
        id: '0123456789abcdef01234567',
        name: 'Luke',
        accountName: 'steam',
        level: 55,
        building_count: 10,
        first_seen: '2026-01-01T10:00:00Z',
        last_seen: '2026-08-05T12:00:00Z',
        online: true,
        session_count: 4,
        minutes_30d: 300,
        minutes_365d: 800,
        minutes_all: 900,
        average_session_minutes: 100,
        longest_session_minutes: 200,
        active_days_30d: 4,
        save_available: false,
        save_only: false,
        exp: null,
        owned_pal_count: null,
        unused_status_points: null,
        status_points: {},
        guild_name: '',
        is_guild_admin: false,
        ping_7d: null,
        periods: []
      }
    ]
  },
  '/api/v1/player/0123456789abcdef01234567': {
    player: {
      public_id: '0123456789abcdef01234567',
      name: 'Luke',
      account_name: 'steam',
      level: 55,
      building_count: 10,
      first_seen: '2026-01-01T10:00:00Z',
      last_seen: '2026-08-05T12:00:00Z',
      online: true,
      current_session: 600,
      minutes_lifetime: 900,
      session_count_lifetime: 4,
      longest_session_minutes: 200
    },
    sessions: [],
    ping: [
      { timestamp: '2026-08-05T10:00:00Z', ping: 20 },
      { timestamp: '2026-08-05T11:00:00Z', ping: 40 }
    ],
    presence: {
      weeks: 8,
      rows: 7,
      cols: 24,
      grid: Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0))
    },
    events: [],
    generated_at: '2026-08-05T12:00:00Z'
  },
  '/api/v1/world/diff': {
    generated_at: '2026-08-05T12:00:00Z',
    diffs: [{ key: 'ExpRate', vanilla: 1, current: 2 }],
    total: 1,
    has_settings: true
  },
  '/api/v1/guild/data': {
    schema_version: 3,
    guilds: [
      {
        group_id: 'guild',
        guild_name: 'Cartografi',
        players: [{ player_name: 'Luke', is_admin: true }],
        base_count: 1,
        pal_count: 2,
        worker_count: 2,
        working_count: 2,
        problem_worker_count: 0
      }
    ],
    bases: [
      {
        base_id: 'base',
        group_id: 'guild',
        name: 'Osservatorio',
        worker_count: 2,
        working_count: 2,
        problem_worker_count: 0,
        raid_active: false
      }
    ],
    world: {},
    updated_at: '2026-08-05T12:00:00Z',
    stale: false,
    alerts: []
  },
  '/api/v1/leaderboard': {
    generated_at: '2026-08-05T12:00:00Z',
    windows: { month_days: 30, year_days: 365 },
    by_playtime: { '30d': [], '365d': [], all: [] },
    by_level: [],
    total_players: 0
  },
  '/api/v1/activity/heatmap': {
    generated_at: '2026-08-05T12:00:00Z',
    range: '30d',
    weekday_labels: ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'],
    grid: Array.from({ length: 7 }, (_, day) =>
      Array.from({ length: 24 }, (_, hour) => (day === 0 && hour === 12 ? 45 : 0))
    ),
    hour_totals: Array.from({ length: 24 }, (_, hour) => (hour === 12 ? 45 : 0)),
    day_totals: [45, 0, 0, 0, 0, 0, 0],
    peak_hour: 12,
    peak_day: 'Lun',
    session_count: 1,
    total_minutes: 45
  },
  '/api/v1/palworld/players': { available: true, stale: false, generated_at: '2026-08-05T12:00:00Z', players: [] },
  '/api/v1/admin/player-ips': { players: [] },
  '/api/v1/palworld/info': { available: true, generated_at: '2026-08-05T12:00:00Z', stale: false, servername: 'Test' },
  '/api/v1/admin/weekly-report-schedule': {
    enabled: true,
    weekday: 0,
    time: '08:00',
    timezone: 'Europe/Rome',
    next_run_at: '2026-08-10T06:00:00Z',
    last_run: { scheduled_for: null, started_at: null, finished_at: null, status: 'never', error: null },
    updated_at: '2026-08-05T12:00:00Z'
  },
  '/api/v1/palworld/admin/players': { players: [] }
}

function mockApi(overrides: Record<string, unknown> = {}) {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      window.location.origin
    )
    const body = Object.hasOwn(overrides, url.pathname) ? overrides[url.pathname] : responses[url.pathname]
    return body === undefined
      ? new Response(JSON.stringify({ error: 'not found' }), { status: 404 })
      : new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  window.history.replaceState({}, '', '/')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('dashboard router and shell', () => {
  it('renders the home route and admin-aware shell navigation', async () => {
    mockApi()
    render(<DashboardApp />)

    expect(await screen.findByRole('heading', { name: 'Test Palpagos' }, { timeout: 5000 })).toBeVisible()
    expect(screen.getByRole('navigation', { name: 'Amministrazione' })).toBeVisible()
    expect(screen.getByRole('link', { name: /Admin panel/ })).toHaveAttribute('href', '/admin-panel/')
    expect(screen.getByRole('link', { name: 'Profilo' })).toHaveAttribute('href', '/accounts/username/')
  })

  it('loads a deep-linked feature without fetching inactive routes', async () => {
    window.history.pushState({}, '', '/accesso/')
    const fetchMock = mockApi()
    render(<DashboardApp />)

    expect(await screen.findByRole('heading', { name: 'Entra nel server' })).toBeVisible()
    await waitFor(() => expect(screen.getByText('pal.example.test')).toBeVisible())
    const paths = fetchMock.mock.calls.map(([input]) => new URL(String(input), window.location.origin).pathname)
    expect(paths).toContain('/api/v1/session')
    expect(paths).toContain('/api/v1/server/access')
    expect(paths).toContain('/api/v1/snapshot')
    expect(paths).not.toContain('/api/v1/history')
    expect(paths).not.toContain('/api/v1/players')
  })

  it('unmounts the dashboard context cleanly when navigating to the map', async () => {
    mockApi()
    const user = userEvent.setup()
    render(<DashboardApp />)

    expect(await screen.findByRole('heading', { name: 'Test Palpagos' })).toBeVisible()
    await user.click(within(screen.getByRole('navigation', { name: 'Server' })).getByRole('link', { name: /Mappa/ }))

    expect(await screen.findByRole('button', { name: 'Retry' })).toBeVisible()
    expect(window.location.pathname).toBe('/mappa/')
    expect(screen.queryByText('Il pannello non può essere visualizzato')).not.toBeInTheDocument()
  })

  it.each([
    ['/telemetria/', 'Telemetria'],
    ['/giocatori/', 'Giocatori'],
    ['/giocatori/0123456789abcdef01234567/', 'Luke'],
    ['/mondo/', 'Mondo'],
    ['/attivita/', 'Attività'],
    ['/classifica/', 'Classifica'],
    ['/orari/', 'Orari di punta'],
    ['/gilde/', 'Gilde'],
    ['/admin-panel/', 'Admin']
  ])('smoke route %s', async (path, heading) => {
    window.history.pushState({}, '', path)
    mockApi()
    render(<DashboardApp />)
    expect(await screen.findByRole('heading', { name: heading, level: 1 })).toBeVisible()
  })

  it('persists a selected visual theme', async () => {
    mockApi()
    render(<DashboardApp />)
    const selector = await screen.findByLabelText('TEMA INTERFACCIA')
    selector.dispatchEvent(new Event('change', { bubbles: true }))
    await waitFor(() => expect(window.localStorage.getItem('observatory.theme')).toBe('observatory'))
  })

  it('renders the live roster and numeric heatmap cells from validated snapshots', async () => {
    window.history.pushState({}, '', '/giocatori/')
    mockApi()
    const firstRender = render(<DashboardApp />)

    const roster = await waitFor(() => {
      const table = document.querySelector<HTMLElement>('.live-roster-table')
      expect(table).toBeInTheDocument()
      return table as HTMLElement
    })
    expect(within(roster).getByText('Luke')).toBeVisible()
    expect(within(roster).getByText('32 ms')).toBeVisible()
    firstRender.unmount()

    window.history.pushState({}, '', '/orari/')
    render(<DashboardApp />)
    const cell = await screen.findByRole('cell', { name: 'Lun, ore 12:00: 45 minuti' })
    expect(cell).toHaveTextContent('45')
    expect(cell.tagName).toBe('TD')
  })

  it('does not request admin resources before privileges are established', async () => {
    window.history.pushState({}, '', '/admin-panel/')
    const fetchMock = mockApi({
      '/api/v1/session': { ...session, siteAdmin: false, routes: { ...session.routes, members: null, admin: null } }
    })
    render(<DashboardApp />)

    expect(await screen.findByRole('heading', { name: 'Area amministrativa' })).toBeVisible()
    const paths = fetchMock.mock.calls.map(([input]) => new URL(String(input), window.location.origin).pathname)
    expect(paths).not.toContain('/api/v1/palworld/players')
    expect(paths).not.toContain('/api/v1/admin/player-ips')
    expect(paths).not.toContain('/api/v1/palworld/info')
    expect(paths).not.toContain('/api/v1/palworld/admin/players')
    expect(paths).not.toContain('/api/v1/admin/weekly-report-schedule')
    expect(paths).not.toContain('/api/v1/guild/data')
  })

  it('shows a dedicated 404 profile and reports the observed ping maximum', async () => {
    window.history.pushState({}, '', '/giocatori/0123456789abcdef01234567/')
    mockApi()
    const firstRender = render(<DashboardApp />)
    expect(await screen.findByText(/massimo osservato 40 ms/)).toBeVisible()
    firstRender.unmount()

    window.history.pushState({}, '', '/giocatori/missing-player/')
    mockApi()
    render(<DashboardApp />)
    expect(await screen.findByRole('heading', { name: 'Giocatore non trovato' })).toBeVisible()
    expect(screen.getByRole('link', { name: /Torna ai giocatori/ })).toHaveAttribute('href', '/giocatori/')
  })

  it('closes the mobile navigation with Escape and restores focus', async () => {
    const listeners = new Set<(event: MediaQueryListEvent) => void>()
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({
        matches: true,
        media: '(max-width: 760px)',
        onchange: null,
        addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
        removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
          listeners.delete(listener),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn()
      })
    )
    mockApi()
    const user = userEvent.setup()
    render(<DashboardApp />)

    const toggle = await screen.findByRole('button', { name: 'Apri menu' })
    const sidebar = document.querySelector<HTMLElement>('#dashboard-navigation')
    expect(sidebar).toHaveAttribute('inert')
    await user.click(toggle)
    expect(sidebar).not.toHaveAttribute('inert')
    await waitFor(() => expect(within(sidebar as HTMLElement).getByRole('link', { name: /Comando/ })).toHaveFocus())
    await user.keyboard('{Escape}')
    await waitFor(() => expect(toggle).toHaveFocus())
    expect(sidebar).toHaveAttribute('inert')
  })
})
