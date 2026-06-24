import { describe, it, expect, beforeEach } from 'vitest'
import {
  loaded,
  loadError,
  industryPresets,
  industryPresetIds,
  workflowEmployeeModIds,
  workflowEmployeeIds,
  employeeRegistryRules,
  clientModPolicies,
  workflowDelivery,
} from './hostConfigRefs'

describe('hostConfigRefs', () => {
  beforeEach(() => {
    // Reset all refs to default values
    loaded.value = false
    loadError.value = null
    industryPresets.value = {}
    industryPresetIds.value = []
    workflowEmployeeModIds.value = []
    workflowEmployeeIds.value = []
    employeeRegistryRules.value = null
    clientModPolicies.value = null
    workflowDelivery.value = 'monolith'
  })

  it('loaded is a ref initialized to false', () => {
    expect(loaded.value).toBe(false)
    loaded.value = true
    expect(loaded.value).toBe(true)
  })

  it('loadError is a ref initialized to null', () => {
    expect(loadError.value).toBeNull()
    loadError.value = 'failed to load'
    expect(loadError.value).toBe('failed to load')
  })

  it('industryPresets is a ref initialized to empty object', () => {
    expect(industryPresets.value).toEqual({})
    industryPresets.value = { retail: { id: 'retail' } as never }
    expect(industryPresets.value.retail).toBeDefined()
  })

  it('industryPresetIds is a ref initialized to empty array', () => {
    expect(industryPresetIds.value).toEqual([])
    industryPresetIds.value = ['retail', 'manufacturing']
    expect(industryPresetIds.value).toHaveLength(2)
  })

  it('workflowEmployeeModIds is a ref initialized to empty array', () => {
    expect(workflowEmployeeModIds.value).toEqual([])
    workflowEmployeeModIds.value = ['mod-1', 'mod-2']
    expect(workflowEmployeeModIds.value).toHaveLength(2)
  })

  it('workflowEmployeeIds is a ref initialized to empty array', () => {
    expect(workflowEmployeeIds.value).toEqual([])
    workflowEmployeeIds.value = ['emp-1', 'emp-2']
    expect(workflowEmployeeIds.value).toHaveLength(2)
  })

  it('employeeRegistryRules is a ref initialized to null', () => {
    expect(employeeRegistryRules.value).toBeNull()
    employeeRegistryRules.value = {
      workflow_employee_id_prefixes: ['xcagi-'],
    }
    expect(employeeRegistryRules.value?.workflow_employee_id_prefixes).toEqual(['xcagi-'])
  })

  it('clientModPolicies is a ref initialized to null', () => {
    expect(clientModPolicies.value).toBeNull()
    clientModPolicies.value = {
      client_primary_erp_mod_id: 'attendance-industry',
    }
    expect(clientModPolicies.value?.client_primary_erp_mod_id).toBe('attendance-industry')
  })

  it('workflowDelivery is a ref initialized to monolith', () => {
    expect(workflowDelivery.value).toBe('monolith')
    workflowDelivery.value = 'modular'
    expect(workflowDelivery.value).toBe('modular')
  })

  it('all refs are writable', () => {
    loaded.value = true
    loadError.value = 'test'
    industryPresets.value = { test: {} } as never
    industryPresetIds.value = ['test']
    workflowEmployeeModIds.value = ['test']
    workflowEmployeeIds.value = ['test']
    employeeRegistryRules.value = {}
    clientModPolicies.value = {}
    workflowDelivery.value = 'test'

    expect(loaded.value).toBe(true)
    expect(loadError.value).toBe('test')
    expect(industryPresets.value).toHaveProperty('test')
    expect(industryPresetIds.value).toEqual(['test'])
    expect(workflowEmployeeModIds.value).toEqual(['test'])
    expect(workflowEmployeeIds.value).toEqual(['test'])
    expect(employeeRegistryRules.value).toEqual({})
    expect(clientModPolicies.value).toEqual({})
    expect(workflowDelivery.value).toBe('test')
  })
})
