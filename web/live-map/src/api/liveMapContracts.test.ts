import { describe, expect, it } from 'vitest'
import { LiveMapConfigSchema } from './liveMapContracts'

const config = {
  pollIntervalMs: 20_000,
  worldPollIntervalMs: 15_000,
  worldDataEnabled: true,
  layers: [
    {
      id: 'palpagos',
      name: 'Palpagos',
      imageUrl: '/static/maps/palpagos.jpg',
      bounds: [100, 100, -100, -100]
    }
  ],
  catalogueUrl: '/api/v1/live-map/catalogue?v=test',
  landmarks: [],
  landmarkCatalogue: {
    gameVersion: '1.0.0',
    generator: 'test',
    decoder: 'test'
  }
}

describe('LiveMapConfigSchema', () => {
  it('accepts same-origin map assets', () => {
    expect(LiveMapConfigSchema.parse(config).catalogueUrl).toBe(config.catalogueUrl)
  })

  it('rejects cross-origin map assets', () => {
    expect(
      LiveMapConfigSchema.safeParse({
        ...config,
        catalogueUrl: 'https://attacker.example/catalogue.json'
      }).success
    ).toBe(false)
    expect(
      LiveMapConfigSchema.safeParse({
        ...config,
        layers: [{ ...config.layers[0], imageUrl: '//attacker.example/map.jpg' }]
      }).success
    ).toBe(false)
  })
})
