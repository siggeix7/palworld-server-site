import { describe, expect, it } from 'vitest'
import type { History } from '../../api/contracts'
import { splitAtGaps } from './TelemetryChart'

describe('telemetry gap segmentation', () => {
  it('starts a new line segment after a collector gap', () => {
    const samples = [
      { timestamp: '2026-08-05T10:00:00Z', gap_before: false },
      { timestamp: '2026-08-05T10:01:00Z', gap_before: false },
      { timestamp: '2026-08-05T10:10:00Z', gap_before: true },
      { timestamp: '2026-08-05T10:11:00Z', gap_before: false }
    ] as History['samples']

    expect(splitAtGaps(samples).map((segment) => segment.map((sample) => sample.timestamp))).toEqual([
      ['2026-08-05T10:00:00Z', '2026-08-05T10:01:00Z'],
      ['2026-08-05T10:10:00Z', '2026-08-05T10:11:00Z']
    ])
  })
})
