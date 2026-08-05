import type { z } from 'zod'
import type {
  HeatmapSchema,
  HistorySchema,
  LeaderboardSchema,
  PlayersSchema,
  ServerAccessSchema,
  SessionSchema
} from './contracts'
import type { components } from './schema'

type Expect<T extends true> = T
type AcceptedBy<Schema extends z.ZodType, ApiType> = ApiType extends z.output<Schema> ? true : false

export type SessionContractAcceptsOpenApi = Expect<AcceptedBy<typeof SessionSchema, components['schemas']['Session']>>
export type AccessContractAcceptsOpenApi = Expect<
  AcceptedBy<typeof ServerAccessSchema, components['schemas']['ServerAccess']>
>
export type HistoryContractAcceptsOpenApi = Expect<AcceptedBy<typeof HistorySchema, components['schemas']['History']>>
export type PlayersContractAcceptsOpenApi = Expect<
  AcceptedBy<typeof PlayersSchema, components['schemas']['PlayerArchive']>
>
export type LeaderboardContractAcceptsOpenApi = Expect<
  AcceptedBy<typeof LeaderboardSchema, components['schemas']['Leaderboard']>
>
export type HeatmapContractAcceptsOpenApi = Expect<
  AcceptedBy<typeof HeatmapSchema, components['schemas']['ActivityHeatmap']>
>
