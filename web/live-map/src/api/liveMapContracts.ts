import { z } from 'zod'
import type { ObjectState, PlayerState, PublicConfig, WorldCatalogue, WorldObject } from '../types'

const mapKinds = [
  'bases',
  'workers',
  'companions',
  'wild-pals',
  'alpha-pals',
  'bosses',
  'bounties',
  'oil-rigs',
  'watchtowers',
  'waypoints',
  'dungeon-entrances',
  'effigies',
  'journals',
  'ancient-shrine-pickups',
  'npc-locations',
  'npcs'
] as const

const CatalogueMetadataSchema = z.object({
  gameVersion: z.string(),
  generator: z.string(),
  decoder: z.string()
})

const SameOriginUrlSchema = z.string().refine(
  (value) => {
    try {
      const url = new URL(value, window.location.href)
      return url.origin === window.location.origin && !url.username && !url.password
    } catch {
      return false
    }
  },
  { error: 'URL must use the current origin' }
)

const TileUrlTemplateSchema = SameOriginUrlSchema.refine(
  (value) => !value.includes('#') && ['{size}', '{x}', '{y}'].every((placeholder) => value.includes(placeholder)),
  { error: 'Tile URL template must contain size, x, and y placeholders before any fragment' }
)

const WorldObjectSchema = z.object({
  id: z.string(),
  kind: z.enum(mapKinds),
  name: z.string(),
  detail: z.string().optional(),
  baseId: z.string().optional(),
  guildKey: z.string().optional(),
  guildName: z.string().optional(),
  ownerId: z.string().optional(),
  level: z.number().optional(),
  x: z.number(),
  y: z.number(),
  z: z.number().optional(),
  rewards: z.array(z.object({ name: z.string(), count: z.number().int().nonnegative() })).optional(),
  map: z.string()
}) satisfies z.ZodType<WorldObject>

export const LiveMapConfigSchema = z.object({
  pollIntervalMs: z.number().positive(),
  worldPollIntervalMs: z.number().positive(),
  worldDataEnabled: z.boolean(),
  playerClaimsEnabled: z.boolean(),
  layers: z
    .array(
      z.object({
        id: z.string(),
        name: z.string(),
        imageUrl: SameOriginUrlSchema.optional(),
        bounds: z.tuple([z.number(), z.number(), z.number(), z.number()]),
        tilePyramid: z
          .object({
            tileSize: z.number().int().positive(),
            levels: z.array(z.number().int().positive()).min(1),
            urlTemplate: TileUrlTemplateSchema
          })
          .optional()
      })
    )
    .min(1),
  catalogueUrl: SameOriginUrlSchema,
  landmarks: z.array(WorldObjectSchema).default([]),
  landmarkCatalogue: CatalogueMetadataSchema,
  upstreamRevision: z.string().optional()
}) satisfies z.ZodType<PublicConfig>

export const LiveMapCatalogueSchema = CatalogueMetadataSchema.extend({
  locations: z.array(WorldObjectSchema).default([])
}) satisfies z.ZodType<WorldCatalogue>

const LiveMapPlayerSchema = z.object({
  id: z.string(),
  name: z.string(),
  level: z.number(),
  guildKey: z.string().optional(),
  guildName: z.string().optional(),
  online: z.boolean().default(true),
  lastSeenAt: z.string().optional(),
  captureTotal: z.number().optional(),
  uniquePalsCaptured: z.number().optional(),
  paldeckUnlocked: z.number().optional(),
  arenaRankPoints: z.number().optional(),
  fastTravelUnlocked: z.number().optional(),
  areasDiscovered: z.number().optional(),
  bossDefeats: z.number().optional(),
  towerDefeats: z.number().optional(),
  x: z.number(),
  y: z.number(),
  map: z.string()
})

export const LiveMapPlayersSchema = z
  .object({
    server: z.object({ name: z.string(), description: z.string().optional(), version: z.string().optional() }),
    metrics: z.object({
      currentPlayers: z.number(),
      maxPlayers: z.number(),
      serverFps: z.number(),
      serverFrameTime: z.number(),
      uptimeSeconds: z.number(),
      baseCount: z.number(),
      days: z.number()
    }),
    metricsAvailable: z.boolean(),
    metricsStale: z.boolean(),
    metricsUpdatedAt: z.string().optional(),
    connected: z.boolean(),
    stale: z.boolean(),
    lastSuccessAt: z.string().optional(),
    saveEnabled: z.boolean(),
    saveAvailable: z.boolean(),
    saveStale: z.boolean(),
    saveUpdatedAt: z.string().optional(),
    saveSnapshotAt: z.string().optional(),
    saveLastError: z.string().optional(),
    players: z.array(LiveMapPlayerSchema)
  })
  .strict() satisfies z.ZodType<PlayerState>

export const LiveMapObjectsSchema = z
  .object({
    enabled: z.boolean(),
    available: z.boolean(),
    stale: z.boolean(),
    unsupported: z.boolean(),
    truncated: z.boolean(),
    total: z.number(),
    updatedAt: z.string().optional(),
    lastError: z.string().optional(),
    objects: z.array(WorldObjectSchema)
  })
  .strict() satisfies z.ZodType<ObjectState>
