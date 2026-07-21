import { describe, it, expect, afterEach } from 'vitest'
import { checkBeforeAction, isEnabled, type Tier, type GateResult } from '../cross-tier-gate.js'

describe('cross-tier-gate', () => {
  describe('checkBeforeAction — fail-open', () => {
    it('allows when remoteState is null (query failed) — fail-open, no new SPOF', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', null)
      expect(result.allow).toBe(true)
      expect(result.reasons).toEqual(['remote_state unavailable, fail-open'])
    })

    it('allows when tier is desktop and remoteState is null regardless of action', () => {
      expect(checkBeforeAction('desktop', 'rollback_version', null).allow).toBe(true)
      expect(checkBeforeAction('desktop', 'clear_cache', null).allow).toBe(true)
    })

    it('allows when tier is server and remoteState is null', () => {
      expect(checkBeforeAction('server', 'rollback_to_last_tarball', null).allow).toBe(true)
    })

    it('allows when tier is ci and remoteState is null', () => {
      expect(checkBeforeAction('ci', 'cvm-push-release', null).allow).toBe(true)
    })
  })

  describe('checkBeforeAction — empty state', () => {
    it('allows when remoteState is empty object (desktop)', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', {})
      expect(result.allow).toBe(true)
      expect(result.reasons).toEqual([])
    })

    it('allows when remoteState is empty object (server)', () => {
      const result = checkBeforeAction('server', 'rollback_to_last_tarball', {})
      expect(result.allow).toBe(true)
    })

    it('allows when remoteState is empty object (ci)', () => {
      const result = checkBeforeAction('ci', 'cvm-push-release', {})
      expect(result.allow).toBe(true)
    })
  })

  describe('checkBeforeAction — desktop rollback_version', () => {
    it('denies when server_manifest_frozen=true', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', {
        server_manifest_frozen: true,
      })
      expect(result.allow).toBe(false)
      expect(result.reasons.length).toBe(1)
      expect(result.reasons[0]).toContain('服务器端 manifest 已冻结')
    })

    it('allows when server_manifest_frozen=false', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', {
        server_manifest_frozen: false,
      })
      expect(result.allow).toBe(true)
    })

    it('allows when server_manifest_frozen is missing (treated as false)', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', {
        other_field: 'value',
      })
      expect(result.allow).toBe(true)
    })

    it('allows for non-rollback_version actions even if server_manifest_frozen=true', () => {
      expect(
        checkBeforeAction('desktop', 'clear_cache', { server_manifest_frozen: true }).allow,
      ).toBe(true)
      expect(
        checkBeforeAction('desktop', 'restart_backend', { server_manifest_frozen: true }).allow,
      ).toBe(true)
    })

    it('does not trigger desktop rule for server tier even with same action', () => {
      const result = checkBeforeAction('server', 'rollback_version', {
        server_manifest_frozen: true,
      })
      expect(result.allow).toBe(true)
    })
  })

  describe('checkBeforeAction — server rollback_to_last_tarball', () => {
    it('denies when desktop_pending_rollback_marker=true', () => {
      const result = checkBeforeAction('server', 'rollback_to_last_tarball', {
        desktop_pending_rollback_marker: true,
      })
      expect(result.allow).toBe(false)
      expect(result.reasons.length).toBe(1)
      expect(result.reasons[0]).toContain('桌面端存在 pending rollback marker')
    })

    it('allows when desktop_pending_rollback_marker=false', () => {
      const result = checkBeforeAction('server', 'rollback_to_last_tarball', {
        desktop_pending_rollback_marker: false,
      })
      expect(result.allow).toBe(true)
    })

    it('allows for non-rollback_to_last_tarball actions', () => {
      expect(
        checkBeforeAction('server', 'restart_service', {
          desktop_pending_rollback_marker: true,
        }).allow,
      ).toBe(true)
    })

    it('does not trigger server rule for desktop tier even with same action', () => {
      const result = checkBeforeAction('desktop', 'rollback_to_last_tarball', {
        desktop_pending_rollback_marker: true,
      })
      expect(result.allow).toBe(true)
    })
  })

  describe('checkBeforeAction — ci cvm-push-release', () => {
    it('denies when server_manifest_frozen=true', () => {
      const result = checkBeforeAction('ci', 'cvm-push-release', {
        server_manifest_frozen: true,
      })
      expect(result.allow).toBe(false)
      expect(result.reasons.length).toBe(1)
      expect(result.reasons[0]).toContain('服务器端 manifest 已冻结')
    })

    it('allows when server_manifest_frozen=false', () => {
      const result = checkBeforeAction('ci', 'cvm-push-release', {
        server_manifest_frozen: false,
      })
      expect(result.allow).toBe(true)
    })

    it('allows for non-cvm-push-release actions', () => {
      expect(
        checkBeforeAction('ci', 'create_pr', { server_manifest_frozen: true }).allow,
      ).toBe(true)
    })
  })

  describe('checkBeforeAction — unmatched actions', () => {
    it('allows for unknown action types', () => {
      expect(checkBeforeAction('desktop', 'unknown_action', { server_manifest_frozen: true }).allow).toBe(true)
      expect(checkBeforeAction('server', 'unknown_action', { desktop_pending_rollback_marker: true }).allow).toBe(true)
      expect(checkBeforeAction('ci', 'unknown_action', { server_manifest_frozen: true }).allow).toBe(true)
    })

    it('allows for unknown tiers', () => {
      expect(checkBeforeAction('desktop' as Tier, 'rollback_version', { server_manifest_frozen: true }).allow).toBe(false)
    })
  })

  describe('GateResult shape', () => {
    it('returns reasons array (not undefined) when allowed', () => {
      const result: GateResult = checkBeforeAction('desktop', 'rollback_version', {})
      expect(Array.isArray(result.reasons)).toBe(true)
      expect(result.reasons).toEqual([])
    })

    it('returns non-empty reasons when denied', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', {
        server_manifest_frozen: true,
      })
      expect(result.reasons.length).toBeGreaterThan(0)
      expect(result.reasons.every(r => typeof r === 'string')).toBe(true)
    })
  })

  describe('isEnabled', () => {
    const ENV_KEY = 'XCAGI_CROSS_TIER_GATE'

    afterEach(() => {
      delete process.env[ENV_KEY]
    })

    it('returns true when env not set (default enabled, opt-out)', () => {
      delete process.env[ENV_KEY]
      expect(isEnabled()).toBe(true)
    })

    it('returns true when env is empty string', () => {
      process.env[ENV_KEY] = ''
      expect(isEnabled()).toBe(true)
    })

    it('returns true when env is "1"', () => {
      process.env[ENV_KEY] = '1'
      expect(isEnabled()).toBe(true)
    })

    it('returns true when env is "true"', () => {
      process.env[ENV_KEY] = 'true'
      expect(isEnabled()).toBe(true)
    })

    it('returns true when env is "yes"', () => {
      process.env[ENV_KEY] = 'yes'
      expect(isEnabled()).toBe(true)
    })

    it('returns true when env is "TRUE" (case-insensitive)', () => {
      process.env[ENV_KEY] = 'TRUE'
      expect(isEnabled()).toBe(true)
    })

    it('returns false when env is "0"', () => {
      process.env[ENV_KEY] = '0'
      expect(isEnabled()).toBe(false)
    })

    it('returns false when env is "false"', () => {
      process.env[ENV_KEY] = 'false'
      expect(isEnabled()).toBe(false)
    })

    it('returns false when env is "no"', () => {
      process.env[ENV_KEY] = 'no'
      expect(isEnabled()).toBe(false)
    })

    it('reflects env changes between calls', () => {
      delete process.env[ENV_KEY]
      expect(isEnabled()).toBe(true)
      process.env[ENV_KEY] = '0'
      expect(isEnabled()).toBe(false)
      delete process.env[ENV_KEY]
      expect(isEnabled()).toBe(true)
    })
  })
})
