import { describe, it, expect, beforeEach } from 'vitest'
import {
  WORKFLOW_DOC_CORE_EMPLOYEE_IDS,
  WORKFLOW_DOC_FIXED_MOD_SERVICE_IDS,
  isWorkflowDocCoreEmployeeId,
  isWorkflowDocFixedModServiceId,
} from './workflowEmployeeDocIds'
import { WORKFLOW_EMPLOYEE_IDS } from './workflowEmployeeMods'

describe('workflowEmployeeDocIds constants and functions', () => {
  describe('WORKFLOW_DOC_CORE_EMPLOYEE_IDS', () => {
    it('contains the first 4 workflow employee ids', () => {
      expect(WORKFLOW_DOC_CORE_EMPLOYEE_IDS).toHaveLength(4)
    })

    it('contains label_print as first id', () => {
      expect(WORKFLOW_DOC_CORE_EMPLOYEE_IDS[0]).toBe('label_print')
    })

    it('contains shipment_mgmt as second id', () => {
      expect(WORKFLOW_DOC_CORE_EMPLOYEE_IDS[1]).toBe('shipment_mgmt')
    })

    it('contains receipt_confirm as third id', () => {
      expect(WORKFLOW_DOC_CORE_EMPLOYEE_IDS[2]).toBe('receipt_confirm')
    })

    it('contains wechat_msg as fourth id', () => {
      expect(WORKFLOW_DOC_CORE_EMPLOYEE_IDS[3]).toBe('wechat_msg')
    })

    it('is a slice of WORKFLOW_EMPLOYEE_IDS', () => {
      expect(WORKFLOW_DOC_CORE_EMPLOYEE_IDS).toEqual(WORKFLOW_EMPLOYEE_IDS.slice(0, 4))
    })
  })

  describe('WORKFLOW_DOC_FIXED_MOD_SERVICE_IDS', () => {
    it('contains the remaining workflow employee ids after the first 4', () => {
      expect(WORKFLOW_DOC_FIXED_MOD_SERVICE_IDS).toHaveLength(WORKFLOW_EMPLOYEE_IDS.length - 4)
    })

    it('contains wechat_phone', () => {
      expect(WORKFLOW_DOC_FIXED_MOD_SERVICE_IDS).toContain('wechat_phone')
    })

    it('contains real_phone', () => {
      expect(WORKFLOW_DOC_FIXED_MOD_SERVICE_IDS).toContain('real_phone')
    })

    it('is a slice of WORKFLOW_EMPLOYEE_IDS from index 4', () => {
      expect(WORKFLOW_DOC_FIXED_MOD_SERVICE_IDS).toEqual(WORKFLOW_EMPLOYEE_IDS.slice(4))
    })
  })

  describe('isWorkflowDocCoreEmployeeId', () => {
    it('returns true for label_print', () => {
      expect(isWorkflowDocCoreEmployeeId('label_print')).toBe(true)
    })

    it('returns true for shipment_mgmt', () => {
      expect(isWorkflowDocCoreEmployeeId('shipment_mgmt')).toBe(true)
    })

    it('returns true for receipt_confirm', () => {
      expect(isWorkflowDocCoreEmployeeId('receipt_confirm')).toBe(true)
    })

    it('returns true for wechat_msg', () => {
      expect(isWorkflowDocCoreEmployeeId('wechat_msg')).toBe(true)
    })

    it('returns false for wechat_phone (not in core)', () => {
      expect(isWorkflowDocCoreEmployeeId('wechat_phone')).toBe(false)
    })

    it('returns false for real_phone (not in core)', () => {
      expect(isWorkflowDocCoreEmployeeId('real_phone')).toBe(false)
    })

    it('returns false for unknown id', () => {
      expect(isWorkflowDocCoreEmployeeId('unknown')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isWorkflowDocCoreEmployeeId('')).toBe(false)
    })
  })

  describe('isWorkflowDocFixedModServiceId', () => {
    it('returns true for wechat_phone', () => {
      expect(isWorkflowDocFixedModServiceId('wechat_phone')).toBe(true)
    })

    it('returns true for real_phone', () => {
      expect(isWorkflowDocFixedModServiceId('real_phone')).toBe(true)
    })

    it('returns false for label_print (in core, not fixed mod)', () => {
      expect(isWorkflowDocFixedModServiceId('label_print')).toBe(false)
    })

    it('returns false for unknown id', () => {
      expect(isWorkflowDocFixedModServiceId('unknown')).toBe(false)
    })

    it('returns false for empty string', () => {
      expect(isWorkflowDocFixedModServiceId('')).toBe(false)
    })
  })
})
