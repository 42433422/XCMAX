import { describe, it, expect } from 'vitest'
import {
  formatWorkDurationShort,
  totalWorkMs,
} from './useWorkflowEmployeeDesks'

describe('useWorkflowEmployeeDesks', () => {
  describe('formatWorkDurationShort', () => {
    it('returns 0m for non-finite values', () => {
      expect(formatWorkDurationShort(NaN)).toBe('0m')
      expect(formatWorkDurationShort(Infinity)).toBe('0m')
      expect(formatWorkDurationShort(-1)).toBe('0m')
      expect(formatWorkDurationShort(0)).toBe('0m')
    })

    it('returns seconds for less than 60 seconds', () => {
      expect(formatWorkDurationShort(1000)).toBe('1s')
      expect(formatWorkDurationShort(30000)).toBe('30s')
      expect(formatWorkDurationShort(59000)).toBe('59s')
    })

    it('returns minutes for less than 60 minutes', () => {
      expect(formatWorkDurationShort(60000)).toBe('1m')
      expect(formatWorkDurationShort(600000)).toBe('10m')
      expect(formatWorkDurationShort(3540000)).toBe('59m')
    })

    it('returns hours for less than 24 hours', () => {
      expect(formatWorkDurationShort(3600000)).toBe('1h')
      expect(formatWorkDurationShort(7200000)).toBe('2h')
    })

    it('returns hours with minutes', () => {
      expect(formatWorkDurationShort(9000000)).toBe('2h 30m')
    })

    it('returns days for 24+ hours', () => {
      expect(formatWorkDurationShort(86400000)).toBe('1d')
    })

    it('returns days with hours', () => {
      expect(formatWorkDurationShort(126000000)).toBe('1d 11h')
    })
  })

  describe('totalWorkMs', () => {
    it('returns 0 for undefined session', () => {
      expect(totalWorkMs(undefined, Date.now())).toBe(0)
    })

    it('returns lifetimeMs when no enabledAt', () => {
      expect(totalWorkMs({ lifetimeMs: 5000, enabledAt: null } as any, Date.now())).toBe(5000)
    })

    it('adds live duration to lifetimeMs', () => {
      const now = Date.now()
      const enabledAt = now - 10000
      const result = totalWorkMs({ lifetimeMs: 5000, enabledAt } as any, now)
      expect(result).toBe(15000)
    })

    it('clamps to 0 when enabledAt is in the future', () => {
      const now = Date.now()
      const enabledAt = now + 10000
      const result = totalWorkMs({ lifetimeMs: 5000, enabledAt } as any, now)
      expect(result).toBe(5000)
    })

    it('returns 0 when lifetimeMs is 0 and no enabledAt', () => {
      expect(totalWorkMs({ lifetimeMs: 0, enabledAt: null } as any, Date.now())).toBe(0)
    })
  })
})
