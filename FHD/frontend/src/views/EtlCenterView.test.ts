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
    expect(wrapper.find('input[type="file"][multiple]').exists()).toBe(true)
    expect(wrapper.find('input[type="file"][webkitdirectory]').exists()).toBe(true)
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
    vi.spyOn(window, 'prompt').mockReturnValue('  客户产品模板  ')
    const wrapper = await mountView(run.id)

    expect(wrapper.text()).toContain('客户 → 产品关系')
    expect(wrapper.text()).toContain('OCR 第 2 页 · 表格行 7')
    expect(wrapper.text()).toContain('默认阻断整批')
    expect(buttonByText(wrapper, '确认执行')?.attributes('disabled')).toBeDefined()

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
    await buttonByText(wrapper, '确认执行')?.trigger('click')
    await flushPromises()

    expect(etlApiMock.execute).toHaveBeenCalledWith(run.id, true)
    expect(wrapper.text()).toContain('运行历史')
    wrapper.unmount()
  })

  it('applies deterministic row overrides and reloads the filtered preview', async () => {
    const run = previewRun()
    etlApiMock.run.mockResolvedValue(run)
    etlApiMock.patchDraft.mockResolvedValue(run)
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
