import { describe, it, expect } from 'vitest'
import { databaseLinkForEmployee } from './workflowEmployeeDatabaseLinks'

describe('workflowEmployeeDatabaseLinks functions', () => {
  describe('databaseLinkForEmployee', () => {
    it('returns label_print link for label_print empId', () => {
      const link = databaseLinkForEmployee('label_print')
      expect(link.empId).toBe('label_print')
      expect(link.routeName).toBe('print')
      expect(link.label).toContain('标签打印')
    })

    it('returns shipment_mgmt link for shipment_mgmt empId', () => {
      const link = databaseLinkForEmployee('shipment_mgmt')
      expect(link.empId).toBe('shipment_mgmt')
      expect(link.routeName).toBe('shipment-records')
      expect(link.label).toContain('出货记录')
    })

    it('returns receipt_confirm link for receipt_confirm empId', () => {
      const link = databaseLinkForEmployee('receipt_confirm')
      expect(link.empId).toBe('receipt_confirm')
      expect(link.routeName).toBe('customers')
    })

    it('returns wechat_msg link with query for wechat_msg empId', () => {
      const link = databaseLinkForEmployee('wechat_msg')
      expect(link.empId).toBe('wechat_msg')
      expect(link.routeName).toBe('data-sources')
      expect(link.query).toEqual({ source: 'wechat_local_db' })
    })

    it('returns wechat_phone link for wechat_phone empId', () => {
      const link = databaseLinkForEmployee('wechat_phone')
      expect(link.empId).toBe('wechat_phone')
      expect(link.routeName).toBe('chat')
    })

    it('returns real_phone link for real_phone empId', () => {
      const link = databaseLinkForEmployee('real_phone')
      expect(link.empId).toBe('real_phone')
      expect(link.routeName).toBe('chat')
    })

    it('returns fallback link for unknown empId', () => {
      const link = databaseLinkForEmployee('unknown-emp')
      expect(link.empId).toBe('unknown-emp')
      expect(link.routeName).toBe('chat')
      expect(link.label).toContain('智能对话')
    })

    it('returns fallback link for empty empId', () => {
      const link = databaseLinkForEmployee('')
      expect(link.empId).toBe('')
      expect(link.routeName).toBe('chat')
    })

    it('always returns an object with label and description', () => {
      const link = databaseLinkForEmployee('label_print')
      expect(typeof link.label).toBe('string')
      expect(link.label.length).toBeGreaterThan(0)
      expect(typeof link.description).toBe('string')
      expect(link.description.length).toBeGreaterThan(0)
    })

    it('fallback link has description about extension', () => {
      const link = databaseLinkForEmployee('custom-emp')
      expect(link.description).toContain('扩展')
    })
  })
})
