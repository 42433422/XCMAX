import { computed, ref, watch, type Ref } from 'vue'

import type { EtlCapabilities, EtlTemplate } from '@/api/etl'

const COMPATIBILITY_TARGETS = new Set([
  'customer_products',
  'customers',
  'products',
  'shipment_records',
])

// A saved delivery layout is intentionally stored in the same private ETL
// tables as mappings so it can retain tenant + owner isolation. It is not an
// import mapping, however, and must never be offered to the import selector.
const SHIPMENT_DOCUMENT_LAYOUT_DESCRIPTION = 'ETL_SHIPMENT_DOCUMENT_TEMPLATE'

export function useEtlTemplateSelection(options: {
  capabilities: Ref<EtlCapabilities | null>
  templates: Ref<EtlTemplate[]>
  targetType: Ref<string>
}) {
  const templateSelection = ref('')
  const compatibleTemplates = computed(() => (
    options.templates.value.filter((item) => (
      (options.targetType.value === 'auto' || item.target_type === options.targetType.value)
      && item.description !== SHIPMENT_DOCUMENT_LAYOUT_DESCRIPTION
    ))
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

  watch(options.targetType, (targetType) => {
    const selection = templateSelection.value
    if (!selection) return
    // Compatibility presets remain scoped to their target too. Keep the
    // previous reset behavior for them (and for an invalid selection) while a
    // same-target personal template stays selected after it locks the target.
    if (!selection.startsWith('template:')) {
      templateSelection.value = ''
      return
    }
    const selectedId = selection.slice('template:'.length)
    const selectedTemplate = options.templates.value.find((item) => item.id === selectedId)
    if (!selectedTemplate || selectedTemplate.target_type !== targetType) {
      templateSelection.value = ''
    }
  })

  watch(templateSelection, (selection) => {
    if (!selection.startsWith('template:') || options.targetType.value !== 'auto') return
    const selectedId = selection.slice('template:'.length)
    const selectedTemplate = options.templates.value.find((item) => item.id === selectedId)
    if (selectedTemplate) {
      // Choosing a private template is an explicit, deterministic target
      // choice. It only locks the preview target; execution remains gated by
      // the regular preview-and-confirm flow.
      options.targetType.value = selectedTemplate.target_type
    }
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
