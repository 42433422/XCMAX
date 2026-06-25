import { describe, it, expect, beforeEach } from 'vitest'
import {
  WORKFLOW_VIZ_BRIDGE_MOD_ID,
  LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED,
  LEGACY_CORE_WORKFLOW_MOD_ID,
  WORKFLOW_EMPLOYEE_MOD_IDS,
  WORKFLOW_EMPLOYEE_IDS,
  workflowVizModStatusPath,
  readWorkflowVizModPagesEnabled,
  setWorkflowVizModPagesEnabled,
  getWorkflowEmployeeModIds,
  getWorkflowEmployeeIds,
  isWorkflowEmployeeId,
} from './workflowEmployeeMods'
import { workflowEmployeeModIds, workflowEmployeeIds } from '@/stores/hostConfig'

describe('workflowEmployeeMods constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
    workflowEmployeeModIds.value = []
    workflowEmployeeIds.value = []
  })

  describe('WORKFLOW_VIZ_BRIDGE_MOD_ID', () => {
    it('is the workflow visualization bridge mod id', () => {
      expect(WORKFLOW_VIZ_BRIDGE_MOD_ID).toBe('xcagi-workflow-visualization-bridge')
    })
  })

  describe('LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED).toBe('xcagi_workflow_viz_mod_pages_enabled')
    })
  })

  describe('LEGACY_CORE_WORKFLOW_MOD_ID', () => {
    it('is the legacy core workflow mod id', () => {
      expect(LEGACY_CORE_WORKFLOW_MOD_ID).toBe('xcagi-core-workflow-employees')
    })
  })

  describe('WORKFLOW_EMPLOYEE_MOD_IDS', () => {
    it('is a non-empty array', () => {
      expect(WORKFLOW_EMPLOYEE_MOD_IDS.length).toBeGreaterThan(0)
    })

    it('contains label print mod id', () => {
      expect(WORKFLOW_EMPLOYEE_MOD_IDS).toContain('xcagi-workflow-employee-label-print')
    })
  })

  describe('WORKFLOW_EMPLOYEE_IDS', () => {
    it('is a non-empty array', () => {
      expect(WORKFLOW_EMPLOYEE_IDS.length).toBeGreaterThan(0)
    })

    it('contains label_print', () => {
      expect(WORKFLOW_EMPLOYEE_IDS).toContain('label_print')
    })

    it('contains 6 employee ids', () => {
      expect(WORKFLOW_EMPLOYEE_IDS).toHaveLength(6)
    })
  })

  describe('workflowVizModStatusPath', () => {
    it('returns the status path for the workflow viz bridge mod', () => {
      expect(workflowVizModStatusPath()).toBe('/api/mod/xcagi-workflow-visualization-bridge/status')
    })
  })

  describe('readWorkflowVizModPagesEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readWorkflowVizModPagesEnabled()).toBe(false)
    })

    it('returns false when value is 0', () => {
      localStorage.setItem(LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED, '0')
      expect(readWorkflowVizModPagesEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED, '1')
      expect(readWorkflowVizModPagesEnabled()).toBe(true)
    })

    it('returns false for arbitrary string', () => {
      localStorage.setItem(LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED, 'on')
      expect(readWorkflowVizModPagesEnabled()).toBe(false)
    })
  })

  describe('setWorkflowVizModPagesEnabled', () => {
    it('sets value to 1 when true', () => {
      setWorkflowVizModPagesEnabled(true)
      expect(localStorage.getItem(LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setWorkflowVizModPagesEnabled(false)
      expect(localStorage.getItem(LS_WORKFLOW_VIZ_MOD_PAGES_ENABLED)).toBe('0')
    })

    it('read reflects write', () => {
      setWorkflowVizModPagesEnabled(true)
      expect(readWorkflowVizModPagesEnabled()).toBe(true)
      setWorkflowVizModPagesEnabled(false)
      expect(readWorkflowVizModPagesEnabled()).toBe(false)
    })
  })

  describe('getWorkflowEmployeeModIds', () => {
    it('returns built-in mod ids when API provides none', () => {
      const result = getWorkflowEmployeeModIds()
      expect(result).toEqual(WORKFLOW_EMPLOYEE_MOD_IDS)
    })

    it('returns API-provided mod ids when available', () => {
      workflowEmployeeModIds.value = ['custom-mod-1', 'custom-mod-2']
      const result = getWorkflowEmployeeModIds()
      expect(result).toEqual(['custom-mod-1', 'custom-mod-2'])
    })
  })

  describe('getWorkflowEmployeeIds', () => {
    it('returns built-in employee ids when API provides none', () => {
      const result = getWorkflowEmployeeIds()
      expect(result).toEqual(WORKFLOW_EMPLOYEE_IDS)
    })

    it('returns API-provided employee ids when available', () => {
      workflowEmployeeIds.value = ['custom-emp-1', 'custom-emp-2']
      const result = getWorkflowEmployeeIds()
      expect(result).toEqual(['custom-emp-1', 'custom-emp-2'])
    })
  })

  describe('isWorkflowEmployeeId', () => {
    it('returns true for built-in label_print', () => {
      expect(isWorkflowEmployeeId('label_print')).toBe(true)
    })

    it('returns true for built-in shipment_mgmt', () => {
      expect(isWorkflowEmployeeId('shipment_mgmt')).toBe(true)
    })

    it('returns false for unknown id when using built-in list', () => {
      expect(isWorkflowEmployeeId('unknown-emp')).toBe(false)
    })

    it('returns true for API-provided id', () => {
      workflowEmployeeIds.value = ['custom-emp']
      expect(isWorkflowEmployeeId('custom-emp')).toBe(true)
    })

    it('returns false for built-in id when API overrides with different list', () => {
      workflowEmployeeIds.value = ['custom-emp']
      expect(isWorkflowEmployeeId('label_print')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isWorkflowEmployeeId('')).toBe(false)
    })
  })
})
