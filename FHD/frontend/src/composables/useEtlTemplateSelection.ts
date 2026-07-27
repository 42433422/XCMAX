import { computed, ref, watch, type Ref } from 'vue'

import type { EtlCapabilities, EtlTemplate } from '@/api/etl'

const COMPATIBILITY_TARGETS = new Set([
  'customer_products',
  'customers',
  'products',
  'shipment_records',
])

export function useEtlTemplateSelection(options: {
  capabilities: Ref<EtlCapabilities | null>
  templates: Ref<EtlTemplate[]>
  targetType: Ref<string>
}) {
  const templateSelection = ref('')
  const compatibleTemplates = computed(() => (
    options.templates.value.filter((item) => item.target_type === options.targetType.value)
  ))
  const compatiblePresets = computed(() => (
    COMPATIBILITY_TARGETS.has(options.targetType.value)
      ? options.capabilities.value?.compatibility_presets || []
      : []
  ))
  const templateId = computed(() => (
    templateSelection.value.startsWith('template:')
      ? templateSelection.value.slice('template:'.length)
      : ''
  ))
  const compatibilityPresetId = computed(() => (
    templateSelection.value.startsWith('preset:')
      ? templateSelection.value.slice('preset:'.length)
      : ''
  ))
  const selectedCompatibilityPreset = computed(() => (
    compatiblePresets.value.find((item) => item.id === compatibilityPresetId.value)
  ))

  watch(options.targetType, () => {
    templateSelection.value = ''
  })

  return {
    templateSelection,
    compatibleTemplates,
    compatiblePresets,
    templateId,
    compatibilityPresetId,
    selectedCompatibilityPreset,
  }
}
