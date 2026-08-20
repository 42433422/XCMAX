import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { EtlTemplate } from '@/api/etl'

import { useEtlTemplateSelection } from './useEtlTemplateSelection'

describe('useEtlTemplateSelection', () => {
  it('offers personal templates before auto-detection and locks the chosen target', async () => {
    const version = {
      id: 'version-1',
      number: 1,
      source_features: {},
      field_mappings: [],
      validation_rules: [],
      match_keys: [],
      allowed_update_fields: [],
      action_rules: {},
    }
    const templates = ref<EtlTemplate[]>([
      {
        id: 'customer-products-1',
        name: '侯雪梅发货单',
        target_type: 'customer_products',
        current_version: 1,
        version,
      },
    ])
    const targetType = ref('auto')
    const selection = useEtlTemplateSelection({
      capabilities: ref(null),
      templates,
      targetType,
    })

    expect(selection.compatibleTemplates.value.map((item) => item.id)).toEqual(['customer-products-1'])

    selection.templateSelection.value = 'template:customer-products-1'
    await Promise.resolve()

    expect(targetType.value).toBe('customer_products')
    expect(selection.templateId.value).toBe('customer-products-1')
  })

  it('clears a selected template only when the user changes to another target', async () => {
    const version = {
      id: 'version-1',
      number: 1,
      source_features: {},
      field_mappings: [],
      validation_rules: [],
      match_keys: [],
      allowed_update_fields: [],
      action_rules: {},
    }
    const templates = ref<EtlTemplate[]>([
      {
        id: 'customer-products-1',
        name: '侯雪梅发货单',
        target_type: 'customer_products',
        current_version: 1,
        version,
      },
    ])
    const targetType = ref('customer_products')
    const selection = useEtlTemplateSelection({
      capabilities: ref(null),
      templates,
      targetType,
    })

    selection.templateSelection.value = 'template:customer-products-1'
    await Promise.resolve()
    targetType.value = 'products'
    await Promise.resolve()

    expect(selection.templateSelection.value).toBe('')
  })

  it('continues to clear a compatibility preset when the target changes', async () => {
    const targetType = ref('customers')
    const selection = useEtlTemplateSelection({
      capabilities: ref({
        compatibility_presets: [{ id: 'legacy-customers', target_type: 'customers', label: '客户预设' }],
      } as never),
      templates: ref([]),
      targetType,
    })

    selection.templateSelection.value = 'preset:legacy-customers'
    await Promise.resolve()
    targetType.value = 'products'
    await Promise.resolve()

    expect(selection.templateSelection.value).toBe('')
  })

  it('never offers a saved shipment print layout as an import mapping', () => {
    const version = {
      id: 'version-1',
      number: 1,
      source_features: {},
      field_mappings: [],
      validation_rules: [],
      match_keys: [],
      allowed_update_fields: [],
      action_rules: {},
    }
    const templates = ref<EtlTemplate[]>([
      {
        id: 'mapping-1',
        name: '发货记录字段映射',
        target_type: 'shipment_records',
        current_version: 1,
        version,
      },
      {
        id: 'layout-1',
        name: '金汉武家私-发货单版式',
        description: 'ETL_SHIPMENT_DOCUMENT_TEMPLATE',
        target_type: 'shipment_records',
        current_version: 1,
        version: { ...version, id: 'version-layout-1' },
      },
    ])
    const targetType = ref('shipment_records')
    const selection = useEtlTemplateSelection({
      capabilities: ref(null),
      templates,
      targetType,
    })

    expect(selection.compatibleTemplates.value.map((item) => item.id)).toEqual(['mapping-1'])
  })
})
