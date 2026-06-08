/**
 * MODstore 制作端：从 /api/system/* 加载与 FHD 宿主一致的配置。
 */
import { ref } from 'vue'
import { requestJson } from '../infrastructure/http/client'
import type { IndustryPreset } from '../constants/industryPresets'

export type EmployeeRegistryRules = {
  workflow_employee_id_prefixes?: string[]
  exclude_id_suffixes?: string[]
  exclude_artifact_types?: string[]
  exclude_mod_ids?: string[]
  non_workflow_desk_employee_patterns?: string[]
}

const loaded = ref(false)
export const industryPresets = ref<Record<string, IndustryPreset>>({})
export const industryPresetIds = ref<string[]>([])
export const employeeRegistryRules = ref<EmployeeRegistryRules | null>(null)

function unwrapData<T>(body: unknown): T | null {
  if (!body || typeof body !== 'object') return null
  const o = body as Record<string, unknown>
  if (o.data !== undefined) return o.data as T
  return body as T
}

export async function bootstrapHostConfig(): Promise<void> {
  if (loaded.value) return
  try {
    const [presetsBody, rulesBody] = await Promise.all([
      requestJson('/api/system/industry-presets').catch(() => null),
      requestJson('/api/system/employee-registry-rules').catch(() => null),
    ])
    const presetsData = unwrapData<{
      preset_ids?: string[]
      presets?: Record<string, IndustryPreset>
    }>(presetsBody)
    if (presetsData?.presets) {
      industryPresets.value = { ...presetsData.presets }
      industryPresetIds.value = Array.isArray(presetsData.preset_ids)
        ? [...presetsData.preset_ids]
        : Object.keys(presetsData.presets)
    }
    const rules = unwrapData<EmployeeRegistryRules>(rulesBody)
    if (rules) employeeRegistryRules.value = rules
    loaded.value = true
  } catch {
    /* fallback to bundled constants */
  }
}
