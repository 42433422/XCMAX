import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  isSupported: vi.fn(),
  mapExcel: vi.fn(),
  primeCsrfCookie: vi.fn(),
  readOutputs: vi.fn(),
  resolveEmployee: vi.fn(),
  runEmployee: vi.fn(),
  uploadFile: vi.fn(),
  etlUpload: vi.fn(),
  etlPreview: vi.fn(),
  etlBatchAdvice: vi.fn(),
  etlRun: vi.fn(),
  etlExecute: vi.fn(),
  etlRollback: vi.fn(),
  etlSaveTemplate: vi.fn(),
  etlDeleteTemplate: vi.fn(),
}))

vi.mock('@/api/core', () => ({ primeCsrfCookie: mocks.primeCsrfCookie }))
vi.mock('@/utils/apiBase', () => ({ apiFetch: mocks.apiFetch }))
vi.mock('@/api/etl', () => ({
  etlApi: {
    upload: mocks.etlUpload,
    preview: mocks.etlPreview,
    batchAdvice: mocks.etlBatchAdvice,
    run: mocks.etlRun,
    execute: mocks.etlExecute,
    rollback: mocks.etlRollback,
    saveShipmentTemplate: mocks.etlSaveTemplate,
    deleteTemplate: mocks.etlDeleteTemplate,
  },
}))
vi.mock('@/utils/officeEmployeeReadApi', () => ({
  isOfficeDockingFileSupported: mocks.isSupported,
  mapOfficeExcelReadToAnalysisResult: mocks.mapExcel,
  readOfficeEmployeeOutputs: mocks.readOutputs,
  resolveOfficeReadEmployeeForFile: mocks.resolveEmployee,
  runOfficeEmployeeRead: mocks.runEmployee,
  uploadChatOfficeFile: mocks.uploadFile,
}))

import { CSV_FULL_READ_EMPLOYEE_ID, EXCEL_FULL_READ_EMPLOYEE_ID, PPT_FULL_READ_EMPLOYEE_ID } from '@/constants/officeEmployeePack'
import { useChatOfficeDocking } from './useChatOfficeDocking'
import type { EtlRun } from '@/api/etl'

const uploadedNames = new Map<string, string>()

function etlRun(overrides: Partial<EtlRun> = {}): EtlRun {
  const target = overrides.target_type || 'shipment_records'
  return {
    id: overrides.id || `${target}-run`,
    upload_id: overrides.upload_id || 'upload-1',
    file_name: overrides.file_name || '资料.xlsx',
    file_sha256: overrides.file_sha256 || 'sha',
    target_type: target,
    status: overrides.status || 'preview_ready',
    stage: overrides.stage || 'preview_ready',
    progress: overrides.progress ?? 100,
    total_rows: overrides.total_rows ?? 1,
    processed_rows: overrides.processed_rows ?? 1,
    summary: overrides.summary || { new: 1, update: 0, skip: 0, error: 0, executed: 0 },
    details: overrides.details || {},
    source_features: overrides.source_features || {},
    draft: overrides.draft || { field_mappings: [{ source: '购货单位', target: 'purchase_unit', transforms: [], confidence: 1, required: true }] },
    receipt: overrides.receipt || {},
    reversible: overrides.reversible ?? true,
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function fileEvent(file?: File | File[], options: { directory?: boolean } = {}): Event {
  const input = document.createElement('input')
  if (options.directory) input.setAttribute('webkitdirectory', '')
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: Array.isArray(file) ? file : file ? [file] : [],
  })
  return { target: input } as unknown as Event
}

function directoryFile(name: string, relativePath: string): File {
  const file = new File(['fixture'], name)
  Object.defineProperty(file, 'webkitRelativePath', {
    configurable: true,
    value: relativePath,
  })
  return file
}

function createHarness(mode: 'conversation' | 'review' = 'review') {
  const deps = {
    addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
    stageExcelAnalysisContext: vi.fn(),
    sendDatabaseImportMessage: vi.fn().mockResolvedValue(undefined),
  }
  return { deps, docking: useChatOfficeDocking({ ...deps, mode }) }
}

describe('useChatOfficeDocking', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    uploadedNames.clear()
    mocks.isSupported.mockReturnValue(true)
    mocks.primeCsrfCookie.mockResolvedValue(undefined)
    mocks.uploadFile.mockImplementation(async (file: File) => ({
      file_path: `/workspace/${file.name}`,
      workspace_root: '/workspace',
      filename: file.name,
    }))
    mocks.etlUpload.mockImplementation(async (file: File) => {
      const uploadId = `upload-${file.name}`
      uploadedNames.set(uploadId, file.name)
      return { upload_id: uploadId, file_name: file.name, sha256: `sha-${file.name}`, relative_path: file.name }
    })
    mocks.etlPreview.mockImplementation(async (body: { upload_id: string; target_type: string }) => {
      const fileName = uploadedNames.get(body.upload_id) || '资料.xlsx'
      if (body.target_type === 'knowledge') {
        return etlRun({
          id: `knowledge-${body.upload_id}`,
          upload_id: body.upload_id,
          file_name: fileName,
          target_type: 'knowledge',
          source_features: { kind: 'document', sheet_count: fileName.endsWith('.xlsx') ? 1 : 0, workbook_inventory: fileName.endsWith('.xlsx') ? [{ name: '送货单' }] : [] },
        })
      }
      return etlRun({
        id: `database-${body.upload_id}`,
        upload_id: body.upload_id,
        file_name: fileName,
        source_features: {
          target_detection: { confidence: 0.98, document_type: 'delivery_note_workbook' },
          llm_mapping: { used_llm: true, degraded: false },
          shipment_template_candidates: [{ name: `${fileName} · 发货单版式`, source_region_id: 'region-1' }],
        },
      })
    })
    mocks.etlRun.mockImplementation(async (id: string) => etlRun({ id }))
    mocks.etlBatchAdvice.mockResolvedValue({
      used_llm: true,
      degraded: false,
      model: 'xiaomi/mimo-v2.5',
      advice: {
        overall_judgment: '这批资料以发货单为主，应先保留原始证据，再谨慎同步高置信业务记录。',
        reasoning: ['重复内容只保留一份', '真实版式可以沉淀为模板'],
        cautions: ['有阻断错误的文件不要强行入库'],
        questions: ['是否要把低置信文件统一留在知识库？'],
      },
    })
    mocks.etlExecute.mockImplementation(async (id: string) => etlRun({ id, status: 'completed', stage: 'completed', summary: { new: 1, update: 0, skip: 0, error: 0, executed: 1 } }))
    mocks.etlRollback.mockImplementation(async (id: string) => etlRun({ id, status: 'completed', rollback_status: 'completed' }))
    mocks.etlSaveTemplate.mockResolvedValue({ template_id: 'etl:template-1', name: '版式', file_path: '/templates/one.xlsx', message: 'ok' })
    mocks.etlDeleteTemplate.mockResolvedValue(true)
    mocks.apiFetch.mockImplementation(async (url: string) => {
      if (String(url).includes('/shipment-etl/')) {
        return jsonResponse({ success: true, notes: [] })
      }
      return jsonResponse({ success: true })
    })
  })

  it('recognizes delivery-note workbooks via shipment ETL preview and executes closed loop', async () => {
    mocks.resolveEmployee.mockReturnValue(EXCEL_FULL_READ_EMPLOYEE_ID)
    mocks.runEmployee.mockResolvedValue({
      summary: '工作簿已读取',
      output_path: 'outputs/workbook.json',
    })
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/workbook.json',
        kind: 'json',
        json: {
          sheets: [{ sheet_name: '送货单', row_count: 12 }],
        },
      },
    ])
    mocks.mapExcel.mockReturnValue({
      fields: ['购货单位', '型号', '品名', '数量', '单价'],
      preview_data: {
        sheet_names: ['送货单'],
        sample_rows: [{ 购货单位: '甲公司', 型号: 'A1', 品名: '底漆', 数量: 2, 单价: 10 }],
      },
      sheets: [{ sheet_name: '送货单', fields: ['购货单位', '型号', '品名', '数量', '单价'] }],
    })
    mocks.apiFetch.mockImplementation(async (url: string) => {
      if (String(url).includes('/shipment-etl/preview')) {
        return jsonResponse({
          success: true,
          note_count: 1,
          message: '识别到 1 张送货单',
          notes: [
            {
              sheet_name: '送货单',
              unit_name: '甲公司',
              item_count: 2,
              total_amount: 20,
              items: [{ model_number: 'A1', product_name: '底漆', quantity: 2 }],
            },
          ],
        })
      }
      if (String(url).includes('/shipment-etl/execute')) {
        return jsonResponse({
          success: true,
          note_count: 1,
          shipment_created: 1,
          product_result: { success: true, imported: 1 },
        })
      }
      return jsonResponse({ success: true })
    })

    const { deps, docking } = createHarness()
    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '国圣送货单.xlsx')))

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.intentId).toBe('shipment_delivery')
    expect(item.databaseAction).toBe('shipment_etl_execute')
    expect(item.databaseTargetLabel).toBe('客户/产品/发货单')
    expect(item.shipmentEtlPreview?.note_count).toBe(1)
    expect(item.summary).toContain('送货单 1 张')
    expect(item.templateName).toBe('国圣送货单 · 发货单模板')
    expect(item.templateScope).toBe('orders')
    expect(mocks.apiFetch.mock.calls.some(([url]) => String(url) === '/api/templates/upload')).toBe(false)
    expect(mocks.apiFetch.mock.calls.some(([url]) => String(url).includes('/shipment-etl/execute'))).toBe(false)
    expect(deps.addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('[对接审核] 已阅读「国圣送货单.xlsx」'), 'ai')

    await docking.confirmOfficeDockingReview()

    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/templates/upload', expect.objectContaining({ method: 'POST' }))
    const templateUploadCall = mocks.apiFetch.mock.calls.find(([url]) => String(url) === '/api/templates/upload')
    const templateUploadBody = templateUploadCall?.[1]?.body as FormData
    expect(templateUploadBody.get('template_name')).toBe('国圣送货单 · 发货单模板')
    expect(templateUploadBody.get('template_scope')).toBe('orders')
    expect(templateUploadBody.get('source')).toBe('chat_office_docking_ai_advice')
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/excel/data/shipment-etl/execute', expect.objectContaining({ method: 'POST' }))
    expect(deps.stageExcelAnalysisContext).not.toHaveBeenCalled()
    expect(deps.sendDatabaseImportMessage).not.toHaveBeenCalled()
    expect(item.commitStatus).toBe('committed')
    expect(item.summary).toContain('送货单 ETL 完成')
  })

  it('reads a CSV, classifies customer/product data, and commits both targets', async () => {
    mocks.resolveEmployee.mockReturnValue(CSV_FULL_READ_EMPLOYEE_ID)
    mocks.runEmployee.mockResolvedValue({
      summary: 'CSV 已读取',
      output_path: 'outputs/data.json',
      warnings: ['列名已标准化'],
      items: [{ text_output_path: 'outputs/data.txt', warnings: ['空行已忽略'] }],
    })
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/data.json',
        kind: 'json',
        json: {
          columns: ['客户', '产品', '型号', '价格'],
          rows: [
            { 客户: '甲公司', 产品: '底漆', 型号: 'A1', 价格: 12.5 },
            { 客户: '乙公司', 产品: '面漆', 型号: 'B2', 价格: 18 },
          ],
          row_count: 2,
        },
      },
      { path: 'outputs/data.txt', kind: 'text', text: '甲公司 底漆 A1' },
    ])

    const { deps, docking } = createHarness()
    await docking.onOfficeDockingFileChange(fileEvent(new File(['csv'], '客户产品.csv')))

    expect(docking.officeDockingProcessing.value).toBe(false)
    expect(docking.officeDockingPendingCount.value).toBe(1)
    const item = docking.officeDockingReviewItems.value[0]
    expect(item.status).toBe('ready')
    expect(item.intentId).toBe('customer_product')
    expect(item.databaseAction).toBe('customer_product_import')
    expect(item.selectedDatabase).toBe(true)
    expect(item.rowCount).toBe(2)
    expect(item.fieldNames).toEqual(['客户', '产品', '型号', '价格'])
    expect(item.warnings).toEqual(['列名已标准化', '空行已忽略'])

    docking.toggleOfficeDockingTarget('missing', 'template', false)
    docking.toggleOfficeDockingTarget(item.id, 'template', false)
    docking.toggleOfficeDockingTarget(item.id, 'template', true)
    docking.updateOfficeDockingTemplateName(item.id, '客户产品 · 标准模板')
    docking.toggleOfficeDockingTarget(item.id, 'database', false)
    docking.toggleOfficeDockingTarget(item.id, 'database', true)
    await docking.confirmOfficeDockingReview()

    expect(mocks.primeCsrfCookie).toHaveBeenCalled()
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/templates/upload', expect.objectContaining({ method: 'POST' }))
    expect(deps.stageExcelAnalysisContext).toHaveBeenCalledWith(item.excelAnalysis)
    expect(deps.sendDatabaseImportMessage).toHaveBeenCalledWith('导入数据库，确认导入：客户产品.csv')
    expect(item.commitStatus).toBe('committed')
    expect(deps.addAndSaveMessage).toHaveBeenCalledWith('[对接] 「客户产品.csv」已处理到 模板库、客户/产品库。', 'ai')
    expect(deps.addAndSaveMessage).toHaveBeenLastCalledWith('[对接] 本批文件审核完成。', 'ai')

    item.commitStatus = 'failed'
    item.databaseCommitStatus = 'failed'
    mocks.apiFetch.mockClear()
    await docking.confirmOfficeDockingReview()
    expect(mocks.apiFetch.mock.calls.some(([url]) => String(url) === '/api/templates/upload')).toBe(false)
    expect(deps.sendDatabaseImportMessage).toHaveBeenCalledTimes(2)

    docking.clearOfficeDockingReview()
    expect(docking.officeDockingPanelOpen.value).toBe(false)
    expect(docking.officeDockingReviewItems.value).toEqual([])
  })

  it('recognizes an attendance workbook and writes it to the attendance database', async () => {
    mocks.resolveEmployee.mockReturnValue(EXCEL_FULL_READ_EMPLOYEE_ID)
    mocks.runEmployee.mockResolvedValue({
      summary: '工作簿已读取',
      output_path: 'outputs/workbook.json',
    })
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/workbook.json',
        kind: 'json',
        json: {
          sheets: [
            { sheet_name: '明细', row_count: 3 },
            { sheet_name: '月度统计', row_count: 1 },
          ],
        },
      },
    ])
    mocks.mapExcel.mockReturnValue({
      fields: ['部门', '姓名', '性质'],
      preview_data: {
        sheet_names: ['明细', '月度统计'],
        sample_rows: [{ 部门: '研发', 姓名: '张三', 性质: '正式' }],
      },
      sheets: [
        { sheet_name: '明细', fields: ['部门', '姓名', '性质'] },
        { sheet_name: '月度统计', fields: ['部门', '姓名'] },
      ],
    })
    mocks.apiFetch.mockResolvedValue(jsonResponse({ success: true, data: { employee_rows: 3, department_rows: 1 } }))

    const { docking } = createHarness()
    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '考勤转换结果.xlsx')))

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.intentId).toBe('attendance_roster')
    expect(item.databaseAction).toBe('attendance_import')
    expect(item.rowCount).toBe(4)
    await docking.confirmOfficeDockingReview()

    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/mod/taiyangniao-pro/attendance/import-workbook',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(item.commitStatus).toBe('committed')
    expect(item.summary).toBe('考勤入库完成：人员 3 条，部门 1 条')
  })

  it('handles unsupported input, trigger state, and failed template archiving', async () => {
    const { deps, docking } = createHarness()
    const click = vi.fn()
    docking.officeDockingInputRef.value = { click } as unknown as HTMLInputElement
    docking.triggerOfficeDocking()
    expect(click).toHaveBeenCalledTimes(1)
    docking.officeDockingProcessing.value = true
    docking.triggerOfficeDocking()
    expect(click).toHaveBeenCalledTimes(1)
    docking.officeDockingProcessing.value = false

    await docking.onOfficeDockingFileChange(fileEvent())
    expect(deps.addAndSaveMessage).not.toHaveBeenCalled()

    mocks.resolveEmployee.mockReturnValue('')
    mocks.isSupported.mockReturnValue(false)
    await docking.onOfficeDockingFileChange(fileEvent(new File(['raw'], 'notes.bin')))
    expect(docking.officeDockingReviewItems.value[0]).toMatchObject({
      status: 'error',
      error: '该文件类型未匹配到办公读取员工',
    })

    mocks.resolveEmployee.mockReturnValue(PPT_FULL_READ_EMPLOYEE_ID)
    mocks.isSupported.mockReturnValue(true)
    mocks.runEmployee.mockResolvedValue({ output_path: 'outputs/slides.json' })
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/slides.json',
        kind: 'json',
        json: {
          title: '季度复盘',
          slides: [{ index: 1, title: '进展', texts: ['完成发布'], notes_generated: '继续观察' }],
        },
      },
    ])
    mocks.apiFetch.mockResolvedValue(jsonResponse({ success: false, message: '模板服务不可用' }, 503))
    await docking.onOfficeDockingFileChange(fileEvent(new File(['pptx'], '复盘.pptx')))

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.textPreview).toContain('第 1 页 进展')
    expect(item.intentId).toBe('document')
    await docking.confirmOfficeDockingReview()
    expect(item.commitStatus).toBe('failed')
    expect(item.templateCommitStatus).toBe('failed')
    expect(item.error).toBe('模板服务不可用')
    expect(deps.addAndSaveMessage).toHaveBeenLastCalledWith('[对接] 「复盘.pptx」处理失败：模板服务不可用。请调整后重试或跳过。', 'ai')
  })

  it('selects a whole folder, ignores system files, and stages every supported file for review', async () => {
    mocks.isSupported.mockImplementation((name: string) => name.toLowerCase().endsWith('.xlsx'))
    mocks.resolveEmployee.mockReturnValue(EXCEL_FULL_READ_EMPLOYEE_ID)
    mocks.runEmployee.mockResolvedValue({
      summary: '工作簿已读取',
      output_path: 'outputs/workbook.json',
    })
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/workbook.json',
        kind: 'json',
        json: { sheets: [{ sheet_name: '送货单', row_count: 1 }] },
      },
    ])
    mocks.mapExcel.mockReturnValue({
      fields: ['购货单位', '品名', '型号', '数量'],
      preview_data: {
        sheet_names: ['送货单'],
        sample_rows: [{ 购货单位: '甲公司', 品名: '底漆', 型号: 'A1', 数量: 1 }],
      },
      sheets: [{ sheet_name: '送货单', fields: ['购货单位', '品名', '型号', '数量'] }],
    })

    const { deps, docking } = createHarness()
    const folderClick = vi.fn()
    docking.officeDockingFolderInputRef.value = { click: folderClick } as unknown as HTMLInputElement
    docking.triggerOfficeDockingFolder()
    expect(folderClick).toHaveBeenCalledTimes(1)

    const files = [
      directoryFile('国圣化工.xlsx', '发货单/国圣化工.xlsx'),
      directoryFile('侯雪梅.xlsx', '发货单/客户/侯雪梅.xlsx'),
      directoryFile('.DS_Store', '发货单/.DS_Store'),
    ]
    await docking.onOfficeDockingFileChange(fileEvent(files, { directory: true }))

    expect(mocks.uploadFile).toHaveBeenCalledTimes(2)
    expect(docking.officeDockingReviewItems.value.map((item) => item.fileName)).toEqual(['发货单/国圣化工.xlsx', '发货单/客户/侯雪梅.xlsx'])
    expect(docking.officeDockingReviewItems.value.every((item) => item.status === 'ready')).toBe(true)
    expect(docking.officeDockingReviewItems.value.every((item) => item.databaseAction === '')).toBe(true)
    expect(docking.officeDockingReviewItems.value.every((item) => item.databaseDisabledReason.includes('profile_target'))).toBe(true)
    expect(deps.addAndSaveMessage).toHaveBeenCalledWith(
      '已收到文件夹「发货单」中的 2 个可读取文件，另有 1 个文件已跳过（可在进度卡查看原因），现在开始阅读。',
      'ai',
    )
    expect(docking.officeDockingProgress.value).toMatchObject({
      phase: 'completed',
      total: 2,
      completed: 2,
      success: 2,
      failed: 0,
      percent: 100,
      ignored: [{ fileName: '发货单/.DS_Store', reason: '系统或临时文件' }],
    })
    expect(deps.addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('[对接审核] 已阅读「发货单/国圣化工.xlsx」'), 'ai')

    const [first, second] = docking.officeDockingReviewItems.value
    docking.toggleOfficeDockingTarget(first.id, 'database', false)
    docking.toggleOfficeDockingTarget(second.id, 'database', false)
    await docking.confirmOfficeDockingReview()

    expect(first.commitStatus).toBe('committed')
    expect(second.commitStatus).toBe('')
    expect(mocks.apiFetch.mock.calls.filter(([url]) => String(url) === '/api/templates/upload')).toHaveLength(1)
    expect(deps.addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('[对接审核] 已阅读「发货单/客户/侯雪梅.xlsx」'), 'ai')

    await docking.skipCurrentOfficeDockingReview()
    expect(second.commitStatus).toBe('skipped')
    expect(deps.addAndSaveMessage).toHaveBeenLastCalledWith('[对接] 本批文件审核完成。', 'ai')
  })

  it('reads the whole folder before offering one batch recommendation in chat', async () => {
    mocks.isSupported.mockImplementation((name: string) => name.toLowerCase().endsWith('.xlsx'))
    mocks.resolveEmployee.mockReturnValue(EXCEL_FULL_READ_EMPLOYEE_ID)
    mocks.runEmployee.mockResolvedValue({ summary: '工作簿已读取', output_path: 'outputs/workbook.json' })
    mocks.readOutputs.mockResolvedValue([
      { path: 'outputs/workbook.json', kind: 'json', json: { sheets: [{ sheet_name: '送货单', row_count: 1 }] } },
    ])
    mocks.mapExcel.mockReturnValue({
      fields: ['购货单位', '品名', '型号', '数量'],
      preview_data: {
        sheet_names: ['送货单'],
        sample_rows: [{ 购货单位: '甲公司', 品名: '底漆', 型号: 'A1', 数量: 1 }],
      },
      sheets: [{ sheet_name: '送货单', fields: ['购货单位', '品名', '型号', '数量'] }],
    })
    mocks.apiFetch.mockImplementation(async (url: string) => {
      if (String(url).includes('/shipment-etl/preview')) {
        return jsonResponse({
          success: true,
          note_count: 1,
          notes: [{ sheet_name: '送货单', unit_name: '甲公司', item_count: 1 }],
        })
      }
      if (String(url).includes('/shipment-etl/execute')) {
        return jsonResponse({ success: true, note_count: 1, shipment_created: 1, product_result: { imported: 1 } })
      }
      return jsonResponse({ success: true })
    })

    const { deps, docking } = createHarness('conversation')
    const files = [
      directoryFile('国圣化工.xlsx', '发货单/国圣化工.xlsx'),
      directoryFile('侯雪梅.xlsx', '发货单/客户/侯雪梅.xlsx'),
      directoryFile('.DS_Store', '发货单/.DS_Store'),
    ]
    await docking.onOfficeDockingFileChange(fileEvent(files, { directory: true }))

    expect(docking.officeDockingPanelOpen.value).toBe(false)
    expect(docking.officeDockingAwaitingDecision.value).toBe(true)
    expect(docking.officeDockingProgress.value).toMatchObject({ phase: 'completed', total: 2, completed: 2, percent: 100 })
    expect(deps.addAndSaveMessage).toHaveBeenCalledTimes(2)
    const batchMessage = String(deps.addAndSaveMessage.mock.calls[1][0])
    expect(batchMessage).toContain('文件夹「发货单」里的文件完整分析完了')
    expect(batchMessage).toContain('发货单/国圣化工.xlsx')
    expect(batchMessage).toContain('发货单/客户/侯雪梅.xlsx')
    expect(batchMessage).toContain('我的建议')
    expect(batchMessage).toContain('AI 综合意见')
    expect(batchMessage).toContain('这批资料以发货单为主')
    expect(batchMessage).toContain('xiaomi/mimo-v2.5')
    expect(batchMessage).toContain('你想怎么处理这批资料')
    expect(batchMessage).not.toContain('AI 对接建议')
    expect(batchMessage).not.toContain('逐个确认')
    const decisionExtras = deps.addAndSaveMessage.mock.calls[1][2] as {
      decisionOptions?: Array<Record<string, unknown>>
    }
    expect(decisionExtras.decisionOptions).toHaveLength(3)
    expect(decisionExtras.decisionOptions).toEqual([
      expect.objectContaining({ id: 'recommended', label: '按 AI 建议处理', message: '按建议处理', recommended: true }),
      expect.objectContaining({ id: 'knowledge-only', label: '仅进入知识库', message: '全部只进入知识库' }),
      expect.objectContaining({ id: 'custom', label: '自定义处理方式', composePrefill: '我想这样处理：' }),
    ])
    expect(mocks.etlSaveTemplate).not.toHaveBeenCalled()
    expect(mocks.etlExecute).not.toHaveBeenCalled()
    expect(mocks.etlBatchAdvice).toHaveBeenCalledTimes(1)
    expect(mocks.etlPreview).toHaveBeenCalledWith(expect.objectContaining({ llm_advice_enabled: false }))

    expect(await docking.handleOfficeDockingConversationDecision('你觉得呢？')).toBe(false)
    expect(await docking.handleOfficeDockingConversationDecision('按建议处理')).toBe(true)
    expect(deps.addAndSaveMessage).toHaveBeenLastCalledWith(expect.stringContaining('现在还没有执行；如果理解正确，请回复“确认执行”'), 'ai')
    expect(mocks.etlSaveTemplate).not.toHaveBeenCalled()
    expect(mocks.etlExecute).not.toHaveBeenCalled()

    expect(await docking.handleOfficeDockingConversationDecision('确认执行')).toBe(true)
    expect(mocks.etlSaveTemplate).toHaveBeenCalledTimes(2)
    expect(mocks.etlExecute).toHaveBeenCalledTimes(4)
    expect(docking.officeDockingReviewItems.value.every((item) => item.commitStatus === 'committed')).toBe(true)
    expect(docking.officeDockingAwaitingDecision.value).toBe(false)
  })

  it('deduplicates renamed files by server SHA-256 before creating previews', async () => {
    mocks.etlUpload.mockImplementation(async (file: File) => {
      const uploadId = `upload-${file.name}`
      uploadedNames.set(uploadId, file.name)
      return { upload_id: uploadId, file_name: file.name, sha256: 'same-content-sha', relative_path: file.name }
    })
    const { docking } = createHarness('conversation')

    await docking.onOfficeDockingFileChange(fileEvent([
      new File(['same'], '迎扬李总.xlsx'),
      new File(['same'], '迎扬李总(1).xlsx'),
    ]))

    expect(docking.officeDockingReviewItems.value).toHaveLength(1)
    expect(mocks.etlPreview).toHaveBeenCalledTimes(2)
    expect(docking.officeDockingProgress.value).toMatchObject({
      total: 1,
      completed: 1,
      ignored: [{ fileName: '迎扬李总(1).xlsx', reason: '内容与「迎扬李总.xlsx」完全相同' }],
    })
  })

  it('includes the linked customer-product preview when a shipment workbook has supporting sheets', async () => {
    mocks.etlPreview.mockImplementation(async (body: { upload_id: string; target_type: string }) => {
      if (body.target_type === 'knowledge') return etlRun({ id: 'knowledge-linked', target_type: 'knowledge' })
      return etlRun({
        id: 'shipment-primary',
        target_type: 'shipment_records',
        details: { linked_customer_products_preview: { run_id: 'customer-products-linked' } },
        source_features: { target_detection: { confidence: 0.98 } },
      })
    })
    mocks.etlRun.mockImplementation(async (id: string) =>
      etlRun({ id, target_type: id === 'customer-products-linked' ? 'customer_products' : 'shipment_records' }),
    )
    const { docking } = createHarness('conversation')

    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '混合发货资料.xlsx')))
    const item = docking.officeDockingReviewItems.value[0]
    expect(item.databaseRuns?.map((run) => run.id)).toEqual(['shipment-primary', 'customer-products-linked'])
    expect(item.summary).toContain('含客户/产品关系附表')

    await docking.handleOfficeDockingConversationDecision('按建议处理')
    await docking.handleOfficeDockingConversationDecision('确认执行')
    expect(mocks.etlExecute.mock.calls.map(([id]) => id)).toEqual([
      'customer-products-linked',
      'shipment-primary',
      'knowledge-linked',
    ])
  })

  it('shows cooperative cancellation and never offers execution options for an incomplete batch', async () => {
    mocks.isSupported.mockReturnValue(true)
    let finishUpload!: (value: Record<string, unknown>) => void
    mocks.etlUpload.mockImplementationOnce(
      (file: File) =>
        new Promise((resolve) => {
          finishUpload = resolve
          uploadedNames.set(`upload-${file.name}`, file.name)
        }),
    )

    const { deps, docking } = createHarness('conversation')
    const reading = docking.onOfficeDockingFileChange(fileEvent([new File(['a'], '第一份.xlsx'), new File(['b'], '第二份.xlsx')]))
    await vi.waitFor(() => expect(mocks.etlUpload).toHaveBeenCalledTimes(1))

    expect(docking.officeDockingProgress.value).toMatchObject({
      phase: 'inventory',
      total: 2,
      currentIndex: 1,
      currentFile: '第一份.xlsx',
    })
    docking.cancelOfficeDockingReading()
    expect(docking.officeDockingProgress.value?.phase).toBe('stopping')

    finishUpload({ upload_id: 'upload-第一份.xlsx', file_name: '第一份.xlsx', sha256: 'sha-first', relative_path: '第一份.xlsx' })
    await reading

    expect(docking.officeDockingProgress.value).toMatchObject({
      phase: 'cancelled',
      total: 1,
      completed: 0,
      success: 0,
    })
    expect(docking.officeDockingAwaitingDecision.value).toBe(false)
    expect(deps.addAndSaveMessage).toHaveBeenLastCalledWith(expect.stringContaining('已停止这次分析：完成 0/1 个'), 'ai')
    expect(deps.addAndSaveMessage.mock.calls.some((call) => call[2]?.decisionOptions)).toBe(false)
  })

  it('holds a low-confidence database target while still offering the knowledge preview', async () => {
    mocks.etlPreview.mockImplementation(async (body: { upload_id: string; target_type: string }) => {
      if (body.target_type === 'knowledge') return etlRun({ id: 'knowledge-low', target_type: 'knowledge' })
      return etlRun({
        id: 'database-low',
        target_type: 'customer_products',
        source_features: { target_detection: { confidence: 0.35, document_type: 'generic_structured_table' } },
      })
    })

    const { deps, docking } = createHarness('conversation')
    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '国圣化工.xlsx')))

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.intentId).toBe('customer_product')
    expect(item.databaseAction).toBe('universal_etl_execute')
    expect(item.selectedDatabase).toBe(false)
    expect(item.selectedKnowledge).toBe(true)
    expect(item.selectedTemplate).toBe(false)
    expect(item.databaseDisabledReason).toContain('置信度仅 35%')
    expect(String(deps.addAndSaveMessage.mock.calls[1][0])).toContain('置信度仅 35%')

    expect(await docking.handleOfficeDockingConversationDecision('按建议处理')).toBe(true)
    expect(await docking.handleOfficeDockingConversationDecision('确认执行')).toBe(true)
    expect(mocks.etlSaveTemplate).not.toHaveBeenCalled()
    expect(mocks.etlExecute).toHaveBeenCalledTimes(1)
    expect(mocks.etlExecute).toHaveBeenCalledWith('knowledge-low')
    expect(item.commitStatus).toBe('committed')
  })

  it('treats a drifted ETL receipt as failure and reports row reasons in chat', async () => {
    mocks.etlExecute.mockImplementation(async (id: string) => {
      if (id.startsWith('database-')) {
        return etlRun({
          id,
          status: 'completed',
          stage: 'completed',
          summary: { new: 2, update: 0, skip: 0, error: 0, executed: 2 },
          execution_integrity: {
            status: 'drifted',
            checked_rows: 2,
            failure_count: 2,
            failures: [
              {
                row_id: 21,
                source_sheet: '客户',
                source_row: 2,
                code: 'ETL_EXECUTION_TARGET_MISSING',
                message: '关联客户记录不存在',
              },
              {
                row_id: 22,
                source_sheet: '产品',
                source_row: 5,
                code: 'ETL_EXECUTION_RELATIONSHIP_BROKEN',
                message: '客户产品关系断裂',
              },
            ],
          },
        })
      }
      return etlRun({ id, status: 'completed', stage: 'completed' })
    })

    const { deps, docking } = createHarness('conversation')
    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '国圣化工.xlsx')))
    await docking.handleOfficeDockingConversationDecision('按建议处理')
    await docking.handleOfficeDockingConversationDecision('确认执行')

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.commitStatus).toBe('failed')
    expect(item.databaseCommitStatus).toBe('failed')
    expect(item.databaseError).toContain('客户 第 2 行：关联客户记录不存在')
    expect(item.databaseError).toContain('产品 第 5 行：客户产品关系断裂')
    const receipt = String(deps.addAndSaveMessage.mock.calls.at(-1)?.[0])
    expect(receipt).toContain('国圣化工.xlsx：失败')
    expect(receipt).toContain('客户 第 2 行：关联客户记录不存在')
    expect(receipt).toContain('产品 第 5 行：客户产品关系断裂')
  })

  it('rolls back a completed database run when the later knowledge write fails', async () => {
    mocks.etlExecute.mockImplementation(async (id: string) => {
      if (id.startsWith('knowledge-')) throw new Error('知识库索引服务暂不可用')
      return etlRun({ id, status: 'completed', stage: 'completed' })
    })

    const { deps, docking } = createHarness('conversation')
    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '国圣化工.xlsx')))
    await docking.handleOfficeDockingConversationDecision('按建议处理')
    await docking.handleOfficeDockingConversationDecision('确认执行')

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.commitStatus).toBe('failed')
    expect(item.databaseCommitStatus).toBe('rolled_back')
    expect(item.knowledgeCommitStatus).toBe('failed')
    expect(item.knowledgeError).toBe('知识库索引服务暂不可用')
    expect(mocks.etlRollback).toHaveBeenCalledWith(expect.stringContaining('database-upload-国圣化工.xlsx'))
    expect(mocks.etlSaveTemplate).not.toHaveBeenCalled()
    const receipt = String(deps.addAndSaveMessage.mock.calls.at(-1)?.[0])
    expect(receipt).toContain('国圣化工.xlsx：失败')
    expect(receipt).toContain('客户/产品/发货单已自动回滚')
    expect(receipt).toContain('知识库失败（知识库索引服务暂不可用）')
  })

  it('reports partial success and both reasons when a later template and its rollback fail', async () => {
    mocks.etlPreview.mockImplementation(async (body: { upload_id: string; target_type: string }) => {
      if (body.target_type === 'knowledge') return etlRun({ id: `knowledge-${body.upload_id}`, target_type: 'knowledge' })
      return etlRun({
        id: `database-${body.upload_id}`,
        source_features: {
          target_detection: { confidence: 0.98 },
          shipment_template_candidates: [
            { name: '版式一', source_region_id: 'region-1' },
            { name: '版式二', source_region_id: 'region-2' },
          ],
        },
      })
    })
    mocks.etlSaveTemplate
      .mockResolvedValueOnce({ template_id: 'etl:template-1', name: '版式一', file_path: '/templates/one.xlsx', message: 'ok' })
      .mockRejectedValueOnce(new Error('第二套模板保存失败'))
    mocks.etlDeleteTemplate.mockRejectedValue(new Error('模板回滚服务暂不可用'))

    const { deps, docking } = createHarness('conversation')
    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '国圣化工.xlsx')))
    await docking.handleOfficeDockingConversationDecision('按建议处理')
    await docking.handleOfficeDockingConversationDecision('确认执行')

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.commitStatus).toBe('partial')
    expect(item.templateCommitStatus).toBe('failed')
    expect(item.databaseCommitStatus).toBe('rolled_back')
    expect(item.knowledgeCommitStatus).toBe('rolled_back')
    expect(item.rollbackError).toContain('模板 etl:template-1：模板回滚服务暂不可用')
    const receipt = String(deps.addAndSaveMessage.mock.calls.at(-1)?.[0])
    expect(receipt).toContain('部分成功 1 个')
    expect(receipt).toContain('模板库失败（第二套模板保存失败）')
    expect(receipt).toContain('客户/产品/发货单已自动回滚')
    expect(receipt).toContain('知识库已自动回滚')
    expect(receipt).toContain('模板自动回滚失败')
  })

  it('supports a knowledge-only batch instruction without writing any business database or template', async () => {
    const { deps, docking } = createHarness('conversation')
    await docking.onOfficeDockingFileChange(fileEvent(new File(['pptx'], '培训.pptx')))

    expect(await docking.handleOfficeDockingConversationDecision('全部只进入知识库')).toBe(true)
    expect(await docking.handleOfficeDockingConversationDecision('确认执行')).toBe(true)
    expect(mocks.etlExecute).toHaveBeenCalledTimes(1)
    expect(mocks.etlExecute).toHaveBeenCalledWith(expect.stringContaining('knowledge-'))
    expect(mocks.etlSaveTemplate).not.toHaveBeenCalled()
    expect(deps.sendDatabaseImportMessage).not.toHaveBeenCalled()
  })
})
