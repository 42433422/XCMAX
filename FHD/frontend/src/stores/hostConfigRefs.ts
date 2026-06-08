/**
 * 宿主配置运行时状态（仅 ref，无 bootstrap）。
 * 与 industryPresets 常量分离，避免 hostConfig ↔ industryPresets 循环依赖。
 */
import { ref } from 'vue'
import type { IndustryPreset } from '@/types/industryPreset'

export type EmployeeRegistryRules = {
  workflow_employee_id_prefixes?: string[]
  exclude_id_suffixes?: string[]
  exclude_artifact_types?: string[]
  exclude_mod_ids?: string[]
  non_workflow_desk_employee_patterns?: string[]
}

export type WorkflowCatalogEntry = {
  mod_id: string
  employee_id: string
  label?: string
  panel_title?: string
  panel_summary?: string
}

export const loaded = ref(false)
export const loadError = ref<string | null>(null)
export const industryPresets = ref<Record<string, IndustryPreset>>({})
export const industryPresetIds = ref<string[]>([])
export const workflowEmployeeModIds = ref<string[]>([])
export const workflowEmployeeIds = ref<string[]>([])
export const employeeRegistryRules = ref<EmployeeRegistryRules | null>(null)
export const clientModPolicies = ref<{
  client_primary_erp_mod_id?: string
  suppress_generic_shell_mod_ids?: string[]
  protected_ids?: string[]
} | null>(null)
export const workflowDelivery = ref<string>('monolith')
