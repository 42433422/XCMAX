import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EtlRun } from '@/api/etl'

const { etlApiMock, currentUserMock } = vi.hoisted(() => ({
  currentUserMock: vi.fn(),
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
    replay: vi.fn(),
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
vi.mock('@/api/auth', () => ({ authApi: { getCurrentUser: currentUserMock } }))

import EtlCenterView from './EtlRunHistory.vue'

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
    preview_revision: 'a'.repeat(64),
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
        {
          code: 'OCR_LOW_CONFIDENCE',
          message: '请复核购买单位',
          severity: 'error',
          field: 'customer_name',
        },
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

describe('existing ETL run history and confirmed actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    currentUserMock.mockResolvedValue({ success: true, data: { permissions: ['etl.read', 'etl.execute', 'etl.rollback', 'etl.template.manage', 'etl.target.manage'] } })
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
      preview_revision: 'a'.repeat(64),
    })
    etlApiMock.exportUrl.mockImplementation((id: string) => `/api/etl/runs/${id}/download`)
    etlApiMock.errorExportUrl.mockImplementation((id: string) => `/api/etl/runs/${id}/errors/export`)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })


  it('reprocesses saved source into a new preview and waits for explicit write confirmation', async () => {
    vi.useFakeTimers()
    const source = { ...completedRun(), details: { source_snapshot: { version: 1 } } }
    const details = { source_snapshot: { version: 1 }, replay_of: source.id }
    let replayed = { ...queuedRun('replayed-run', source.file_name), details }
    etlApiMock.run.mockImplementation(async (id: string) => id === source.id ? source : replayed)
    etlApiMock.runs.mockImplementation(async () => [source, replayed])
    etlApiMock.replay.mockImplementation(async () => replayed)
    etlApiMock.execute.mockResolvedValue(completedRun(replayed.id))
    const wrapper = await mountView(source.id)
    try {
      expect(buttonByText(wrapper, '重新处理')?.attributes('title')).toContain('确认后才会写入')
      await buttonByText(wrapper, '重新处理')!.trigger('click')
      await flushPromises()
      expect(etlApiMock.replay).toHaveBeenCalledWith(source.id)
      expect(wrapper.vm.$route.query.run_id).toBe(replayed.id)
      expect(wrapper.text()).toContain('从已保存的原始数据生成新预演，确认后才会写入')
      expect(wrapper.text()).not.toContain('解析通过后将自动写入业务库')

      replayed = { ...previewRun(replayed.id), details }
      await vi.advanceTimersByTimeAsync(1200)
      await flushPromises()
      expect(etlApiMock.rows).toHaveBeenCalledWith(replayed.id, 1, 50, '')
      expect(etlApiMock.execute).not.toHaveBeenCalled()
      expect(buttonByText(wrapper, '写入数据库')!.attributes('disabled')).toBeDefined()
      await wrapper.find('.etl-alert--warning input[type="checkbox"]').setValue(true)
      await buttonByText(wrapper, '写入数据库')!.trigger('click')
      await flushPromises()
      expect(etlApiMock.execute).toHaveBeenCalledExactlyOnceWith(replayed.id, 'a'.repeat(64), true)
    } finally {
      wrapper.unmount()
    }
  })

  it.each([
    { ...completedRun(), details: {} },
    { ...completedRun(), details: { source_snapshot: { version: 2 } } },
    { ...queuedRun('loading-run', 'input.csv'), details: { source_snapshot: { version: 1 } } },
  ])('does not offer reprocessing without an available, idle source snapshot', async (run) => {
    etlApiMock.run.mockResolvedValue(run)
    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '运行历史')!.trigger('click')
    expect(buttonByText(wrapper, '重新处理')).toBeUndefined()
    wrapper.unmount()
  })


  it('clears the no-writable-rows warning after an allowed-field change is revalidated', async () => {
    vi.useFakeTimers()
    const skipped = { ...previewRun('duplicate-file'), summary: { new: 0, update: 0, skip: 3, error: 0, executed: 0 } }
    let latest = skipped
    etlApiMock.upload.mockResolvedValue({ upload_id: skipped.upload_id })
    etlApiMock.preview.mockResolvedValue(skipped)
    etlApiMock.run.mockImplementation(async () => latest)
    etlApiMock.runs.mockImplementation(async () => [latest])
    etlApiMock.patchDraft.mockImplementation(async (_id: string, draft: Record<string, unknown>) => {
      latest = { ...latest, status: 'previewing', stage: 'validating', draft: { ...latest.draft, ...draft } }
      return latest
    })
    const wrapper = await mountView(skipped.id)
    try {
      expect(buttonByText(wrapper, '写入数据库')?.attributes('disabled')).toBeDefined()
      expect(etlApiMock.execute).not.toHaveBeenCalled()

      await buttonByText(wrapper, '字段映射')?.trigger('click')
      await wrapper.find('input[type="checkbox"][value="address"]').setValue(true)
      await buttonByText(wrapper, '保存并重新校验')?.trigger('click')
      await flushPromises()
      expect(etlApiMock.patchDraft).toHaveBeenCalledWith(skipped.id, expect.objectContaining({ allowed_update_fields: ['address'] }))
      latest = { ...latest, status: 'preview_ready', stage: 'preview_ready', summary: { new: 0, update: 1, skip: 2, error: 0, executed: 0 } }
      await vi.advanceTimersByTimeAsync(1200)
      await flushPromises()

      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      expect(buttonByText(wrapper, '写入数据库')?.attributes('disabled')).toBeUndefined()
      expect(etlApiMock.execute).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
    }
  })


  it('keeps a ready shipment in review and requires an explicit valid-row policy and confirmation', async () => {
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
          {
            sheet: '侯雪梅',
            role: 'delivery_note_template_and_records',
            status: 'included',
            rows: 6,
          },
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
    etlApiMock.execute.mockResolvedValue({
      ...shipment,
      status: 'executing',
      stage: 'executing',
      summary: { ...shipment.summary, executed: 1 },
    })
    etlApiMock.run.mockResolvedValue(shipment)
    etlApiMock.runs.mockResolvedValue([shipment])
    const wrapper = await mountView(shipment.id)

    expect(etlApiMock.execute).not.toHaveBeenCalled()
    expect(buttonByText(wrapper, '写入数据库')?.attributes('disabled')).toBeDefined()
    const validRows = wrapper.findAll('input[type="checkbox"]').find(input => input.element.parentElement?.textContent?.includes('仅处理正确行'))!
    expect((validRows.element as HTMLInputElement).checked).toBe(false)
    await validRows.setValue(true)
    vi.mocked(window.confirm).mockReturnValueOnce(false)
    await buttonByText(wrapper, '写入数据库')?.trigger('click')
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    await buttonByText(wrapper, '写入数据库')?.trigger('click')
    await flushPromises()
    expect(window.confirm).toHaveBeenLastCalledWith(expect.stringContaining('排除 1 行错误'))
    expect(etlApiMock.execute).toHaveBeenCalledWith(shipment.id, shipment.preview_revision, true)
    expect(wrapper.text()).toContain('运行历史')
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
    expect(wrapper.findAll('tbody tr')[0].find('textarea').exists()).toBe(false)
    await transformSelect.setValue('custom')
    expect((wrapper.findAll('textarea[aria-label="安全转换 JSON"]')[0].element as HTMLTextAreaElement).value).toBe('[{"op":"trim"}]')

    const transformEditors = wrapper.findAll('textarea[aria-label="安全转换 JSON"]')
    await transformEditors[1].setValue('{}')
    await buttonByText(wrapper, '保存并重新校验')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('address 的转换规则必须是 JSON 数组')
    expect(etlApiMock.patchDraft).not.toHaveBeenCalled()

    await transformEditors[1].setValue('[{"op":"trim"}]')
    const ocrCheckbox = wrapper
      .findAll('input[type="checkbox"]')
      .find((input) => input.element.parentElement?.textContent?.includes('OCR 表格位置'))
    await ocrCheckbox?.setValue(true)
    const addressCheckbox = wrapper
      .findAll('input[type="checkbox"]')
      .find((input) => input.element.parentElement?.textContent?.includes('地址'))
    await addressCheckbox?.setValue(true)
    await buttonByText(wrapper, '保存并重新校验')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.patchDraft).toHaveBeenCalledWith(
      run.id,
      expect.objectContaining({
        allowed_update_fields: ['address'],
        ocr_confirmed: true,
      }),
    )

    await buttonByText(wrapper, '保存个人模板')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.createTemplate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: '客户产品模板',
        target_type: 'customer_products',
      }),
    )

    const validRowsCheckbox = wrapper
      .findAll('input[type="checkbox"]')
      .find((input) => input.element.parentElement?.textContent?.includes('仅处理正确行'))
    await validRowsCheckbox?.setValue(true)
    await buttonByText(wrapper, '写入数据库')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.execute).toHaveBeenCalledWith(run.id, run.preview_revision, true)
    expect(wrapper.text()).toContain('运行历史')
    wrapper.unmount()
  })

  it('applies deterministic row overrides and shows only the selected action rows', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.patchDraft.mockResolvedValue(run)
    const rows = previewRows()
    etlApiMock.rows.mockImplementation(async (_id: string, page: number, pageSize: number, action = '') => {
      const items = action ? rows.filter((row) => row.final_action === action) : rows
      return { page, page_size: pageSize, total: items.length, items, preview_revision: run.preview_revision }
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
    expect(wrapper.text()).toContain('软件 LLM 已参与结构或字段建议')
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
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('')

    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '保存发货单版式')?.trigger('click')
    await flushPromises()

    expect(prompt).toHaveBeenCalledWith('发货单版式名称（可选；留空将按识别到的客户命名）', '')
    expect(etlApiMock.saveShipmentTemplate).toHaveBeenCalledWith(run.id, '', '')
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

    expect(etlApiMock.saveShipmentTemplate).toHaveBeenCalledWith(run.id, '金汉武专用打印版式', '')
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

    expect(etlApiMock.saveShipmentTemplate).toHaveBeenCalledWith(run.id, '', '侯雪梅!R29C1:10')
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
    etlApiMock.run.mockImplementation(async (id: string) => (id === shipment.id ? shipment : linked))

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
    expect(wrapper.text()).toContain('这是同一上传文件自动建立的客户及产品导入任务')
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
    await buttonByText(wrapper, '重新校验')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.retry).toHaveBeenCalledWith(failed.id)
    wrapper.unmount()
  })

  it.each(['denied', 'unavailable'] as const)('keeps rollback disabled when effective permission is %s', async (permission) => {
    if (permission === 'denied') {
      currentUserMock.mockResolvedValue({ success: true, data: { permissions: ['etl.read', 'etl.execute'] } })
    } else {
      currentUserMock.mockRejectedValue(new Error('permission service offline'))
    }
    const completed = completedRun()
    etlApiMock.run.mockResolvedValue(completed)
    const wrapper = await mountView(completed.id)
    try {
      expect(buttonByText(wrapper, '撤销本次写入')?.attributes('disabled')).toBeDefined()
      expect(wrapper.text()).toContain(permission === 'denied' ? '需要管理员授予撤销权限' : '暂时无法确认撤销权限')
      await buttonByText(wrapper, '撤销本次写入')?.trigger('click')
      expect(etlApiMock.rollback).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
    }
  })

  it('hides write controls for a tenant member with ETL read permission only', async () => {
    currentUserMock.mockResolvedValue({ success: true, data: { permissions: ['etl.read'] } })
    const run = completedRun()
    etlApiMock.run.mockResolvedValue(run)
    const wrapper = await mountView(run.id)
    try {
      expect(buttonByText(wrapper, '选择文件')).toBeUndefined()
      expect(buttonByText(wrapper, '写入数据库')).toBeUndefined()
      expect(buttonByText(wrapper, '保存个人模板')).toBeUndefined()
      expect(buttonByText(wrapper, '撤销本次写入')?.attributes('disabled')).toBeDefined()
    } finally {
      wrapper.unmount()
    }
  })

  it('replaces a failed rollback warning and reports the completed rollback in list, history, and receipt', async () => {
    const completed = completedRun('rollback-file')
    const rolledBack = { ...completed, rollback_status: 'completed', receipt: { rollback: { status: 'completed', rows: 3 } } }
    let latest: EtlRun = completed
    etlApiMock.upload.mockResolvedValue({ upload_id: completed.upload_id })
    etlApiMock.preview.mockResolvedValue(completed)
    etlApiMock.run.mockImplementation(async () => latest)
    etlApiMock.runs.mockImplementation(async () => [latest])
    etlApiMock.rollback.mockRejectedValueOnce(new Error('当前账号没有撤销权限，请联系管理员授权后重试。')).mockImplementationOnce(async () => {
      latest = rolledBack
      return latest
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = await mountView(completed.id)
    try {
      await buttonByText(wrapper, '撤销本次写入')?.trigger('click')
      await flushPromises()
      expect(wrapper.find('[role="alert"]').text()).toContain('没有撤销权限')
      await buttonByText(wrapper, '撤销本次写入')?.trigger('click')
      await flushPromises()

      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      expect(wrapper.find('.etl-history').text()).toContain('已撤销')
      expect(wrapper.find('.etl-receipt').text()).toContain('已撤销本次写入；已回退 3 行')
      expect(wrapper.find('.etl-receipt').text()).not.toContain('已关联写入客户库和产品库')
      expect(etlApiMock.rollback).toHaveBeenCalledTimes(2)
    } finally {
      wrapper.unmount()
    }
  })


  it('surfaces bootstrap failures and retries without losing the page', async () => {
    etlApiMock.capabilities.mockRejectedValueOnce(new Error('能力加载失败'))
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('能力加载失败')
    await buttonByText(wrapper, '重试')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.capabilities).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('这里只处理已有导入任务')
    expect(wrapper.text()).not.toContain('能力加载失败')
    wrapper.unmount()
  })
  it('clears stale row data and ignores run actions when no run is selected', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as any
    vm.runRows = previewRows()
    vm.rowTotal = 3
    vm.runsApi.syncDraft()
    await vm.loadRows()
    await vm.overrideRow(previewRows()[0], { target: { value: 'skip' } })
    await vm.bulkOverride('new')
    await vm.executeCurrentRun()
    await vm.retryRun()
    await vm.rollbackRun()
    expect(vm.runRows).toEqual([])
    expect(vm.rowTotal).toBe(0)
    for (const method of ['rows', 'patchDraft', 'execute', 'retry', 'rollback']) expect(etlApiMock[method]).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['overrideRow', 'patchDraft', '逐行动作保存失败'], ['bulkOverride', 'patchDraft', '批量动作保存失败'],
    ['executeCurrentRun', 'execute', '执行失败'], ['retryRun', 'retry', '重试失败'],
  ])('keeps %s retryable after API failures', async (action, method, fallback) => {
    const wrapper = await mountView()
    const vm = wrapper.vm as any
    const run = previewRun()
    if (action === 'retryRun') run.status = 'failed'
    vm.currentRun = run
    vm.runsApi.syncDraft()
    await vm.loadRows()
    vm.validRowsOnly = true
    vm.runRows = previewRows()
    etlApiMock.run.mockRejectedValue(new Error('readback offline'))
    for (const error of [new Error('operation offline'), 'offline']) {
      etlApiMock[method].mockRejectedValueOnce(error)
      await vm[action](...(action === 'overrideRow' ? [previewRows()[0], { target: { value: 'skip' } }] : action === 'bulkOverride' ? ['new'] : []))
      expect(vm.pageError).toBe(error instanceof Error ? 'operation offline' : fallback)
      expect(vm.busy).toBe(false)
      expect(vm.currentRun.id).toBe(run.id)
    }
    wrapper.unmount()
  })

  it('blocks execution when row readback and run details belong to different preview revisions', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.rows.mockResolvedValue({ items: previewRows(), total: 3, preview_revision: 'b'.repeat(64) })
    const wrapper = await mountView(run.id)
    const vm = wrapper.vm as any
    vm.validRowsOnly = true
    await vm.executeCurrentRun()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    expect(window.confirm).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('requires a new review and error-row choice after the preview revision changes', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    const wrapper = await mountView(run.id)
    const vm = wrapper.vm as any
    vm.validRowsOnly = true
    vm.currentRun = { ...run }
    await flushPromises()
    expect(vm.validRowsOnly).toBe(true)
    expect(vm.state.reviewedPreviewRevision.value).toBe(run.preview_revision)
    vm.currentRun = { ...run, preview_revision: 'b'.repeat(64) }
    await flushPromises()
    expect(vm.validRowsOnly).toBe(false)
    await vm.executeCurrentRun()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    etlApiMock.rows.mockResolvedValue({ items: previewRows(), total: 3, preview_revision: 'b'.repeat(64) })
    await vm.loadRows()
    vm.validRowsOnly = true
    etlApiMock.execute.mockResolvedValue({ ...run, status: 'executing' })
    await vm.executeCurrentRun()
    expect(etlApiMock.execute).toHaveBeenCalledWith(run.id, 'b'.repeat(64), true)
    wrapper.unmount()
  })

  it('does not write with unsaved mapping changes or without a preview revision', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    const wrapper = await mountView(run.id)
    const vm = wrapper.vm as any
    vm.validRowsOnly = true
    vm.mappingUiTransformJson['0'] = '[{"op":"trim"}]'
    await vm.executeCurrentRun()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    vm.runsApi.syncDraft()
    vm.currentRun = { ...run, preview_revision: null }
    await vm.executeCurrentRun()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    expect(window.confirm).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not write empty bulk selections, reread an unchanged filter, or execute an invalid preview', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as any
    vm.currentRun = previewRun()
    await vm.bulkOverride('new')
    await vm.bulkOverride('skip')
    await vm.setRowActionFilter('')
    await vm.executeCurrentRun()
    expect(etlApiMock.patchDraft).not.toHaveBeenCalled()
    expect(etlApiMock.rows).not.toHaveBeenCalled()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    vm.currentRun.total_rows = 0
    await vm.loadRows()
    expect(vm.rowTotal).toBe(0)
    vm.targetType = 'removed-target'
    await vm.bootstrap()
    expect(vm.targetType).toBe('auto')
    wrapper.unmount()
  })

  it.each([true, false])('stops rollback when permission or confirmation is missing: permission=%s', async (permitted) => {
    if (!permitted) currentUserMock.mockResolvedValue({ success: true, data: { permissions: ['etl.read'] } })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = await mountView()
    const vm = wrapper.vm as any
    vm.currentRun = completedRun()
    await vm.rollbackRun()
    expect(etlApiMock.rollback).not.toHaveBeenCalled()
    expect(confirm).toHaveBeenCalledTimes(permitted ? 1 : 0)
    if (!permitted) expect(vm.pageError).toContain('没有撤销权限')
    wrapper.unmount()
  })

  it('stops an obsolete poll and keeps read failures visible until retried', async () => {
    vi.useFakeTimers()
    const wrapper = await mountView()
    const vm = wrapper.vm as any
    vm.currentRun = queuedRun('poll', 'data.csv')
    vm.runsApi.schedulePoll()
    vm.currentRun = null
    await vi.advanceTimersByTimeAsync(1200)
    expect(etlApiMock.run).not.toHaveBeenCalled()
    for (const error of [new Error('read offline'), 'offline']) {
      vm.currentRun = queuedRun('poll', 'data.csv')
      etlApiMock.run.mockRejectedValueOnce(error)
      vm.runsApi.schedulePoll()
      await vi.advanceTimersByTimeAsync(1200)
      expect(vm.pageError).toBe(error instanceof Error ? error.message : '读取运行进度失败')
    }
    wrapper.unmount()
  })


  it('does not replace the selected task with an obsolete linked-preview response', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as any
    vm.currentRun = { ...previewRun('shipment'), target_type: 'shipment_records', details: { linked_customer_products_preview: { run_id: 'linked-old' } } }
    let resolveOld!: (run: EtlRun) => void
    etlApiMock.run.mockReturnValueOnce(new Promise<EtlRun>(resolve => { resolveOld = resolve }))
    const old = vm.previewCustomerProductsFromShipment()
    etlApiMock.run.mockResolvedValueOnce(previewRun('history-new'))
    await vm.selectRun(previewRun('history-new'))
    resolveOld(previewRun('linked-old'))
    await old
    expect(vm.currentRun.id).toBe('history-new')
    wrapper.unmount()
  })

  it('ignores a saved-layout readback after a different task is selected', async () => {
    const wrapper = await mountView()
    const vm = wrapper.vm as any
    vm.currentRun = { ...previewRun('shipment-old'), target_type: 'shipment_records' }
    vi.spyOn(window, 'prompt').mockReturnValue('')
    etlApiMock.saveShipmentTemplate.mockResolvedValue({ name: 'Synthetic layout', message: 'saved' })
    let resolveOld!: (run: EtlRun) => void
    etlApiMock.run.mockReturnValueOnce(new Promise<EtlRun>(resolve => { resolveOld = resolve }))
    const old = vm.saveCurrentAsShipmentTemplate()
    await flushPromises()
    etlApiMock.run.mockResolvedValueOnce(previewRun('history-new'))
    await vm.selectRun(previewRun('history-new'))
    resolveOld(previewRun('shipment-old'))
    await old
    expect(vm.currentRun.id).toBe('history-new')
    wrapper.unmount()
  })


  it('expands every field of each new record without losing zero, false or nested values', async () => {
    const run = previewRun()
    const records = [0, 210].map((amount, index) => ({
      ...previewRows()[0], id: index + 1, source_row: index + 2,
      source: { customer: '测试客户', product: `产品${index}`, model: 'A', quantity: 2, unit: '件', amount, active: false, terms: { tax: 0 } },
      normalized: { customer: '测试客户', product: `产品${index}`, model: 'A', quantity: 2, unit: '件', amount, active: false, terms: { tax: 0 } },
    }))
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.rows.mockResolvedValue({ page: 1, page_size: 50, total: 2, items: records, preview_revision: run.preview_revision })
    const wrapper = await mountView(run.id)
    const rows = wrapper.findAll('.etl-table-wrap tbody tr')
    expect(rows).toHaveLength(2)
    for (const [index, row] of rows.entries()) {
      const details = row.findAll('.etl-record-fields')
      expect(details).toHaveLength(2)
      for (const detail of details) {
        expect(detail.get('summary').text()).toContain('另有 3 项')
        expect((detail.element as HTMLDetailsElement).open).toBe(false)
        ;(detail.get('summary').element as HTMLElement).click()
        expect((detail.element as HTMLDetailsElement).open).toBe(true)
        expect(detail.findAll('dd').map(item => item.text())).toEqual(['测试客户', `产品${index}`, 'A', '2', '件', String(index ? 210 : 0), 'false', '{"tax":0}'])
      }
    }
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each(['failed', 'interrupted', 'outcome_unknown'])('shows confirmed results and safe next steps for %s in history', async status => {
    const run = {
      ...previewRun(), status, summary: { new: 100, update: 0, skip: 0, error: 0, executed: 37 },
      error: { code: status === 'outcome_unknown' ? 'ETL_OUTCOME_UNKNOWN' : 'WRITE_FAILED', message: '第 38 行处理未完成，请核对结果' },
    }
    etlApiMock.run.mockResolvedValue(run)
    const wrapper = await mountView(run.id)
    const receipt = wrapper.get('.etl-receipt')
    expect(receipt.text()).toContain('已确认写入 37 行')
    expect(receipt.get('[role="alert"]').text()).toContain(run.error.message)
    expect(receipt.text()).not.toContain('未写入 63')
    if (status === 'outcome_unknown') {
      expect(receipt.text()).toContain('结果待核对')
      expect(buttonByText(wrapper, '重新校验')).toBeUndefined()
      expect(buttonByText(wrapper, '撤销本次写入')).toBeUndefined()
      await (wrapper.vm as any).retryRun()
      await (wrapper.vm as any).rollbackRun()
      expect(etlApiMock.retry).not.toHaveBeenCalled()
      expect(etlApiMock.rollback).not.toHaveBeenCalled()
    } else {
      expect(receipt.text()).toContain('63 行结果待核对')
      expect(receipt.text()).toContain('重新校验只生成预演')
    }
    wrapper.unmount()
  })

  it('distinguishes manual skips, matched records and rule exclusions', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.rows.mockResolvedValue({ page: 1, page_size: 50, total: 3, preview_revision: run.preview_revision, items: [
      { ...previewRows()[0], final_action: 'skip', action_overridden: true },
      { ...previewRows()[0], id: 2, final_action: 'skip', match_ref: 'product:42' },
      { ...previewRows()[0], id: 3, final_action: 'skip', suggested_action: 'skip' },
    ] })
    const wrapper = await mountView(run.id)
    const reasons = wrapper.findAll('.etl-table-wrap tbody tr').map(row => row.findAll('td')[4].text())
    expect(reasons).toEqual(['用户主动跳过（原建议：新增）', '已匹配现有记录，默认跳过', '按规则跳过；具体原因请查看原建议'])
    wrapper.unmount()
  })

  it.each([
    ['customer_products', '写入数据库', '已写入'], ['export_xlsx', '生成 Excel 文件', '文件已生成'],
    ['export_csv', '生成 CSV 文件', '文件已生成'], ['webhook', '发送到外部系统', '发送完成'],
  ])('names the reviewed %s action and result consistently', async (target, action, done) => {
    const run = { ...previewRun(), target_type: target, reversible: target === 'customer_products',
      summary: { new: 1, update: 0, skip: 0, error: 0, executed: 0 },
      draft: { ...previewRun().draft, target_config_id: target === 'webhook' ? 'webhook-1' : undefined } }
    const completed = { ...run, status: 'completed', summary: { ...run.summary, executed: 1 } }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.execute.mockResolvedValue(completed)
    etlApiMock.runs.mockResolvedValue([completed])
    const wrapper = await mountView(run.id)
    await wrapper.get('[data-tutorial-id="etl-confirm"]').trigger('click')
    await flushPromises()
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining(`确认${action}`))
    if (!run.reversible) expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('不支持撤销'))
    if (target === 'webhook') expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('ERP 回调（https://example.com/hook）'))
    expect(wrapper.get('.etl-receipt').text()).toContain(done)
    expect(etlApiMock.execute).toHaveBeenCalledWith(run.id, run.preview_revision, false)
    wrapper.unmount()
  })

  it.each(['export_xlsx', 'export_csv', 'webhook'])('describes error-row handling without database-write wording for %s', async (target) => {
    const run = { ...previewRun(), target_type: target, reversible: false,
      summary: { new: 1, update: 0, skip: 0, error: 1, executed: 0 } }
    etlApiMock.run.mockResolvedValue(run)
    const wrapper = await mountView(run.id)
    const review = wrapper.get('[data-tutorial-id="etl-confirm"]').element.closest('section')!
    expect(review.textContent).toContain('仅处理正确行')
    expect(review.textContent).not.toContain('仅写入正确行')
    expect(wrapper.get('[data-tutorial-id="etl-confirm"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('offers source columns with samples and preserves advanced transforms until explicitly edited', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '字段映射')?.trigger('click')
    const input = wrapper.get('input[list="etl-source-columns"]')
    expect(wrapper.get('datalist').text()).toContain('国圣化工')
    expect(wrapper.findAll('datalist option').map(option => option.attributes('value'))).toContain('产品名称')
    await input.setValue('产品名称')
    await wrapper.findAll('tbody select')[0].setValue('number')
    expect(wrapper.findAll('tbody tr')[0].find('textarea').exists()).toBe(false)
    expect(wrapper.findAll('tbody tr')[1].get('textarea').element).toHaveProperty('value', '[{"op":"custom_lookup","table":"districts"}]')
    etlApiMock.patchDraft.mockResolvedValue(run)
    await buttonByText(wrapper, '保存并重新校验')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.patchDraft).toHaveBeenCalledWith(run.id, expect.objectContaining({ field_mappings: [
      expect.objectContaining({ source: '产品名称', transforms: [{ op: 'number' }] }),
      expect.objectContaining({ transforms: [{ op: 'custom_lookup', table: 'districts' }] }),
    ] }))
    wrapper.unmount()
  })

  it('jumps across 2000 server pages and locates a source row without loading the workbook', async () => {
    const run = { ...previewRun(), total_rows: 100_000 }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.rows.mockImplementation(async (_id, page, pageSize, _action, source) => ({
      page, page_size: pageSize, total: source ? 1 : 100_000, preview_revision: run.preview_revision,
      items: [{ ...previewRows()[0], source_row: source?.row || (page - 1) * 50 + 2 }],
    }))
    const wrapper = await mountView(run.id)
    await buttonByText(wrapper, '末页')?.trigger('click')
    await flushPromises()
    expect(etlApiMock.rows).toHaveBeenLastCalledWith(run.id, 2000, 50, '')
    await wrapper.get('.etl-pagination input').setValue(1200)
    await wrapper.get('.etl-pagination form').trigger('submit')
    await flushPromises()
    expect(etlApiMock.rows).toHaveBeenLastCalledWith(run.id, 1200, 50, '')
    await wrapper.get('.etl-source-location input[list]').setValue('报价明细')
    await wrapper.get('.etl-source-location input[type="number"]').setValue(99888)
    await wrapper.get('.etl-source-location').trigger('submit')
    await flushPromises()
    expect(etlApiMock.rows).toHaveBeenLastCalledWith(run.id, 1, 50, '', { sheet: '报价明细', row: 99888 })
    expect(wrapper.text()).toContain('99888')
    expect(etlApiMock.rows).toHaveBeenCalledTimes(4)
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('ignores obsolete page responses and never approves an empty or changed source location', async () => {
    const run = { ...previewRun(), total_rows: 100 }
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.rows.mockResolvedValue({ page: 1, page_size: 50, total: 100, items: previewRows(), preview_revision: run.preview_revision })
    const wrapper = await mountView(run.id)
    const vm = wrapper.vm as any
    let finishOld!: (value: unknown) => void
    etlApiMock.rows.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    const oldRead = vm.goToRowPage(2)
    vm.sourceRowInput = 99999
    etlApiMock.rows.mockResolvedValueOnce({ page: 1, page_size: 50, total: 0, items: [], preview_revision: run.preview_revision })
    await vm.locateSourceRow()
    finishOld({ page: 2, page_size: 50, total: 100, items: previewRows(), preview_revision: run.preview_revision })
    await oldRead
    expect(vm.runRows).toEqual([])
    expect(vm.state.reviewedPreviewRevision.value).toBeNull()
    await vm.executeCurrentRun()
    expect(etlApiMock.execute).not.toHaveBeenCalled()
    etlApiMock.rows.mockResolvedValueOnce({ page: 1, page_size: 50, total: 1, items: previewRows(), preview_revision: 'b'.repeat(64) })
    await vm.loadRows()
    expect(vm.runRows).toEqual([])
    expect(vm.pageError).toContain('预演内容已变化')
    wrapper.unmount()
  })

})
