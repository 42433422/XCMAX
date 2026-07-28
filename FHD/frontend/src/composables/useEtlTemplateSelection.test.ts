import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { EtlTemplate } from '@/api/etl'

import { useEtlTemplateSelection } from './useEtlTemplateSelection'

describe('useEtlTemplateSelection', () => {
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
