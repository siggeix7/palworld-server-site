import { requestJson } from './client'
import {
  AdminInfoSchema,
  AdminIpsSchema,
  AdminPlayersSchema,
  CommandPlayersSchema,
  GuildDataSchema,
  HeatmapSchema,
  HistorySchema,
  LeaderboardSchema,
  MutationResultSchema,
  PlayerDetailSchema,
  PlayersSchema,
  ServerAccessSchema,
  SessionSchema,
  SnapshotSchema,
  TelemetryStatsSchema,
  WorldDiffSchema
} from './contracts'

export const api = {
  session: (signal?: AbortSignal) => requestJson('/api/v1/session', SessionSchema, { signal }),
  access: (signal?: AbortSignal) => requestJson('/api/v1/server/access', ServerAccessSchema, { signal }),
  snapshot: (signal?: AbortSignal) => requestJson('/api/v1/snapshot', SnapshotSchema, { signal }),
  history: (range: string, signal?: AbortSignal) =>
    requestJson(`/api/v1/history?range=${encodeURIComponent(range)}`, HistorySchema, { signal }),
  players: (signal?: AbortSignal) => requestJson('/api/v1/players', PlayersSchema, { signal }),
  player: (id: string, signal?: AbortSignal) =>
    requestJson(`/api/v1/player/${encodeURIComponent(id)}`, PlayerDetailSchema, { signal }),
  leaderboard: (signal?: AbortSignal) => requestJson('/api/v1/leaderboard', LeaderboardSchema, { signal }),
  heatmap: (range: string, signal?: AbortSignal) =>
    requestJson(`/api/v1/activity/heatmap?range=${encodeURIComponent(range)}`, HeatmapSchema, { signal }),
  telemetryStats: (signal?: AbortSignal) => requestJson('/api/v1/telemetry/stats', TelemetryStatsSchema, { signal }),
  worldDiff: (signal?: AbortSignal) => requestJson('/api/v1/world/diff', WorldDiffSchema, { signal }),
  guilds: (signal?: AbortSignal) => requestJson('/api/v1/guild/data', GuildDataSchema, { signal }),
  adminPlayers: (signal?: AbortSignal) =>
    requestJson('/api/v1/palworld/players', AdminPlayersSchema, { signal, forbidden: 'home' }),
  adminIps: (signal?: AbortSignal) =>
    requestJson('/api/v1/admin/player-ips', AdminIpsSchema, { signal, forbidden: 'home' }),
  adminInfo: (signal?: AbortSignal) =>
    requestJson('/api/v1/palworld/info', AdminInfoSchema, { signal, forbidden: 'home' }),
  commandPlayers: (signal?: AbortSignal) =>
    requestJson('/api/v1/palworld/admin/players', CommandPlayersSchema, { signal, forbidden: 'home' }),
  announce: (message: string, signal?: AbortSignal) =>
    requestJson('/api/v1/palworld/announce', MutationResultSchema, {
      method: 'POST',
      json: { message },
      signal,
      forbidden: 'home'
    }),
  playerCommand: (action: 'kick' | 'ban' | 'unban', userid: string, signal?: AbortSignal) =>
    requestJson(`/api/v1/palworld/${action}`, MutationResultSchema, {
      method: 'POST',
      json: { userid },
      signal,
      forbidden: 'home'
    })
}
