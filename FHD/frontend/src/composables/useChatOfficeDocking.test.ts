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
}))

vi.mock('@/api/core', () => ({ primeCsrfCookie: mocks.primeCsrfCookie }))
vi.mock('@/utils/apiBase', () => ({ apiFetch: mocks.apiFetch }))
vi.mock('@/utils/officeEmployeeReadApi', () => ({
  isOfficeDockingFileSupported: mocks.isSupported,
  mapOfficeExcelReadToAnalysisResult: mocks.mapExcel,
  readOfficeEmployeeOutputs: mocks.readOutputs,
  resolveOfficeReadEmployeeForFile: mocks.resolveEmployee,
  runOfficeEmployeeRead: mocks.runEmployee,
  uploadChatOfficeFile: mocks.uploadFile,
}))

import {
  CSV_FULL_READ_EMPLOYEE_ID,
  EXCEL_FULL_READ_EMPLOYEE_ID,
  PPT_FULL_READ_EMPLOYEE_ID,
} from '@/constants/officeEmployeePack'
import { useChatOfficeDocking } from './useChatOfficeDocking'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

function fileEvent(file?: File): Event {
  const input = document.createElement('input')
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: file ? [file] : [],
  })
  return { target: input } as unknown as Event
}

function createHarness() {
  const deps = {
    addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
    stageExcelAnalysisContext: vi.fn(),
    sendDatabaseImportMessage: vi.fn().mockResolvedValue(undefined),
  }
  return { deps, docking: useChatOfficeDocking(deps) }
}

describe('useChatOfficeDocking', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.isSupported.mockReturnValue(true)
    mocks.primeCsrfCookie.mockResolvedValue(undefined)
    mocks.uploadFile.mockImplementation(async (file: File) => ({
      file_path: `/workspace/${file.name}`,
      workspace_root: '/workspace',
      filename: file.name,
    }))
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
          sheets: [
            { sheet_name: '送货单', row_count: 12 },
          ],
        },
      },
    ])
    mocks.mapExcel.mockReturnValue({
      fields: ['购货单位', '型号', '品名', '数量', '单价'],
      preview_data: {
        sheet_names: ['送货单'],
        sample_rows: [{ 购货单位: '甲公司', 型号: 'A1', 品名: '底漆', 数量: 2, 单价: 10 }],
      },
      sheets: [
        { sheet_name: '送货单', fields: ['购货单位', '型号', '品名', '数量', '单价'] },
      ],
    })
    mocks.apiFetch.mockImplementation(async (url: string) => {
      if (String(url).includes('/shipment-etl/preview')) {
        return jsonResponse({
          success: true,
          note_count: 1,
          message: '识别到 1 张送货单',
          notes: [{
            sheet_name: '送货单',
            unit_name: '甲公司',
            item_count: 2,
            total_amount: 20,
            items: [{ model_number: 'A1', product_name: '底漆', quantity: 2 }],
          }],
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

    docking.toggleOfficeDockingTarget(item.id, 'knowledge', false)
    await docking.confirmOfficeDockingReview()

    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/excel/data/shipment-etl/execute',
      expect.objectContaining({ method: 'POST' }),
    )
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

    docking.toggleOfficeDockingTarget('missing', 'knowledge', false)
    docking.toggleOfficeDockingTarget(item.id, 'knowledge', false)
    docking.toggleOfficeDockingTarget(item.id, 'knowledge', true)
    docking.toggleOfficeDockingTarget(item.id, 'database', false)
    docking.toggleOfficeDockingTarget(item.id, 'database', true)
    await docking.confirmOfficeDockingReview()

    expect(mocks.primeCsrfCookie).toHaveBeenCalled()
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/documents',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(deps.stageExcelAnalysisContext).toHaveBeenCalledWith(item.excelAnalysis)
    expect(deps.sendDatabaseImportMessage).toHaveBeenCalledWith('导入数据库，确认导入：客户产品.csv')
    expect(item.commitStatus).toBe('committed')
    expect(deps.addAndSaveMessage).toHaveBeenLastCalledWith(
      '[对接] 审核提交完成：成功 1 个。',
      'ai',
    )

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
    mocks.apiFetch.mockResolvedValue(
      jsonResponse({ success: true, data: { employee_rows: 3, department_rows: 1 } }),
    )

    const { docking } = createHarness()
    await docking.onOfficeDockingFileChange(fileEvent(new File(['xlsx'], '考勤转换结果.xlsx')))

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.intentId).toBe('attendance_roster')
    expect(item.databaseAction).toBe('attendance_import')
    expect(item.rowCount).toBe(4)
    docking.toggleOfficeDockingTarget(item.id, 'knowledge', false)
    await docking.confirmOfficeDockingReview()

    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/mod/taiyangniao-pro/attendance/import-workbook',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(item.commitStatus).toBe('committed')
    expect(item.summary).toBe('考勤入库完成：人员 3 条，部门 1 条')
  })

  it('handles unsupported input, trigger state, and failed knowledge ingestion', async () => {
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
    mocks.apiFetch.mockResolvedValue(jsonResponse({ success: false, message: '向量库不可用' }, 503))
    await docking.onOfficeDockingFileChange(fileEvent(new File(['pptx'], '复盘.pptx')))

    const item = docking.officeDockingReviewItems.value[0]
    expect(item.textPreview).toContain('第 1 页 进展')
    expect(item.intentId).toBe('document')
    await docking.confirmOfficeDockingReview()
    expect(item.commitStatus).toBe('failed')
    expect(item.error).toBe('向量库不可用')
    expect(deps.addAndSaveMessage).toHaveBeenLastCalledWith(
      '[对接] 审核提交完成：成功 0 个，失败 1 个。',
      'ai',
    )
  })
})
