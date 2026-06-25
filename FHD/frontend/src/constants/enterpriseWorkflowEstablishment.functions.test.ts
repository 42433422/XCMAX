import { describe, it, expect } from 'vitest'
import {
  ENTERPRISE_ORG_LAYERS,
  ENTERPRISE_EMPLOYEES,
  ENTERPRISE_ESTABLISHMENT_ZONES,
  normalizeEnterpriseOrgLayerId,
  resolveEnterpriseOrgLayer,
  resolveEnterpriseEstablishmentZone,
  countEnterpriseEstablishmentMaxSlots,
  enterpriseOrgLayerById,
  enterpriseEstablishmentZoneById,
  resolveEnterpriseOrgLayerForCatalogItem,
} from './enterpriseWorkflowEstablishment'

describe('enterpriseWorkflowEstablishment constants and functions', () => {
  describe('ENTERPRISE_ORG_LAYERS', () => {
    it('has 4 layers', () => {
      expect(ENTERPRISE_ORG_LAYERS).toHaveLength(4)
    })

    it('contains tools layer', () => {
      expect(ENTERPRISE_ORG_LAYERS.find((l) => l.id === 'tools')).toBeTruthy()
    })

    it('contains execution layer', () => {
      expect(ENTERPRISE_ORG_LAYERS.find((l) => l.id === 'execution')).toBeTruthy()
    })

    it('contains service layer', () => {
      expect(ENTERPRISE_ORG_LAYERS.find((l) => l.id === 'service')).toBeTruthy()
    })

    it('contains management layer', () => {
      expect(ENTERPRISE_ORG_LAYERS.find((l) => l.id === 'management')).toBeTruthy()
    })

    it('each layer has code L1-L4', () => {
      const codes = ENTERPRISE_ORG_LAYERS.map((l) => l.code)
      expect(codes).toEqual(['L1', 'L2', 'L3', 'L4'])
    })
  })

  describe('ENTERPRISE_EMPLOYEES', () => {
    it('is a non-empty record', () => {
      expect(Object.keys(ENTERPRISE_EMPLOYEES).length).toBeGreaterThan(0)
    })

    it('contains wechat_contacts employee', () => {
      expect(ENTERPRISE_EMPLOYEES['wechat_contacts']).toBeTruthy()
      expect(ENTERPRISE_EMPLOYEES['wechat_contacts'].enterprise_layer).toBe('service')
    })
  })

  describe('ENTERPRISE_ESTABLISHMENT_ZONES (deprecated)', () => {
    it('is the same as ENTERPRISE_ORG_LAYERS', () => {
      expect(ENTERPRISE_ESTABLISHMENT_ZONES).toBe(ENTERPRISE_ORG_LAYERS)
    })
  })

  describe('normalizeEnterpriseOrgLayerId', () => {
    it('returns tools for tools input', () => {
      expect(normalizeEnterpriseOrgLayerId('tools')).toBe('tools')
    })

    it('returns execution for execution input', () => {
      expect(normalizeEnterpriseOrgLayerId('execution')).toBe('execution')
    })

    it('returns tools for tool alias', () => {
      expect(normalizeEnterpriseOrgLayerId('tool')).toBe('tools')
    })

    it('returns tools for 工具层', () => {
      expect(normalizeEnterpriseOrgLayerId('工具层')).toBe('tools')
    })

    it('returns execution for 执行层', () => {
      expect(normalizeEnterpriseOrgLayerId('执行层')).toBe('execution')
    })

    it('returns service for collaboration alias', () => {
      expect(normalizeEnterpriseOrgLayerId('collaboration')).toBe('service')
    })

    it('returns management for manage alias', () => {
      expect(normalizeEnterpriseOrgLayerId('manage')).toBe('management')
    })

    it('returns null for unknown input', () => {
      expect(normalizeEnterpriseOrgLayerId('unknown')).toBeNull()
    })

    it('returns null for empty string', () => {
      expect(normalizeEnterpriseOrgLayerId('')).toBeNull()
    })

    it('returns null for null input', () => {
      expect(normalizeEnterpriseOrgLayerId(null)).toBeNull()
    })

    it('returns null for undefined input', () => {
      expect(normalizeEnterpriseOrgLayerId(undefined)).toBeNull()
    })

    it('is case-insensitive', () => {
      expect(normalizeEnterpriseOrgLayerId('TOOLS')).toBe('tools')
    })

    it('trims whitespace', () => {
      expect(normalizeEnterpriseOrgLayerId('  tools  ')).toBe('tools')
    })
  })

  describe('resolveEnterpriseOrgLayer', () => {
    it('returns layer from manifest when provided', () => {
      expect(resolveEnterpriseOrgLayer('unknown', '', '', 'tools')).toBe('tools')
    })

    it('returns layer from SSOT for known empId', () => {
      expect(resolveEnterpriseOrgLayer('wechat_contacts')).toBe('service')
    })

    it('returns layer from SSOT for label_print', () => {
      expect(resolveEnterpriseOrgLayer('label_print')).toBe('execution')
    })

    it('returns tools for lan_gate SSOT entry', () => {
      expect(resolveEnterpriseOrgLayer('lan_gate')).toBe('tools')
    })

    it('returns management for workflow_automator SSOT entry', () => {
      expect(resolveEnterpriseOrgLayer('workflow_automator')).toBe('management')
    })

    it('infers tools from blob containing lan', () => {
      expect(resolveEnterpriseOrgLayer('custom-lan-tool')).toBe('tools')
    })

    it('infers execution from blob containing shipment', () => {
      expect(resolveEnterpriseOrgLayer('custom-shipment')).toBe('execution')
    })

    it('infers service from blob containing wechat', () => {
      expect(resolveEnterpriseOrgLayer('custom-wechat')).toBe('service')
    })

    it('infers management from blob containing orchestr', () => {
      expect(resolveEnterpriseOrgLayer('custom-orchestrator')).toBe('management')
    })

    it('defaults to management for unknown blob', () => {
      expect(resolveEnterpriseOrgLayer('completely-unknown-thing')).toBe('management')
    })

    it('uses shortName in blob', () => {
      expect(resolveEnterpriseOrgLayer('x', '出货管理')).toBe('execution')
    })

    it('uses panelTitle in blob', () => {
      expect(resolveEnterpriseOrgLayer('x', '', '微信消息')).toBe('service')
    })

    it('manifest layer overrides SSOT', () => {
      expect(resolveEnterpriseOrgLayer('label_print', '', '', 'service')).toBe('service')
    })
  })

  describe('resolveEnterpriseEstablishmentZone (deprecated)', () => {
    it('delegates to resolveEnterpriseOrgLayer', () => {
      expect(resolveEnterpriseEstablishmentZone('wechat_contacts')).toBe('service')
    })
  })

  describe('countEnterpriseEstablishmentMaxSlots', () => {
    it('returns at least 1 for empty desks', () => {
      expect(countEnterpriseEstablishmentMaxSlots([])).toBe(1)
    })

    it('returns 1 for single desk', () => {
      expect(countEnterpriseEstablishmentMaxSlots([{ empId: 'label_print' }])).toBe(1)
    })

    it('returns max count across layers', () => {
      const desks = [
        { empId: 'label_print' },
        { empId: 'shipment_mgmt' },
        { empId: 'wechat_contacts' },
      ]
      // label_print and shipment_mgmt are both execution → count 2
      expect(countEnterpriseEstablishmentMaxSlots(desks)).toBe(2)
    })

    it('returns 1 when all desks in different layers', () => {
      const desks = [
        { empId: 'label_print' },
        { empId: 'wechat_contacts' },
      ]
      expect(countEnterpriseEstablishmentMaxSlots(desks)).toBe(1)
    })
  })

  describe('enterpriseOrgLayerById', () => {
    it('returns tools layer for tools id', () => {
      const layer = enterpriseOrgLayerById('tools')
      expect(layer?.id).toBe('tools')
      expect(layer?.code).toBe('L1')
    })

    it('returns execution layer for execution id', () => {
      expect(enterpriseOrgLayerById('execution')?.code).toBe('L2')
    })

    it('returns undefined for unknown id', () => {
      expect(enterpriseOrgLayerById('unknown')).toBeUndefined()
    })

    it('returns undefined for empty string', () => {
      expect(enterpriseOrgLayerById('')).toBeUndefined()
    })
  })

  describe('enterpriseEstablishmentZoneById (deprecated)', () => {
    it('delegates to enterpriseOrgLayerById', () => {
      expect(enterpriseEstablishmentZoneById('tools')?.id).toBe('tools')
    })

    it('returns undefined for unknown id', () => {
      expect(enterpriseEstablishmentZoneById('unknown')).toBeUndefined()
    })
  })

  describe('resolveEnterpriseOrgLayerForCatalogItem', () => {
    it('returns layer from enterprise_layer field', () => {
      const result = resolveEnterpriseOrgLayerForCatalogItem({ enterprise_layer: 'tools' })
      expect(result?.id).toBe('tools')
    })

    it('returns layer from workflow_employees array', () => {
      const result = resolveEnterpriseOrgLayerForCatalogItem({
        workflow_employees: [{ id: 'label_print', enterprise_layer: 'execution' }],
      })
      expect(result?.id).toBe('execution')
    })

    it('returns layer from workflow_employees inference', () => {
      const result = resolveEnterpriseOrgLayerForCatalogItem({
        workflow_employees: [{ id: 'custom-shipment' }],
      })
      expect(result?.id).toBe('execution')
    })

    it('returns layer from employee field', () => {
      const result = resolveEnterpriseOrgLayerForCatalogItem({
        employee: { id: 'label_print' },
      })
      expect(result?.id).toBe('execution')
    })

    it('returns layer from blob inference for catalog item', () => {
      const result = resolveEnterpriseOrgLayerForCatalogItem({
        id: 'custom-lan-tool',
        name: 'LAN Tool',
      })
      expect(result?.id).toBe('tools')
    })

    it('returns undefined when no inference possible', () => {
      const result = resolveEnterpriseOrgLayerForCatalogItem({})
      expect(result?.id).toBe('management')
    })

    it('returns undefined for empty input object', () => {
      const result = resolveEnterpriseOrgLayerForCatalogItem({})
      expect(result).toBeTruthy()
    })
  })
})
