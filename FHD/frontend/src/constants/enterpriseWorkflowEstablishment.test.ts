import { describe, it, expect } from 'vitest'
import {
  resolveEnterpriseOrgLayer,
  resolveEnterpriseOrgLayerForCatalogItem,
  normalizeEnterpriseOrgLayerId,
} from './enterpriseWorkflowEstablishment'

describe('enterpriseWorkflowEstablishment', () => {
  it('maps core workflow employees to four layers', () => {
    expect(resolveEnterpriseOrgLayer('label_print')).toBe('execution')
    expect(resolveEnterpriseOrgLayer('wechat_msg')).toBe('service')
    expect(resolveEnterpriseOrgLayer('lan_gate_ai')).toBe('tools')
  })

  it('accepts manifest enterprise_layer aliases', () => {
    expect(normalizeEnterpriseOrgLayerId('工具层')).toBe('tools')
    expect(normalizeEnterpriseOrgLayerId('management_layer')).toBe('management')
    expect(
      resolveEnterpriseOrgLayer('custom_emp', '测试', '', '服务层'),
    ).toBe('service')
  })

  it('infers catalog item layer from workflow_employees', () => {
    const layer = resolveEnterpriseOrgLayerForCatalogItem({
      id: 'xcagi-core-workflow-employees',
      workflow_employees: [{ id: 'label_print', label: '标签打印' }],
    })
    expect(layer?.id).toBe('execution')
    expect(layer?.label).toBe('执行层')
  })
})
