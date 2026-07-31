import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { etlApiMock } = vi.hoisted(() => ({
  etlApiMock: {
    capabilities: vi.fn(),
    templates: vi.fn(),
    runs: vi.fn(),
    targetConfigs: vi.fn(),
    upload: vi.fn(),
    preview: vi.fn(),
    run: vi.fn(),
    rows: vi.fn(),
    patchDraft: vi.fn(),
    execute: vi.fn(),
    retry: vi.fn(),
    reanalyzeLlm: vi.fn(),
    rollback: vi.fn(),
    saveShipmentTemplate: vi.fn(),
    createTemplate: vi.fn(),
    createTargetConfig: vi.fn(),
    testTarget: vi.fn(),
    exportUrl: vi.fn(),
    errorExportUrl: vi.fn(),
  },
}))

vi.mock('@/api/etl', () => ({ etlApi: etlApiMock }))

import EtlCenterView from './EtlCenterView.vue'

async function mountView(runId = '') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/business-docking', component: EtlCenterView }],
  })
  await router.push({
    path: '/business-docking',
    query: runId ? { run_id: runId } : {},
  })
  await router.isReady()
  const wrapper = mount(EtlCenterView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

function folderFile(name: string, relativePath: string) {
  const file = new File(['data'], name, { type: 'text/csv', lastModified: 123 })
  Object.defineProperty(file, 'webkitRelativePath', { value: relativePath })
  return file
}

function queuedRun(id: string, fileName: string) {
  return {
    id,
    upload_id: `upload-${id}`,
    file_name: fileName,
    file_sha256: id,
    target_type: 'customer_products',
    status: 'queued',
    stage: 'queued',
    progress: 0,
    total_rows: 0,
    processed_rows: 0,
    summary: { new: 0, update: 0, skip: 0, error: 0, executed: 0 },
    details: {},
    source_features: {},
    draft: {},
    receipt: {},
    reversible: true,
  }
}

function previewRun(id = 'preview-run') {
  return {
    ...queuedRun(id, '客户产品.xlsx'),
    status: 'preview_ready',
    stage: 'preview_ready',
    progress: 100,
    total_rows: 3,
    processed_rows: 3,
    summary: { new: 1, update: 1, skip: 0, error: 1, executed: 0 },
    source_features: { headers: ['购买单位', '产品名称', '地址'] },
    draft: {
      field_mappings: [
        {
          source: '购买单位',
          target: 'customer_name',
          transforms: [],
          confidence: 0.96,
          required: true,
        },
        {
          source: '地址',
          target: 'address',
          transforms: [{ op: 'custom_lookup', table: 'districts' }],
          confidence: 0.72,
          required: false,
        },
      ],
      match_keys: ['customer_name'],
      allowed_update_fields: [],
      ocr_confirmed: false,
    },
  }
}

function previewRows() {
  return [
    {
      id: 1,
      source_sheet: 'Sheet1',
      source_row: 2,
      source: { 购买单位: '国圣化工', 产品名称: '底漆' },
      normalized: { customer_name: '国圣化工', product_name: '底漆' },
      provenance: {},
      validation_issues: [],
      llm_suggestion: { action: 'new', reason: '未匹配到现有产品' },
      suggested_action: 'new',
      final_action: 'new',
      action_overridden: false,
      match_ref: null,
      before: {},
      after: { customer_name: '国圣化工', product_name: '底漆' },
    },
    {
      id: 2,
      source_sheet: 'Sheet1',
      source_row: 3,
      source: { 购买单位: '国圣化工', 产品名称: '面漆' },
      normalized: { customer_name: '国圣化工', product_name: '面漆', address: '上海' },
      provenance: {},
      validation_issues: [],
      llm_suggestion: { action: 'update', reason: '地址发生变化' },
      suggested_action: 'update',
      final_action: 'update',
      action_overridden: false,
      match_ref: 'product:2',
      before: { address: '苏州' },
      after: { address: '上海' },
    },
    {
      id: 3,
      source_sheet: 'OCR',
      source_row: 4,
      source: { 购买单位: '低置信客户' },
      normalized: { customer_name: '低置信客户' },
      provenance: {
        ocr: true,
        page: 2,
        table_position: { row: 7 },
        original_fragment: '低置信客户',
        low_confidence_fields: ['购买单位'],
      },
      validation_issues: [
        { code: 'OCR_LOW_CONFIDENCE', message: '请复核购买单位', severity: 'error', field: 'customer_name' },
      ],
      llm_suggestion: {},
      suggested_action: 'error',
      final_action: 'error',
      action_overridden: false,
      match_ref: null,
      before: {},
      after: {},
    },
  ]
}

function completedRun(id = 'completed-run') {
  return {
    ...previewRun(id),
    file_name: '已导入.xlsx',
    status: 'completed',
    stage: 'completed',
    summary: { new: 2, update: 1, skip: 1, error: 0, executed: 3 },
    receipt: { customer_ids: ['customer-1'], product_ids: ['product-1', 'product-2'] },
    created_at: '2026-07-27T06:00:00Z',
  }
}

function buttonByText(wrapper: Awaited<ReturnType<typeof mountView>>, text: string) {
  return wrapper.findAll('button').find((button) => button.text().includes(text))
}

describe('EtlCenterView folder workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    etlApiMock.capabilities.mockResolvedValue({
      enabled: true,
      limits: { max_file_bytes: 100 * 1024 * 1024, max_rows: 100_000 },
      inputs: { structured: [], ocr: [], knowledge_only: [], folder_upload: true },
      transforms: [],
      targets: [
        {
          type: 'customer_products',
          label: '客户及产品',
          fields: [
            {
              key: 'customer_name',
              label: '客户名称',
              type: 'string',
              required: true,
              aliases: [],
              updatable: false,
            },
            {
              key: 'address',
              label: '地址',
              type: 'string',
              required: false,
              aliases: [],
              updatable: true,
            },
          ],
          required_fields: [],
          default_match_keys: [],
          supported_actions: ['new', 'update', 'skip'],
          reversible: true,
        },
        {
          type: 'webhook',
          label: 'Webhook',
          fields: [],
          required_fields: [],
          default_match_keys: [],
          supported_actions: ['new', 'skip'],
          reversible: false,
          allow_dynamic_fields: true,
        },
        {
          type: 'shipment_records',
          label: '发货记录',
          fields: [],
          required_fields: [],
          default_match_keys: [],
          supported_actions: ['new', 'skip'],
          reversible: true,
        },
      ],
      compatibility_presets: [{ id: 'legacy', label: '旧预设', source: 'yaml', target: 'customer_products' }],
      execution_policy: {},
    })
    etlApiMock.templates.mockResolvedValue([])
    etlApiMock.runs.mockResolvedValue([])
    etlApiMock.targetConfigs.mockResolvedValue([
      {
        id: 'webhook-1',
        name: 'ERP 回调',
        target_type: 'webhook',
        endpoint_url: 'https://example.com/hook',
        headers: {},
        has_secret: true,
        is_active: true,
      },
    ])
    etlApiMock.rows.mockResolvedValue({
      page: 1,
      page_size: 50,
      total: 3,
      items: previewRows(),
    })
    etlApiMock.exportUrl.mockImplementation((id: string) => `/api/etl/runs/${id}/download`)
    etlApiMock.errorExportUrl.mockImplementation((id: string) => `/api/etl/runs/${id}/errors/export`)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows separate file and whole-folder pickers', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('选择整个文件夹')
    expect(wrapper.text()).toContain('单文件 100.0 MB')
    expect(wrapper.text()).toContain('智能识别（推荐）')
    expect(wrapper.text()).toContain('送货单会自动选择“发货记录”')
    expect(wrapper.text()).toContain('已获取 1 个旧 YAML/知识库兼容预设')
    expect(wrapper.find('input[type="file"][multiple]').exists()).toBe(true)
    expect(wrapper.find('input[type="file"][webkitdirectory]').exists()).toBe(true)
  })

  it('explains the 100MB single-file limit before a file reaches the API', async () => {
    const wrapper = await mountView()
    const input = wrapper.find('input[type="file"][multiple]')
    const oversized = new File(['x'], 'over-limit.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    Object.defineProperty(oversized, 'size', { value: 100 * 1024 * 1024 + 1 })
    Object.defineProperty(input.element, 'files', { value: [oversized] })

    await input.trigger('change')

    expect(wrapper.text()).toContain('已忽略 1 个不支持、重复或超过 100.0 MB 的文件')
    expect(wrapper.text()).toContain('over-limit.xlsx · 单文件超过 100.0 MB')
    expect(etlApiMock.upload).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('opens a ready auto-detected shipment preview with the companion preview action', async () => {
    const shipment = {
      ...previewRun('auto-shipment-run'),
      file_name: '侯雪梅.xlsx',
      upload_id: 'upload-houxuemei',
      target_type: 'shipment_records',
      source_features: {
        business_document_type: 'delivery_note',
        shipment_template_candidate: {
          name: '金汉武家私-发货单版式',
          sheet: '侯雪梅',
          header_row: 3,
          customer_name: '金汉武家私',
          order_number: '26-010057A',
        },
        target_detection: {
          target_type: 'shipment_records',
          document_type: 'delivery_note_workbook',
        },
        sheet_plan: [
          { sheet: '侯雪梅', role: 'delivery_note_template_and_records', status: 'included', rows: 6 },
          { sheet: '25年回款', role: 'finance_or_reconciliation', status: 'excluded', rows: 0 },
        ],
      },
    }
    etlApiMock.upload.mockResolvedValue({
      upload_id: 'upload-houxuemei',
      file_name: '侯雪梅.xlsx',
      suffix: '.xlsx',
      size_bytes: 4,
      sha256: 'source-hash',
    })
    etlApiMock.preview.mockResolvedValue(shipment)
    const wrapper = await mountView()
    const input = wrapper.find('input[type="file"][multiple]')
    const source = new File(['data'], '侯雪梅.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    Object.defineProperty(input.element, 'files', { value: [source] })
    await input.trigger('change')
    await buttonByText(wrapper, '上传并开始预演')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.preview).toHaveBeenCalledWith(expect.objectContaining({
      upload_id: 'upload-houxuemei',
      target_type: 'auto',
    }))
    expect(wrapper.text()).toContain('写入目标')
    expect(wrapper.text()).toContain('发货记录')
    expect(wrapper.text()).toContain('已获取送货单版式候选：金汉武家私-发货单版式')
    expect(wrapper.text()).toContain('尚未保存')
    expect(wrapper.text()).toContain('要同时补全客户库和产品库？')
    expect(buttonByText(wrapper, '预演客户及产品')).toBeTruthy()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('passes the selected read-only compatibility preset into preview', async () => {
    etlApiMock.upload.mockResolvedValue({
      upload_id: 'upload-legacy',
      file_name: 'legacy.xlsx',
      suffix: '.xlsx',
      size_bytes: 4,
      sha256: 'legacy',
    })
    etlApiMock.preview.mockResolvedValue(queuedRun('run-legacy', 'legacy.xlsx'))
    const wrapper = await mountView()
    await wrapper.find('.etl-form-card select').setValue('customer_products')
    await flushPromises()
    await wrapper.find('select[aria-label="导入模板"]').setValue('preset:legacy')

    const input = wrapper.find('input[type="file"][multiple]')
    const file = new File(['data'], 'legacy.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await buttonByText(wrapper, '上传并开始预演')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.preview).toHaveBeenCalledWith(expect.objectContaining({
      upload_id: 'upload-legacy',
      target_type: 'customer_products',
      compatibility_preset_id: 'legacy',
    }))
    expect(etlApiMock.preview.mock.calls[0][0].template_id).toBeUndefined()
    wrapper.unmount()
  })

  it('shows a saved personal template before an auto-target preview', async () => {
    etlApiMock.templates.mockResolvedValue([
      {
        id: 'hou-template',
        name: '侯雪梅客户产品模板',
        target_type: 'customer_products',
        current_version: 1,
        version: {
          id: 'hou-template-v1',
          number: 1,
          source_features: {},
          field_mappings: [],
          validation_rules: [],
          match_keys: [],
          allowed_update_fields: [],
          action_rules: {},
        },
      },
    ])

    const wrapper = await mountView()

    expect(wrapper.find('select[aria-label="导入模板"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('智能识别（或选择个人模板）')
    expect(wrapper.text()).toContain('侯雪梅客户产品模板 · 客户及产品 · v1')
    wrapper.unmount()
  })

  it('shows folder name, file count, relative paths, and batch action', async () => {
    const wrapper = await mountView()
    const input = wrapper.find('input[type="file"][webkitdirectory]')
    const files = [
      folderFile('customers.csv', '华东批次/客户/customers.csv'),
      folderFile('products.csv', '华东批次/产品/products.csv'),
    ]
    Object.defineProperty(input.element, 'files', { value: files })
    await input.trigger('change')

    expect(wrapper.text()).toContain('华东批次 · 2 个可处理文件')
    expect(wrapper.text()).toContain('华东批次/客户/customers.csv')
    expect(wrapper.text()).toContain('华东批次/产品/products.csv')
    expect(wrapper.text()).toContain('批量上传并创建 2 个预演')
    wrapper.unmount()
  })

  it('uploads every folder file with one batch id and its own relative path', async () => {
    etlApiMock.upload.mockImplementation(async (file: File) => ({
      upload_id: `upload-${file.name}`,
      file_name: file.name,
      suffix: '.csv',
      size_bytes: file.size,
      sha256: file.name,
    }))
    etlApiMock.preview.mockImplementation(async ({ upload_id }: { upload_id: string }) => (
      queuedRun(`run-${upload_id}`, upload_id)
    ))
    const wrapper = await mountView()
    const input = wrapper.find('input[type="file"][webkitdirectory]')
    const files = [
      folderFile('customers.csv', '华东批次/客户/customers.csv'),
      folderFile('products.csv', '华东批次/产品/products.csv'),
    ]
    Object.defineProperty(input.element, 'files', { value: files })
    await input.trigger('change')
    const start = wrapper.findAll('button').find((button) => (
      button.text().includes('批量上传并创建 2 个预演')
    ))
    await start?.trigger('click')
    await flushPromises()

    expect(etlApiMock.upload).toHaveBeenCalledTimes(2)
    const options = etlApiMock.upload.mock.calls.map((call) => call[1])
    expect(new Set(options.map((item) => item.batchId)).size).toBe(1)
    expect(options.map((item) => item.relativePath)).toEqual([
      '华东批次/客户/customers.csv',
      '华东批次/产品/products.csv',
    ])
    expect(etlApiMock.preview).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('edits safe mappings, confirms OCR, saves a template, and executes only valid rows', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.patchDraft.mockResolvedValue(run)
    etlApiMock.createTemplate.mockResolvedValue({ id: 'template-1' })
    etlApiMock.execute.mockResolvedValue({ ...run, status: 'executing', stage: 'executing' })
    etlApiMock.runs.mockResolvedValue([run])
    const wrapper = await mountView(run.id)

    expect(wrapper.text()).toContain('客户 → 产品关系')
    expect(wrapper.text()).toContain('OCR 第 2 页 · 表格行 7')
    expect(wrapper.text()).toContain('1 行数据冲突需确认')
    expect(wrapper.text()).toContain('这不是数据库执行失败')
    expect(buttonByText(wrapper, '确认执行')?.attributes('disabled')).toBeDefined()

    await buttonByText(wrapper, '字段映射')?.trigger('click')
    const transformSelect = wrapper.findAll('select[aria-label="字段标准化方式"]')[0]
    await transformSelect.setValue('trim')
    expect(wrapper.findAll('textarea[aria-label="安全转换 JSON"]')).toHaveLength(1)

    const secondTransform = wrapper.findAll('select[aria-label="字段标准化方式"]')[1]
    await secondTransform.setValue('custom')
    let transformEditor = wrapper.find('textarea[aria-label="安全转换 JSON"]')
    await transformEditor.setValue('{}')
    await buttonByText(wrapper, '保存并重新校验')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('address 的转换规则必须是 JSON 数组')
    expect(etlApiMock.patchDraft).not.toHaveBeenCalled()

    transformEditor = wrapper.find('textarea[aria-label="安全转换 JSON"]')
    await transformEditor.setValue('[{"op":"trim"}]')
    const ocrCheckbox = wrapper.findAll('input[type="checkbox"]').find((input) => (
      input.element.parentElement?.textContent?.includes('OCR 表格位置')
    ))
    await ocrCheckbox?.setValue(true)
    const addressCheckbox = wrapper.findAll('input[type="checkbox"]').find((input) => (
      input.element.parentElement?.textContent?.includes('地址')
    ))
    await addressCheckbox?.setValue(true)
    await buttonByText(wrapper, '保存并重新校验')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.patchDraft).toHaveBeenCalledWith(run.id, expect.objectContaining({
      allowed_update_fields: ['address'],
      ocr_confirmed: true,
    }))

    await wrapper.get('input[aria-label="个人模板名称"]').setValue('  客户产品模板  ')
    await buttonByText(wrapper, '保存个人模板')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.createTemplate).toHaveBeenCalledWith(expect.objectContaining({
      name: '客户产品模板',
      target_type: 'customer_products',
    }))

    const validRowsCheckbox = wrapper.findAll('input[type="checkbox"]').find((input) => (
      input.element.parentElement?.textContent?.includes('仅写入无冲突行')
    ))
    await validRowsCheckbox?.setValue(true)
    await buttonByText(wrapper, '确认执行')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.execute).toHaveBeenCalledWith(run.id, true)
    expect(wrapper.text()).toContain('运行历史')
    wrapper.unmount()
  })

  it('shows source coordinates and requires document-structure confirmation', async () => {
    const run: any = previewRun('document-proof')
    run.summary = { new: 2, update: 0, skip: 0, error: 0, executed: 0 }
    run.source_features = {
      headers: ['订单号', '供应商', '品名', '数量'],
      document_understanding: {
        file_structure: 'single_document',
        summary: '识别为采购订单，共 2 条明细',
        requires_confirmation: true,
        documents: [
          {
            document_id: 'po-1',
            document_type: 'purchase_order',
            sheet: '采购订单',
            confidence: 0.97,
            header_fields: [
              {
                role: 'document_number',
                label: '订单号',
                value: 'PO-2026-7788',
                value_coordinate: 'B2',
                value_cell_id: 's1:r2:c2',
              },
              {
                role: 'supplier',
                label: '供应商',
                value: '星光涂料厂',
                value_coordinate: 'B3',
                value_cell_id: 's1:r3:c2',
              },
            ],
            tables: [
              {
                header_start_row: 7,
                header_end_row: 7,
                data_start_row: 8,
                data_end_row: 9,
              },
            ],
            issues: [],
          },
        ],
      },
    }
    run.draft.document_confirmed = false
    const confirmed = {
      ...run,
      draft: { ...run.draft, document_confirmed: true },
    }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.patchDraft.mockResolvedValue(confirmed)

    const wrapper = await mountView(run.id)

    expect(wrapper.text()).toContain('一份文件一张单 · 1 张单')
    expect(wrapper.text()).toContain('采购单')
    expect(wrapper.text()).toContain('PO-2026-7788')
    expect(wrapper.text()).toContain('B2')
    expect(wrapper.text()).toContain('数据 8-9 行')
    expect(buttonByText(wrapper, '确认执行')?.attributes('disabled')).toBeDefined()

    await buttonByText(wrapper, '确认单据结构')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.patchDraft).toHaveBeenCalledWith(run.id, {
      document_confirmed: true,
    })
    expect(wrapper.text()).toContain('结构已确认')
    wrapper.unmount()
  })

  it('shows sheet inventory before per-document preview routes', async () => {
    const root: any = previewRun('workbook-root')
    root.file_name = '业务合集.xlsx'
    root.target_type = 'shipment_records'
    root.summary = { new: 1, update: 0, skip: 0, error: 0, executed: 0 }
    root.details = {
      workbook_root_run_id: 'workbook-root',
      sheet_inventory: [
        {
          sheet_index: 1,
          sheet: '报价混排',
          physical_range: 'A1:D7',
          observed_effective_range: 'A1:D7',
          evidence_complete: true,
          structure: 'multi_document',
          document_count: 2,
          business_objects: ['quotation', 'invoice'],
        },
        {
          sheet_index: 2,
          sheet: '考勤',
          physical_range: 'A1:C2',
          observed_effective_range: 'A1:C2',
          evidence_complete: true,
          structure: 'single_document',
          document_count: 1,
          business_objects: ['attendance'],
        },
      ],
      document_routes: [
        {
          route_id: 'quote',
          run_id: 'workbook-root',
          sheet: '报价混排',
          document_type: 'quotation',
          target_type: 'export_xlsx',
          status: 'preview_ready',
        },
        {
          route_id: 'invoice',
          run_id: 'invoice-run',
          sheet: '报价混排',
          document_type: 'invoice',
          target_type: 'export_xlsx',
          status: 'preview_ready',
        },
        {
          route_id: 'attendance',
          run_id: 'attendance-run',
          sheet: '考勤',
          document_type: 'attendance',
          target_type: 'attendance',
          status: 'preview_ready',
        },
      ],
    }
    root.source_features = {
      headers: ['品名', '数量', '单价', '金额'],
      document_understanding: {
        file_structure: 'single_document',
        summary: '报价单独立预演',
        requires_confirmation: true,
        documents: [
          {
            document_id: 'quote',
            document_type: 'quotation',
            sheet: '报价混排',
            confidence: 0.98,
            header_fields: [],
            tables: [{ header_start_row: 2, header_end_row: 2, data_start_row: 3, data_end_row: 3 }],
            issues: [],
          },
        ],
      },
    }
    const invoice = {
      ...root,
      id: 'invoice-run',
      target_type: 'export_xlsx',
      details: {
        workbook_root_run_id: 'workbook-root',
        sheet_inventory: root.details.sheet_inventory,
        document_route: root.details.document_routes[1],
      },
    }
    etlApiMock.run
      .mockResolvedValueOnce(root)
      .mockResolvedValueOnce(invoice)

    const wrapper = await mountView(root.id)

    const inventory = wrapper.get('[data-testid="sheet-inventory"]')
    expect(inventory.text()).toContain('第一步 · 工作簿清点')
    expect(inventory.text()).toContain('2 个 Sheet')
    expect(inventory.text()).toContain('Sheet 01')
    expect(inventory.text()).toContain('报价混排')
    expect(inventory.text()).toContain('一表多单')
    expect(inventory.text()).toContain('2 张单')
    expect(inventory.text()).toContain('报价单、发票')
    expect(inventory.text()).toContain('考勤表')

    const invoiceButton = inventory.findAll('button').find((button) => (
      button.text().includes('发票')
    ))
    await invoiceButton?.trigger('click')
    await flushPromises()

    expect(etlApiMock.run).toHaveBeenLastCalledWith('invoice-run')
    expect(wrapper.text()).toContain('返回工作簿任务')
    wrapper.unmount()
  })

  it('shows the sheet count while business classification is still running', async () => {
    const run: any = {
      ...queuedRun('inventory-first-run', '多表工作簿.xlsx'),
      status: 'previewing',
      stage: 'classifying_sheets',
      progress: 15,
      details: {
        workbook_stage: 'sheet_inventory_ready',
        workbook_sheet_count: 2,
        sheet_inventory: [
          {
            sheet_index: 1,
            sheet: '送货单',
            physical_range: 'A1:F20',
            observed_effective_range: 'A1:F20',
            structure: 'unclassified',
            document_count: 0,
            is_empty: false,
          },
          {
            sheet_index: 2,
            sheet: '产品目录',
            physical_range: 'A1:D30',
            observed_effective_range: 'A1:D30',
            structure: 'unclassified',
            document_count: 0,
            is_empty: false,
          },
        ],
      },
    }
    etlApiMock.run.mockResolvedValue(run)

    const wrapper = await mountView(run.id)

    const inventory = wrapper.get('[data-testid="sheet-inventory-progress"]')
    expect(wrapper.text()).toContain('逐 Sheet 识别业务对象')
    expect(wrapper.text()).toContain('第一步已完成：共 2 个 Sheet')
    expect(inventory.text()).toContain('工作簿清点已完成')
    expect(inventory.text()).toContain('送货单')
    expect(inventory.text()).toContain('产品目录')
    expect(inventory.text()).toContain('等待识别')
    wrapper.unmount()
  })

  it('localizes historical English model summaries, issues, and row advice', async () => {
    const run: any = previewRun('localized-document-proof')
    run.source_features = {
      headers: ['品名', '金额'],
      document_understanding: {
        file_structure: 'single_document',
        summary: 'Single purchase order document (采购订单) with a detail table.',
        requires_confirmation: true,
        documents: [
          {
            document_id: 'po-1',
            document_type: 'purchase_order',
            sheet: '采购订单',
            confidence: 0.95,
            header_fields: [],
            tables: [{ header_start_row: 7, header_end_row: 7, data_start_row: 8, data_end_row: 9 }],
            issues: [
              {
                message: 'No total amount row present; sum of line amounts would be 157.',
              },
            ],
          },
        ],
      },
    }
    const rows = previewRows()
    rows[0].llm_suggestion.reason = 'Complete normalized record; data is valid for new insert.'
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.rows.mockResolvedValue({
      page: 1,
      page_size: 50,
      total: rows.length,
      items: rows,
    })

    const wrapper = await mountView(run.id)

    expect(wrapper.text()).toContain('识别为采购单，共 1 张单；已定位单据头和 1 个明细表')
    expect(wrapper.text()).toContain('按明细金额计算合计为 157')
    expect(wrapper.text()).toContain('字段完整且未发现重复记录，模型建议新增')
    expect(wrapper.text()).not.toContain('No total amount row')
    expect(wrapper.text()).not.toContain('Single purchase order')
    expect(wrapper.text()).not.toContain('Complete normalized record')
    wrapper.unmount()
  })

  it('retries degraded document understanding without uploading again', async () => {
    const run: any = previewRun('degraded-document-proof')
    run.source_features = {
      headers: ['品名', '数量'],
      document_understanding: {
        file_structure: 'single_document',
        summary: '确定性结构候选，等待人工确认',
        requires_confirmation: true,
        llm: {
          used_llm: true,
          degraded: true,
          degradation_code: 'ETL_LLM_UNAVAILABLE',
        },
        documents: [
          {
            document_id: 'fallback-1',
            document_type: 'purchase_order',
            sheet: '采购订单',
            confidence: 0.75,
            header_fields: [],
            tables: [],
            issues: ['LLM 不可用，当前结构来自确定性降级候选，必须人工确认。'],
          },
        ],
      },
    }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.reanalyzeLlm.mockResolvedValue({
      ...run,
      status: 'previewing',
      stage: 'parsing',
      progress: 5,
    })

    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '重新调用 LLM')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.reanalyzeLlm).toHaveBeenCalledWith(run.id)
    expect(etlApiMock.upload).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('applies deterministic row overrides and shows only the selected action rows', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.patchDraft.mockResolvedValue(run)
    const rows = previewRows()
    etlApiMock.rows.mockImplementation(async (
      _id: string,
      page: number,
      pageSize: number,
      action = '',
    ) => {
      const items = action ? rows.filter((row) => row.final_action === action) : rows
      return { page, page_size: pageSize, total: items.length, items }
    })
    const wrapper = await mountView(run.id)

    await buttonByText(wrapper, '本页可新增行设为新增')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.patchDraft).toHaveBeenCalledWith(run.id, {
      row_overrides: { '1': 'new' },
    })

    await buttonByText(wrapper, '本页全部跳过')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.patchDraft).toHaveBeenCalledWith(run.id, {
      row_overrides: { '1': 'skip', '2': 'skip' },
    })

    const firstRowAction = wrapper.findAll('tbody select')[0]
    await firstRowAction.setValue('skip')
    await flushPromises()
    expect(etlApiMock.patchDraft).toHaveBeenCalledWith(run.id, {
      row_overrides: { '1': 'skip' },
    })

    const actionFilter = wrapper.find('.etl-table-toolbar select')
    await actionFilter.setValue('error')
    await flushPromises()
    expect(etlApiMock.rows).toHaveBeenLastCalledWith(run.id, 1, 50, 'error')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.text()).toContain('低置信客户')
    expect(wrapper.text()).not.toContain('国圣化工')

    await wrapper.findAll('.etl-summary-grid button')[0].trigger('click')
    await flushPromises()
    expect(etlApiMock.rows).toHaveBeenLastCalledWith(run.id, 1, 50, 'new')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.text()).toContain('底漆')
    expect(wrapper.text()).not.toContain('低置信客户')
    wrapper.unmount()
  })

  it('shows multi-region planning and software LLM participation', async () => {
    const run = previewRun()
    run.source_features = {
      region_summary: { selected: 2, excluded: 3, business_rows: 6 },
      regions: [
        {
          id: '业务员甲!R3C1:10',
          sheet: '业务员甲',
          header_row: 3,
          status: 'selected',
          customer_name: '甲家具',
        },
        {
          id: '报价!R2C1:5',
          sheet: '报价',
          header_row: 2,
          status: 'excluded',
        },
      ],
      sheet_plan: [
        {
          sheet: '侯雪梅',
          role: 'delivery_note_template_and_records',
          status: 'included',
          rows: 6,
          reason: '识别到购货单位、产品表头与合计行',
        },
        {
          sheet: '侯雪梅出货',
          role: 'supporting_customer_product_data',
          status: 'included',
          rows: 93,
          reason: '识别到高置信出货历史或客户报价',
        },
        {
          sheet: '25年回款',
          role: 'finance_or_reconciliation',
          status: 'excluded',
          rows: 0,
          reason: '财务/对账附表不写入客户产品或发货记录',
        },
      ],
      latest_record_selection: {
        basis: 'source_date_then_same_sheet_row',
        unique_candidates: 93,
        stale_records_skipped: 12,
      },
      llm_structure: { used_llm: true, degraded: false },
    }
    etlApiMock.run.mockResolvedValue(run)

    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '预演确认')?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已识别 2 个业务区块')
    expect(wrapper.text()).toContain('排除 3 个其他区块')
    expect(wrapper.text()).toContain('软件 LLM 已完成单据理解和字段建议')
    expect(wrapper.text()).toContain('客户 甲家具')
    expect(wrapper.text()).toContain('工作簿附表规划 · 已检查 3 个工作表')
    expect(wrapper.text()).toContain('侯雪梅出货')
    expect(wrapper.text()).toContain('客户与产品补充数据')
    expect(wrapper.text()).toContain('25年回款')
    expect(wrapper.text()).toContain('财务或对账附表')
    expect(wrapper.text()).toContain('按来源日期选择最新有效记录，并排除 12 条较早或同日旧记录')
    wrapper.unmount()
  })

  it('lets the backend name a detected shipment layout from its canonical customer', async () => {
    const run = {
      ...previewRun('shipment-run'),
      file_name: '侯雪梅.xlsx',
      target_type: 'shipment_records',
      source_features: {
        business_document_type: 'delivery_note',
        region_summary: { selected: 2, excluded: 3, business_rows: 6 },
      },
    }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.saveShipmentTemplate.mockResolvedValue({
      template_id: 'db:12',
      name: '金汉武家私-发货单版式',
      file_path: '/runtime/金汉武家私-发货单版式.xlsx',
      message: '已保存发货单版式，后续开单会自动匹配',
    })
    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '保存发货单版式')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.saveShipmentTemplate).toHaveBeenCalledWith(
      run.id,
      '',
      '',
    )
    expect(wrapper.text()).toContain('金汉武家私-发货单版式')
    expect(wrapper.text()).toContain('后续开单会自动匹配')
    wrapper.unmount()
  })

  it('shows a previously saved private shipment layout after the run is reopened', async () => {
    const run = {
      ...previewRun('saved-shipment-layout-run'),
      file_name: '侯雪梅.xlsx',
      target_type: 'shipment_records',
      details: {
        shipment_document_template: {
          template_id: 'etl:private-layout',
          name: '金汉武家私-发货单版式',
        },
      },
    }
    etlApiMock.run.mockResolvedValue(run)

    const wrapper = await mountView(run.id)

    expect(wrapper.text()).toContain('已保存个人发货单版式')
    expect(wrapper.text()).toContain('金汉武家私-发货单版式')
    expect(wrapper.text()).toContain('仅当前用户可见')
    wrapper.unmount()
  })

  it('keeps an explicitly entered shipment layout name', async () => {
    const run = {
      ...previewRun('shipment-custom-layout-run'),
      file_name: '侯雪梅.xlsx',
      target_type: 'shipment_records',
    }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.saveShipmentTemplate.mockResolvedValue({
      template_id: 'db:13',
      name: '金汉武专用打印版式',
      file_path: '/runtime/金汉武专用打印版式.xlsx',
      message: '已保存发货单版式',
    })
    const wrapper = await mountView(run.id)
    await wrapper.get('input[aria-label="发货单版式名称"]').setValue('  金汉武专用打印版式  ')
    await buttonByText(wrapper, '保存发货单版式')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.saveShipmentTemplate).toHaveBeenCalledWith(
      run.id,
      '金汉武专用打印版式',
      '',
    )
    wrapper.unmount()
  })

  it('uses the operator-selected shipment layout region when saving a multi-layout workbook', async () => {
    const run = {
      ...previewRun('shipment-multi-layout-run'),
      file_name: '侯雪梅.xlsx',
      target_type: 'shipment_records',
      source_features: {
        shipment_template_candidates: [
          {
            name: '金汉武家私-发货单版式',
            source_region_id: '侯雪梅!R3C1:10',
            sheet: '侯雪梅',
            header_row: 3,
            customer_name: '金汉武家私',
          },
          {
            name: '宏运家具-发货单版式',
            source_region_id: '侯雪梅!R29C1:10',
            sheet: '侯雪梅',
            header_row: 29,
            customer_name: '宏运家具',
          },
        ],
      },
    }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.saveShipmentTemplate.mockResolvedValue({
      template_id: 'db:14',
      name: '宏运家具-发货单版式',
      file_path: '/runtime/宏运家具-发货单版式.xlsx',
      source_region_id: '侯雪梅!R29C1:10',
      message: '已保存发货单版式',
    })
    const wrapper = await mountView(run.id)
    const layoutSelect = wrapper.find('[data-testid="shipment-template-candidate"] select')
    expect(layoutSelect.exists()).toBe(true)
    expect(wrapper.text()).toContain('金汉武家私-发货单版式')

    await layoutSelect.setValue('侯雪梅!R29C1:10')
    await flushPromises()
    expect(wrapper.text()).toContain('宏运家具-发货单版式')
    await buttonByText(wrapper, '保存发货单版式')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.saveShipmentTemplate).toHaveBeenCalledWith(
      run.id,
      '',
      '侯雪梅!R29C1:10',
    )
    wrapper.unmount()
  })

  it('creates a customer-products preview from the shipment upload without writing data', async () => {
    const shipment = {
      ...previewRun('shipment-product-run'),
      file_name: '侯雪梅.xlsx',
      upload_id: 'upload-houxuemei',
      target_type: 'shipment_records',
      source_features: {
        business_document_type: 'delivery_note',
        sheet_plan: [
          {
            sheet: '侯雪梅',
            role: 'delivery_note_template_and_records',
            status: 'included',
            rows: 6,
          },
          {
            sheet: '侯雪梅出货',
            role: 'supporting_customer_product_data',
            status: 'included',
            rows: 93,
          },
        ],
      },
    }
    const customerProductPreview = {
      ...queuedRun('customer-product-preview', '侯雪梅.xlsx'),
      upload_id: 'upload-houxuemei',
      target_type: 'customer_products',
      status: 'queued',
      stage: 'queued',
    }
    etlApiMock.run.mockResolvedValue(shipment)
    etlApiMock.preview.mockResolvedValue(customerProductPreview)

    const wrapper = await mountView(shipment.id)
    await buttonByText(wrapper, '预演客户及产品')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.preview).toHaveBeenCalledWith({
      upload_id: 'upload-houxuemei',
      target_type: 'customer_products',
    })
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('客户及产品预演已创建')
    expect(wrapper.text()).toContain('不会写入客户库或产品库')
    expect(wrapper.text()).toContain('正在规划客户与产品附表')
    wrapper.unmount()
  })

  it('opens the automatically linked customer-products preview without creating another run', async () => {
    const shipment = {
      ...previewRun('shipment-linked-preview-run'),
      file_name: '侯雪梅.xlsx',
      upload_id: 'upload-houxuemei',
      target_type: 'shipment_records',
      details: {
        linked_customer_products_preview: {
          run_id: 'customer-products-linked-run',
          target_type: 'customer_products',
          preview_only: true,
          status: 'preview_ready',
        },
      },
      source_features: {
        business_document_type: 'delivery_note',
      },
    }
    const linked = {
      ...previewRun('customer-products-linked-run'),
      file_name: '侯雪梅.xlsx',
      upload_id: 'upload-houxuemei',
      target_type: 'customer_products',
    }
    etlApiMock.run.mockImplementation(async (id: string) => (
      id === shipment.id ? shipment : linked
    ))

    const wrapper = await mountView(shipment.id)
    expect(wrapper.text()).toContain('已自动规划客户库和产品库预演')
    expect(buttonByText(wrapper, '查看客户及产品预演')).toBeTruthy()
    etlApiMock.preview.mockClear()
    etlApiMock.execute.mockClear()

    await buttonByText(wrapper, '查看客户及产品预演')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.run).toHaveBeenLastCalledWith('customer-products-linked-run')
    expect(etlApiMock.preview).not.toHaveBeenCalled()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('这是同一上传文件自动建立的客户及产品预演')
    expect(wrapper.text()).toContain('客户及产品')
    wrapper.unmount()
  })

  it('loads history receipts, retries failures, and rolls back confirmed internal writes', async () => {
    const completed = completedRun()
    const failed = {
      ...previewRun('failed-run'),
      file_name: '失败.xlsx',
      status: 'failed',
      stage: 'failed',
      summary: { new: 0, update: 0, skip: 0, error: 1, executed: 1 },
      created_at: '2026-07-27T05:00:00Z',
    }
    etlApiMock.runs.mockResolvedValue([completed, failed])
    etlApiMock.run.mockImplementation(async (id: string) => (id === completed.id ? completed : failed))
    etlApiMock.rollback.mockResolvedValue({ ...completed, rollback_status: 'completed' })
    etlApiMock.retry.mockResolvedValue({ ...failed, status: 'queued', stage: 'queued' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = await mountView()

    await buttonByText(wrapper, '运行历史')?.trigger('click')
    expect(wrapper.text()).toContain('需确认 1')
    await buttonByText(wrapper, '已导入.xlsx')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已关联写入客户库和产品库')
    expect(wrapper.text()).toContain('已写入 3 行')
    expect(wrapper.find('a[href="/customers"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/products"]').exists()).toBe(true)

    await buttonByText(wrapper, '撤销本次写入')?.trigger('click')
    await flushPromises()
    expect(window.confirm).toHaveBeenCalled()
    expect(etlApiMock.rollback).toHaveBeenCalledWith(completed.id)

    await buttonByText(wrapper, '失败.xlsx')?.trigger('click')
    await flushPromises()
    await buttonByText(wrapper, '重新预演')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.retry).toHaveBeenCalledWith(failed.id)
    wrapper.unmount()
  })

  it('validates, saves, and tests a private webhook configuration', async () => {
    const config = {
      id: 'webhook-2',
      name: '新 ERP',
      target_type: 'webhook',
      endpoint_url: 'https://erp.example.com/etl',
      headers: { 'X-System': 'FHD' },
      has_secret: true,
      is_active: true,
    }
    etlApiMock.createTargetConfig.mockResolvedValue(config)
    etlApiMock.testTarget.mockResolvedValue({ ok: true })
    const wrapper = await mountView()
    const targetSelect = wrapper.find('.etl-form-card select')
    await targetSelect.setValue('webhook')
    await buttonByText(wrapper, '新建 Webhook 配置')?.trigger('click')

    const form = wrapper.find('.etl-webhook-form')
    const inputs = form.findAll('input')
    await inputs[0].setValue('新 ERP')
    await inputs[1].setValue('https://erp.example.com/etl')
    await inputs[2].setValue('secret-value')
    await form.find('textarea').setValue('[]')
    await form.trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('普通请求头必须是 JSON 对象')
    expect(etlApiMock.createTargetConfig).not.toHaveBeenCalled()

    await form.find('textarea').setValue('{"X-System":"FHD"}')
    await form.trigger('submit')
    await flushPromises()
    expect(etlApiMock.createTargetConfig).toHaveBeenCalledWith({
      name: '新 ERP',
      endpoint_url: 'https://erp.example.com/etl',
      headers: { 'X-System': 'FHD' },
      secret: 'secret-value',
    })

    await buttonByText(wrapper, '测试当前 Webhook')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.testTarget).toHaveBeenCalledWith(config.id)
    expect(wrapper.text()).toContain('连接测试成功')
    wrapper.unmount()
  })

  it('surfaces bootstrap failures and retries without losing the page', async () => {
    etlApiMock.capabilities.mockRejectedValueOnce(new Error('能力加载失败'))
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('能力加载失败')
    await buttonByText(wrapper, '重试')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.capabilities).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('单文件 100.0 MB')
    expect(wrapper.text()).not.toContain('能力加载失败')
    wrapper.unmount()
  })
})
