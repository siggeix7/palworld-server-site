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
      bounds: [100, 100, -100, -100],
      tilePyramid: {
        tileSize: 512,
        levels: [1024, 2048, 4096, 8192],
        urlTemplate: '/static/maps/palpagos-z{size}-x{x}-y{y}.webp?v=tiles'
      }
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
    const parsed = LiveMapConfigSchema.parse(config)
    expect(parsed.catalogueUrl).toBe(config.catalogueUrl)
    expect(parsed.layers[0].tilePyramid).toEqual(config.layers[0].tilePyramid)
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
    expect(
      LiveMapConfigSchema.safeParse({
        ...config,
        layers: [
          {
            ...config.layers[0],
            tilePyramid: {
              ...config.layers[0].tilePyramid,
              urlTemplate: 'https://attacker.example/map-z{size}-x{x}-y{y}.webp'
            }
          }
        ]
      }).success
    ).toBe(false)
  })

  it('rejects tile templates with fragments or missing placeholders', () => {
    for (const urlTemplate of ['/static/maps/map.webp#z={size}&x={x}&y={y}', '/static/maps/map-z{size}-x{x}.webp']) {
      expect(
        LiveMapConfigSchema.safeParse({
          ...config,
          layers: [
            {
              ...config.layers[0],
              tilePyramid: { ...config.layers[0].tilePyramid, urlTemplate }
            }
          ]
        }).success
      ).toBe(false)
    }
  })
})
