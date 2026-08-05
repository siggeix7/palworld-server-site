import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { App as LiveMap } from '../App'
import { AccessPage as Access } from '../features/access/AccessPage'
import { ActivityPage as Activity } from '../features/activity/ActivityPage'
import { AdminPage as Admin } from '../features/admin/AdminPage'
import { GuildsPage as Guilds } from '../features/guilds/GuildsPage'
import { HomePage as Home } from '../features/home/HomePage'
import { LeaderboardPage as Leaderboard } from '../features/leaderboard/LeaderboardPage'
import { PeakHoursPage as PeakHours } from '../features/peak-hours/PeakHoursPage'
import { PlayerPage as Player } from '../features/players/PlayerPage'
import { PlayersPage as Players } from '../features/players/PlayersPage'
import { TelemetryPage as Telemetry } from '../features/telemetry/TelemetryPage'
import { WorldPage as World } from '../features/world/WorldPage'
import { AppShell } from './AppShell'
import { ErrorBoundary } from './ErrorBoundary'

function MapRoute() {
  const navigate = useNavigate()
  return (
    <ErrorBoundary>
      <LiveMap onObservatoryNavigate={() => navigate('/')} />
    </ErrorBoundary>
  )
}

export function DashboardApp() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/mappa/" element={<MapRoute />} />
          <Route element={<AppShell />}>
            <Route index element={<Home />} />
            <Route path="telemetria/" element={<Telemetry />} />
            <Route path="giocatori/" element={<Players />} />
            <Route path="giocatori/:publicId/" element={<Player />} />
            <Route path="accesso/" element={<Access />} />
            <Route path="mondo/" element={<World />} />
            <Route path="attivita/" element={<Activity />} />
            <Route path="classifica/" element={<Leaderboard />} />
            <Route path="orari/" element={<PeakHours />} />
            <Route path="gilde/" element={<Guilds />} />
            <Route path="admin-panel/" element={<Admin />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
