import { z } from 'zod'

const dateValue = z.string().nullable()
const optionalNumber = z.number().nullable().optional()
const value = z.union([
  z.string(),
  z.number(),
  z.boolean(),
  z.null(),
  z.array(z.unknown()),
  z.record(z.string(), z.unknown())
])

export const SessionSchema = z
  .object({
    authenticated: z.boolean(),
    user: z.object({ username: z.string(), email: z.string() }).strict().nullable(),
    siteAdmin: z.boolean(),
    appVersion: z.string(),
    routes: z
      .object({
        terms: z.string(),
        profile: z.string(),
        password: z.string(),
        members: z.string().nullable(),
        admin: z.string().nullable()
      })
      .strict()
  })
  .strict()

export const ServerAccessSchema = z
  .object({
    host: z.string(),
    port: z.string(),
    password: z.string(),
    address: z.string(),
    configured: z.boolean()
  })
  .strict()

export const EventSchema = z.object({
  type: z.enum(['join', 'leave']),
  player: z.string().optional(),
  player_id: z.string().optional(),
  timestamp: z.string()
})

export const LivePlayerSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    accountName: z.string().optional().default(''),
    level: z.number().default(0),
    ping: optionalNumber,
    building_count: z.number().default(0),
    location_x: optionalNumber,
    location_y: optionalNumber,
    location_available: z.boolean().optional(),
    session: z
      .object({
        current_session: optionalNumber,
        online_7d: optionalNumber
      })
      .optional()
  })
  .passthrough()

export const SnapshotSchema = z.object({
  status: z
    .object({
      online: z.boolean().default(false),
      reachable: z.boolean().default(false),
      stale: z.boolean().default(true),
      data_age_seconds: optionalNumber,
      players_stale: z.boolean().optional(),
      last_updated: dateValue.optional(),
      started_at: dateValue.optional()
    })
    .passthrough(),
  info: z
    .object({
      servername: z.string().optional(),
      description: z.string().optional(),
      version: z.string().optional()
    })
    .passthrough()
    .default({}),
  metrics: z.record(z.string(), value).default({}),
  players: z.array(LivePlayerSchema).default([]),
  settings: z.record(z.string(), value).default({}),
  events: z.array(EventSchema).default([]),
  summary_24h: z
    .object({
      peak_players: z.number().default(0),
      average_players: z.number().default(0),
      average_fps: z.number().default(0),
      minimum_fps: z.number().default(0)
    })
    .default({ peak_players: 0, average_players: 0, average_fps: 0, minimum_fps: 0 }),
  version: z.string().optional()
})

const HealthSchema = z
  .object({
    state: z.enum(['no_data', 'calibrating', 'stale', 'ok']),
    label: z.string(),
    score: z.number().nullable(),
    sample_count: z.number(),
    median_fps: optionalNumber,
    recent_median_fps: optionalNumber,
    average_fps: optionalNumber,
    under_30_percent: optionalNumber,
    longest_dip_seconds: optionalNumber,
    coverage_seconds: optionalNumber,
    newest_sample_age_seconds: optionalNumber,
    nominal_cadence_seconds: optionalNumber,
    gap_threshold_seconds: optionalNumber,
    components: z.record(z.string(), z.number()).optional()
  })
  .strict()

export const HistorySchema = z.object({
  range: z.string(),
  window: z.object({ from: z.string(), to: z.string() }),
  fps_health: HealthSchema,
  samples: z.array(
    z.object({
      timestamp: z.string(),
      fps: z.number(),
      fps_average: z.number(),
      frame_time: z.number(),
      players: z.number(),
      max_players: z.number(),
      bases: z.number(),
      gap_before: z.boolean().default(false)
    })
  )
})

const PeriodSchema = z.object({
  started_at: z.string(),
  ended_at: dateValue,
  active: z.boolean(),
  duration_minutes: z.number()
})

export const ArchivePlayerSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    accountName: z.string().default(''),
    level: z.number().default(0),
    building_count: z.number().default(0),
    first_seen: dateValue,
    last_seen: dateValue,
    online: z.boolean().default(false),
    session_count: z.number().default(0),
    minutes_30d: z.number().default(0),
    minutes_365d: z.number().default(0),
    minutes_all: z.number().default(0),
    average_session_minutes: z.number().default(0),
    longest_session_minutes: z.number().default(0),
    active_days_30d: z.number().default(0),
    save_available: z.boolean().default(false),
    save_only: z.boolean().default(false),
    exp: optionalNumber,
    owned_pal_count: optionalNumber,
    unused_status_points: optionalNumber,
    status_points: z.record(z.string(), z.number()).default({}),
    guild_name: z.string().default(''),
    is_guild_admin: z.boolean().default(false),
    ping_7d: z
      .object({ average: z.number(), minimum: z.number(), maximum: z.number(), sample_count: z.number() })
      .nullable()
      .optional(),
    periods: z.array(PeriodSchema).default([])
  })
  .passthrough()

export const PlayersSchema = z.object({
  generated_at: z.string(),
  windows: z.object({ month_days: z.number(), year_days: z.number() }),
  save_updated_at: dateValue,
  players: z.array(ArchivePlayerSchema).default([])
})

export const PlayerDetailSchema = z.object({
  player: z.object({
    public_id: z.string(),
    name: z.string(),
    account_name: z.string().default(''),
    level: z.number(),
    building_count: z.number(),
    first_seen: z.string(),
    last_seen: z.string(),
    online: z.boolean(),
    current_session: optionalNumber,
    minutes_lifetime: z.number(),
    session_count_lifetime: z.number(),
    longest_session_minutes: z.number()
  }),
  sessions: z.array(PeriodSchema),
  ping: z.array(z.object({ timestamp: z.string(), ping: z.number() })),
  presence: z.object({ weeks: z.number(), rows: z.number(), cols: z.number(), grid: z.array(z.array(z.number())) }),
  events: z.array(z.object({ type: z.enum(['join', 'leave']), timestamp: z.string() })),
  generated_at: z.string()
})

const LeaderboardEntrySchema = z.object({
  id: z.string(),
  name: z.string(),
  account_name: z.string().default(''),
  level: z.number(),
  first_seen: z.string(),
  last_seen: z.string(),
  online: z.boolean(),
  minutes_30d: z.number(),
  minutes_365d: z.number(),
  minutes_all: z.number()
})

export const LeaderboardSchema = z.object({
  generated_at: z.string(),
  windows: z.object({ month_days: z.number(), year_days: z.number() }),
  by_playtime: z.object({
    '30d': z.array(LeaderboardEntrySchema),
    '365d': z.array(LeaderboardEntrySchema),
    all: z.array(LeaderboardEntrySchema)
  }),
  by_level: z.array(LeaderboardEntrySchema),
  total_players: z.number()
})

export const HeatmapSchema = z.object({
  generated_at: z.string(),
  range: z.string(),
  weekday_labels: z.array(z.string()),
  grid: z.array(z.array(z.number())),
  hour_totals: z.array(z.number()),
  day_totals: z.array(z.number()),
  peak_hour: z.number().nullable(),
  peak_day: z.string().nullable(),
  session_count: z.number(),
  total_minutes: z.number()
})

export const TelemetryStatsSchema = z.object({
  generated_at: z.string(),
  uptime: z.object({
    pct_24h: z.number(),
    pct_7d: z.number(),
    gaps_24h: z.array(z.object({ from: z.string(), to: z.string(), seconds: z.number() })),
    gap_count_24h: z.number()
  }),
  fps: z.object({
    mean_24h: optionalNumber,
    min_24h: optionalNumber,
    max_24h: optionalNumber,
    stability_cv_24h: optionalNumber,
    average_24h: z.number()
  }),
  players: z.object({ average_24h: z.number(), peak_24h: z.number() }),
  world: z.object({ day: optionalNumber, uptime_seconds: optionalNumber }),
  data_age_threshold_seconds: z.number()
})

export const WorldDiffSchema = z.object({
  generated_at: z.string(),
  diffs: z.array(z.object({ key: z.string(), vanilla: value, current: value })),
  total: z.number(),
  has_settings: z.boolean()
})

const GuildPlayerSchema = z.object({ player_name: z.string(), is_admin: z.boolean() }).passthrough()
const GuildSchema = z
  .object({
    group_id: z.string(),
    guild_name: z.string().default(''),
    players: z.array(GuildPlayerSchema).default([]),
    base_count: z.number().optional(),
    pal_count: z.number().optional(),
    worker_count: z.number().optional(),
    working_count: z.number().optional(),
    problem_worker_count: z.number().optional()
  })
  .passthrough()
const BaseSchema = z
  .object({
    base_id: z.string(),
    group_id: z.string(),
    name: z.string().default(''),
    worker_count: z.number().optional(),
    working_count: z.number().optional(),
    problem_worker_count: z.number().optional(),
    raid_active: z.boolean().optional()
  })
  .passthrough()

export const GuildDataSchema = z.object({
  schema_version: z.number(),
  guilds: z.array(GuildSchema).default([]),
  bases: z.array(BaseSchema).default([]),
  world: z.record(z.string(), z.number()).default({}),
  updated_at: dateValue,
  stale: z.boolean(),
  alerts: z.array(z.object({ level: z.enum(['warning', 'danger']), title: z.string(), detail: z.string() })).optional()
})

export const AdminPlayersSchema = z.object({
  available: z.boolean(),
  stale: z.boolean(),
  generated_at: dateValue,
  players: z.array(LivePlayerSchema).default([])
})
export const AdminIpsSchema = z.object({
  players: z.array(
    z.object({
      name: z.string(),
      account_name: z.string().default(''),
      ip: z.string(),
      observed_at: dateValue,
      last_seen: z.string(),
      online: z.boolean()
    })
  )
})
export const AdminInfoSchema = z
  .object({ available: z.boolean(), generated_at: dateValue, stale: z.boolean() })
  .passthrough()
export const WeeklyReportScheduleSchema = z
  .object({
    enabled: z.boolean(),
    weekday: z.number().int().min(0).max(6),
    time: z.string().regex(/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/),
    timezone: z.string(),
    next_run_at: dateValue,
    last_run: z
      .object({
        scheduled_for: dateValue,
        started_at: dateValue,
        finished_at: dateValue,
        status: z.enum(['never', 'running', 'success', 'failed', 'interrupted']),
        error: z.string().nullable()
      })
      .strict(),
    updated_at: z.string()
  })
  .strict()
export const CommandPlayersSchema = z.object({
  players: z.array(
    z.object({
      userId: z.string(),
      name: z.string(),
      level: z.number(),
      ping: z.number(),
      location_x: z.number(),
      location_y: z.number()
    })
  )
})
export const MutationResultSchema = z.object({ ok: z.boolean() })

export type Session = z.infer<typeof SessionSchema>
export type Snapshot = z.infer<typeof SnapshotSchema>
export type History = z.infer<typeof HistorySchema>
export type ArchivePlayer = z.infer<typeof ArchivePlayerSchema>
export type PlayerDetail = z.infer<typeof PlayerDetailSchema>
export type GuildData = z.infer<typeof GuildDataSchema>
export type WeeklyReportSchedule = z.infer<typeof WeeklyReportScheduleSchema>
