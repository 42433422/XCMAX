import { describe, it, expect } from 'vitest'

import {
  AUTONOMY_L4_READINESS,
  overlayDeployGap,
  type AutonomyMaturityGap,
} from './autonomyL4Readiness'

const AUTO_DEPLOY_GAP_IDS = AUTONOMY_L4_READINESS.gaps.map((g) => g.id)
const AUTO_DEPLOY_GAP = AUTONOMY_L4_READINESS.gaps.find((g) => g.id === 'p0-auto-deploy')!

function buildGaps(over: Partial<AutonomyMaturityGap> = {}): AutonomyMaturityGap[] {
  return [
    { ...AUTO_DEPLOY_GAP, ...over },
    {
      id: 'p1-callback',
      severity: 'P1',
      title: 'Callback',
      status: 'blocked',
      impact: 'no callback',
      nextStep: 'wire ledger',
      ownerSurface: 'admin',
    },
  ]
}

describe('AUTONOMY_L4_READINESS', () => {
  it('targets L4 and exposes ordered maturity gaps', () => {
    expect(AUTONOMY_L4_READINESS.targetLevel).toBe('L4')
    expect(AUTONOMY_L4_READINESS.gaps.length).toBeGreaterThan(0)
    expect(AUTONOMY_L4_READINESS.steps.length).toBeGreaterThan(0)
    expect(AUTONOMY_L4_READINESS.l5StructuralGaps.length).toBeGreaterThan(0)
    for (const gap of AUTONOMY_L4_READINESS.gaps) {
      expect(['P0', 'P1', 'P2']).toContain(gap.severity)
      expect(['blocked', 'partial', 'ok', 'unknown']).toContain(gap.status)
      expect(typeof gap.impact).toBe('string')
      expect(typeof gap.nextStep).toBe('string')
    }
  })

  it('contains the p0-auto-deploy gap that overlay targets', () => {
    expect(AUTO_DEPLOY_GAP_IDS).toContain('p0-auto-deploy')
  })

  it('tracks callback / runtime-sync / implement-pack / metric-search gaps', () => {
    expect(AUTO_DEPLOY_GAP_IDS).toContain('p1-callback')
    expect(AUTO_DEPLOY_GAP_IDS).toContain('p1-runtime-sync')
    expect(AUTO_DEPLOY_GAP_IDS).toContain('p1-implement-pack')
    expect(AUTO_DEPLOY_GAP_IDS).toContain('p1-metric-search')
  })
})

describe('overlayDeployGap', () => {
  it('returns the same array length and preserves non-target gaps untouched', () => {
    const gaps = buildGaps()
    const out = overlayDeployGap(gaps, true)
    expect(out).toHaveLength(gaps.length)
    expect(out[1]).toEqual(gaps[1])
  })

  it('marks gap as partial when autoDispatchEnabled=true', () => {
    const out = overlayDeployGap(buildGaps(), true)
    const gap = out.find((g) => g.id === 'p0-auto-deploy')!
    expect(gap.status).toBe('partial')
    expect(gap.impact).toContain('AUTO_DISPATCH_DEPLOY')
  })

  it('marks gap as blocked when autoDispatchEnabled=false', () => {
    const out = overlayDeployGap(buildGaps(), false)
    const out2 = overlayDeployGap(buildGaps({ status: 'partial' }), false)
    expect(out.find((g) => g.id === 'p0-auto-deploy')!.status).toBe('blocked')
    expect(out2.find((g) => g.id === 'p0-auto-deploy')!.status).toBe('blocked')
  })

  it('leaves the gap unchanged when autoDispatchEnabled is null', () => {
    const gaps = buildGaps({ status: 'partial', impact: 'orig' })
    const out = overlayDeployGap(gaps, null)
    expect(out.find((g) => g.id === 'p0-auto-deploy')!.status).toBe('partial')
    expect(out.find((g) => g.id === 'p0-auto-deploy')!.impact).toBe('orig')
  })

  it('does not mutate the input array elements', () => {
    const gaps = buildGaps()
    const original = JSON.parse(JSON.stringify(gaps)) as AutonomyMaturityGap[]
    overlayDeployGap(gaps, true)
    expect(gaps).toEqual(original)
  })

  it('handles gaps without the auto-deploy id gracefully', () => {
    const gaps: AutonomyMaturityGap[] = [
      {
        id: 'other-gap',
        severity: 'P0',
        title: 'Other',
        status: 'blocked',
        impact: 'x',
        nextStep: 'y',
        ownerSurface: 'ci',
      },
    ]
    const out = overlayDeployGap(gaps, true)
    expect(out[0]).toEqual(gaps[0])
  })
})
