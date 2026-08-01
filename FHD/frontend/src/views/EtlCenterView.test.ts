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
    expect(wrapper.text()).toContain('送货单会建议“发货记录”')
    expect(wrapper.text()).toContain('确认前不写业务库')
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
    etlApiMock.execute.mockResolvedValue({ ...shipment, status: 'executing', stage: 'executing' })
    const wrapper = await mountView()
    const input = wrapper.find('input[type="file"][multiple]')
    const source = new File(['data'], '侯雪梅.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    Object.defineProperty(input.element, 'files', { value: [source] })
    await input.trigger('change')
    await buttonByText(wrapper, '上传并解析')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.preview).toHaveBeenCalledWith(expect.objectContaining({
      upload_id: 'upload-houxuemei',
      target_type: 'auto',
    }))
    expect(wrapper.text()).toContain('目标')
    expect(wrapper.text()).toContain('发货记录')
    expect(wrapper.text()).toContain('已获取送货单版式候选：金汉武家私-发货单版式')
    expect(wrapper.text()).toContain('尚未保存')
    expect(wrapper.text()).toContain('要同时补全客户库和产品库？')
    expect(buttonByText(wrapper, '导入客户及产品')).toBeTruthy()
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
    await buttonByText(wrapper, '上传并解析')?.trigger('click')
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
    expect(wrapper.text()).toContain('批量上传并解析 2 个文件')
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
      button.text().includes('批量上传并解析 2 个文件')
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
    vi.spyOn(window, 'prompt').mockReturnValue('  客户产品模板  ')
    const wrapper = await mountView(run.id)

    expect(wrapper.text()).toContain('客户 → 产品关系')
    expect(wrapper.text()).toContain('OCR 第 2 页 · 表格行 7')
    expect(wrapper.text()).toContain('默认阻断整批')
    expect(buttonByText(wrapper, '写入数据库')?.attributes('disabled')).toBeDefined()

    await buttonByText(wrapper, '字段映射')?.trigger('click')
    const transformSelect = wrapper.find('tbody select')
    await transformSelect.setValue('trim')
    expect((wrapper.findAll('textarea[aria-label="安全转换 JSON"]')[0].element as HTMLTextAreaElement).value)
      .toBe('[{"op":"trim"}]')

    const transformEditors = wrapper.findAll('textarea[aria-label="安全转换 JSON"]')
    await transformEditors[1].setValue('{}')
    await buttonByText(wrapper, '保存并重新校验')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('address 的转换规则必须是 JSON 数组')
    expect(etlApiMock.patchDraft).not.toHaveBeenCalled()

    await transformEditors[1].setValue('[{"op":"trim"}]')
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

    await buttonByText(wrapper, '保存个人模板')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.createTemplate).toHaveBeenCalledWith(expect.objectContaining({
      name: '客户产品模板',
      target_type: 'customer_products',
    }))

    const validRowsCheckbox = wrapper.findAll('input[type="checkbox"]').find((input) => (
      input.element.parentElement?.textContent?.includes('仅写入正确行')
    ))
    await validRowsCheckbox?.setValue(true)
    await buttonByText(wrapper, '写入数据库')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.execute).toHaveBeenCalledWith(run.id, true)
    expect(wrapper.text()).toContain('运行历史')
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
    run.details = {
      warnings: [
        {
          code: 'ETL_SHIPMENT_HISTORY_PRODUCTS_INCLUDED',
          message: '已从出货历史增补 93 个客户产品候选，仅用于客户产品预演。',
        },
        {
          code: 'ETL_PRODUCT_MODEL_AMBIGUITY',
          message: '发现 2 组型号歧义，需人工确认。',
        },
      ],
    }
    etlApiMock.run.mockResolvedValue(run)

    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '写入数据库')?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已识别 2 个业务区块')
    expect(wrapper.text()).toContain('排除 3 个其他区块')
    expect(wrapper.text()).toContain('软件 LLM 已参与结构或字段建议')
    expect(wrapper.text()).toContain('客户 甲家具')
    expect(wrapper.text()).toContain('工作簿附表规划 · 已检查 3 个工作表')
    expect(wrapper.text()).toContain('写入范围提醒 · ETL_SHIPMENT_HISTORY_PRODUCTS_INCLUDED')
    expect(wrapper.text()).toContain('发现 2 组型号歧义，需人工确认。')
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
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('')

    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '保存发货单版式')?.trigger('click')
    await flushPromises()

    expect(prompt).toHaveBeenCalledWith(
      '发货单版式名称（可选；留空将按识别到的客户命名）',
      '',
    )
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
    vi.spyOn(window, 'prompt').mockReturnValue('  金汉武专用打印版式  ')

    const wrapper = await mountView(run.id)
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
    vi.spyOn(window, 'prompt').mockReturnValue('')

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
    await buttonByText(wrapper, '导入客户及产品')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.preview).toHaveBeenCalledWith({
      upload_id: 'upload-houxuemei',
      target_type: 'customer_products',
    })
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('客户及产品导入任务已创建')
    expect(wrapper.text()).toContain('已从同一上传文件创建客户及产品导入任务')
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
    expect(wrapper.text()).toContain('已自动规划客户库和产品库导入')
    expect(buttonByText(wrapper, '查看客户及产品导入')).toBeTruthy()
    etlApiMock.preview.mockClear()
    etlApiMock.execute.mockClear()

    await buttonByText(wrapper, '查看客户及产品导入')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.run).toHaveBeenLastCalledWith('customer-products-linked-run')
    expect(etlApiMock.preview).not.toHaveBeenCalled()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('这是同一上传文件自动建立的客户及产品导入')
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
    await buttonByText(wrapper, '重新导入')?.trigger('click')
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
