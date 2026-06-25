import { describe, it, expect } from 'vitest'
import {
  CORE_WORKFLOW_MOD_ID,
  CORE_WORKFLOW_EMPLOYEE_IDS,
  isCoreWorkflowModInstalled,
  isCoreWorkflowEmployeeId,
  coreWorkflowModEmployeesPath,
} from './coreWorkflowMod'

describe('coreWorkflowMod constants and functions', () => {
  describe('CORE_WORKFLOW_MOD_ID', () => {
    it('is the workflow visualization bridge mod id', () => {
      expect(CORE_WORKFLOW_MOD_ID).toBe('xcagi-workflow-visualization-bridge')
    })
  })

  describe('CORE_WORKFLOW_EMPLOYEE_IDS', () => {
    it('is a non-empty array', () => {
      expect(CORE_WORKFLOW_EMPLOYEE_IDS.length).toBeGreaterThan(0)
    })

    it('contains label_print', () => {
      expect(CORE_WORKFLOW_EMPLOYEE_IDS).toContain('label_print')
    })
  })

  describe('coreWorkflowModEmployeesPath', () => {
    it('returns the status path', () => {
      expect(coreWorkflowModEmployeesPath()).toBe('/api/mod/xcagi-workflow-visualization-bridge/status')
    })
  })

  describe('isCoreWorkflowEmployeeId', () => {
    it('returns true for label_print', () => {
      expect(isCoreWorkflowEmployeeId('label_print')).toBe(true)
    })

    it('returns false for unknown id', () => {
      expect(isCoreWorkflowEmployeeId('unknown')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isCoreWorkflowEmployeeId('')).toBe(false)
    })
  })

  describe('isCoreWorkflowModInstalled', () => {
    it('returns true when mods contain xcagi-workflow-visualization-bridge', () => {
      const mods = [{ id: 'xcagi-workflow-visualization-bridge' }]
      expect(isCoreWorkflowModInstalled(mods)).toBe(true)
    })

    it('returns true when mods contain xcagi-core-workflow-employees', () => {
      const mods = [{ id: 'xcagi-core-workflow-employees' }]
      expect(isCoreWorkflowModInstalled(mods)).toBe(true)
    })

    it('returns false when mods do not contain known ids', () => {
      const mods = [{ id: 'other-mod' }]
      expect(isCoreWorkflowModInstalled(mods)).toBe(false)
    })

    it('returns false for empty mods array', () => {
      expect(isCoreWorkflowModInstalled([])).toBe(false)
    })

    it('returns false for undefined input', () => {
      expect(isCoreWorkflowModInstalled(undefined)).toBe(false)
    })

    it('returns false for null input', () => {
      expect(isCoreWorkflowModInstalled(null)).toBe(false)
    })

    it('returns true when mod id has whitespace', () => {
      const mods = [{ id: '  xcagi-workflow-visualization-bridge  ' }]
      expect(isCoreWorkflowModInstalled(mods)).toBe(true)
    })

    it('returns false when mod id is empty string', () => {
      const mods = [{ id: '' }]
      expect(isCoreWorkflowModInstalled(mods)).toBe(false)
    })

    it('returns false when mod id is undefined', () => {
      const mods = [{}]
      expect(isCoreWorkflowModInstalled(mods)).toBe(false)
    })

    it('returns true when multiple mods include the bridge id', () => {
      const mods = [{ id: 'mod-a' }, { id: 'xcagi-core-workflow-employees' }, { id: 'mod-b' }]
      expect(isCoreWorkflowModInstalled(mods)).toBe(true)
    })
  })
})
