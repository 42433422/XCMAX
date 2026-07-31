import { describe, it, expect, afterEach } from 'vitest'
import { checkBeforeAction, isEnabled, requiresRemoteState, type Tier, type GateResult } from '../cross-tier-gate.js'

describe('cross-tier-gate', () => {
  describe('checkBeforeAction — fail-closed', () => {
    it('denies when remoteState is null (query failed)', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', null)
      expect(result.allow).toBe(false)
      expect(result.reasons).toEqual(['remote_state unavailable, fail-closed'])
    })

    it('keeps checkBeforeAction fail-closed when it is explicitly invoked', () => {
      expect(checkBeforeAction('desktop', 'rollback_version', null).allow).toBe(false)
      expect(checkBeforeAction('desktop', 'clear_cache', null).allow).toBe(false)
    })

    it('denies when tier is server and remoteState is null', () => {
      expect(checkBeforeAction('server', 'rollback_to_last_tarball', null).allow).toBe(false)
    })

    it('denies when tier is ci and remoteState is null', () => {
      expect(checkBeforeAction('ci', 'cvm-push-release', null).allow).toBe(false)
    })
  })

  describe('checkBeforeAction — empty state', () => {
    it('allows when remoteState is empty object', () => {
      expect(checkBeforeAction('desktop', 'rollback_version', {}).allow).toBe(true)
      expect(checkBeforeAction('server', 'rollback_to_last_tarball', {}).allow).toBe(true)
      expect(checkBeforeAction('ci', 'cvm-push-release', {}).allow).toBe(true)
    })
  })

  describe('requiresRemoteState', () => {
    it('requires a remote snapshot only for cross-tier actions', () => {
      expect(requiresRemoteState('rollback_version')).toBe(true)
      expect(requiresRemoteState('rollback_to_last_tarball')).toBe(true)
      expect(requiresRemoteState('cvm-push-release')).toBe(true)
      expect(requiresRemoteState('clear_cache')).toBe(false)
      expect(requiresRemoteState('repair_config')).toBe(false)
      expect(requiresRemoteState('restart_backend')).toBe(false)
    })
  })

  describe('checkBeforeAction — desktop rollback_version', () => {
    it('denies when server_manifest_frozen=true', () => {
      const result = checkBeforeAction('desktop', 'rollback_version', {
        server_manifest_frozen: true,
      })
      expect(result.allow).toBe(false)
      expect(result.reasons[0]).toContain('服务器端 manifest 已冻结')
    })

    it('allows when server_manifest_frozen=false', () => {
      expect(
        checkBeforeAction('desktop', 'rollback_version', { server_manifest_frozen: false }).allow,
      ).toBe(true)
    })
  })

  describe('checkBeforeAction — server rollback_to_last_tarball', () => {
    it('denies when desktop_pending_rollback_marker=true', () => {
      const result = checkBeforeAction('server', 'rollback_to_last_tarball', {
        desktop_pending_rollback_marker: true,
      })
      expect(result.allow).toBe(false)
      expect(result.reasons[0]).toContain('桌面端存在 pending rollback marker')
    })
  })

  describe('checkBeforeAction — ci cvm-push-release', () => {
    it('denies when server_manifest_frozen=true', () => {
      const result = checkBeforeAction('ci', 'cvm-push-release', {
        server_manifest_frozen: true,
      })
      expect(result.allow).toBe(false)
      expect(result.reasons[0]).toContain('服务器端 manifest 已冻结')
    })
  })

  describe('GateResult shape', () => {
    it('returns reasons array when allowed', () => {
      const result: GateResult = checkBeforeAction('desktop', 'rollback_version', {})
      expect(result.reasons).toEqual([])
    })
  })

  describe('isEnabled', () => {
    const ENV_KEY = 'XCAGI_CROSS_TIER_GATE'

    afterEach(() => {
      delete process.env[ENV_KEY]
    })

    it('returns true when env not set (default enabled)', () => {
      delete process.env[ENV_KEY]
      expect(isEnabled()).toBe(true)
    })

    it('returns false when env is "0"', () => {
      process.env[ENV_KEY] = '0'
      expect(isEnabled()).toBe(false)
    })

    it('returns true when env is "1"', () => {
      process.env[ENV_KEY] = '1'
      expect(isEnabled()).toBe(true)
    })
  })
})
