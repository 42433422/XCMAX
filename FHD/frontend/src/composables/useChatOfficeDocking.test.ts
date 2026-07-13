import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CSV_FULL_READ_EMPLOYEE_ID,
  EXCEL_FULL_READ_EMPLOYEE_ID,
  PDF_FULL_READ_EMPLOYEE_ID,
  PPT_FULL_READ_EMPLOYEE_ID,
  WORD_FULL_READ_EMPLOYEE_ID,
} from '@/constants/officeEmployeePack'
import {
  resolveOfficeDatabaseImportResult,
  useChatOfficeDocking,
} from './useChatOfficeDocking'

const mocks = vi.hoisted(() => ({
  primeCsrfCookie: vi.fn(),
  apiFetch: vi.fn(),
  isSupported: vi.fn(),
  mapExcel: vi.fn(),
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

function response(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

function deps() {
  return {
    addAndSaveMessage: vi.fn().mockResolvedValue(undefined),
    stageExcelAnalysisContext: vi.fn(),
    sendDatabaseImportMessage: vi.fn().mockResolvedValue({
      status: 'committed',
      reason: '后端已返回可核验的真实入库结果',
      action: 'workflow_done',
      affectedRows: 2,
    }),
  }
}

function inputEvent(file?: File): { event: Event; target: { files: File[]; value: string } } {
  const target = { files: file ? [file] : [], value: 'selected' }
  return { event: { target } as unknown as Event, target }
}

describe('useChatOfficeDocking', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.primeCsrfCookie.mockResolvedValue(undefined)
    mocks.apiFetch.mockResolvedValue(response({ success: true }))
    mocks.isSupported.mockImplementation((name: string) => !name.endsWith('.exe'))
    mocks.resolveEmployee.mockImplementation((name: string) => {
      if (name.endsWith('.csv')) return CSV_FULL_READ_EMPLOYEE_ID
      if (name.endsWith('.pdf')) return PDF_FULL_READ_EMPLOYEE_ID
      if (name.endsWith('.pptx')) return PPT_FULL_READ_EMPLOYEE_ID
      if (name.endsWith('.docx')) return WORD_FULL_READ_EMPLOYEE_ID
      if (name.endsWith('.xlsx')) return EXCEL_FULL_READ_EMPLOYEE_ID
      return ''
    })
    mocks.uploadFile.mockImplementation(async (file: File) => ({
      file_path: `/workspace/${file.name}`,
      workspace_root: '/workspace',
      filename: file.name,
    }))
    mocks.runEmployee.mockResolvedValue({
      summary: '办公员工读取完成',
      output_path: 'outputs/workbook.json',
      warnings: ['请复核金额'],
    })
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/workbook.json',
        kind: 'json',
        json: { sheets: [{ sheet_name: '报价', row_count: 2 }] },
      },
    ])
    mocks.mapExcel.mockReturnValue({
      fields: ['客户', '产品', '型号', '单价'],
      preview_data: {
        sheet_names: ['报价'],
        sample_rows: [{ 客户: '甲公司', 产品: '涂料' }],
      },
      sheets: [
        {
          sheet_name: '报价',
          fields: ['客户', '产品', '型号', '单价'],
        },
      ],
    })
  })

  it('reads an Excel file, infers customer/product data, and commits both targets', async () => {
    const external = deps()
    const docking = useChatOfficeDocking(external)
    const { event, target } = inputEvent(new File(['xlsx'], '客户产品报价.xlsx'))

    await docking.onOfficeDockingFileChange(event)

    expect(target.value).toBe('')
    expect(docking.officeDockingProcessing.value).toBe(false)
    expect(docking.officeDockingPendingCount.value).toBe(1)
    const item = docking.officeDockingReviewItems.value[0]
    expect(item.status).toBe('ready')
    expect(item.intentId).toBe('customer_product')
    expect(item.databaseAction).toBe('customer_product_import')
    expect(item.selectedDatabase).toBe(true)
    expect(item.fieldNames).toEqual(['客户', '产品', '型号', '单价'])
    expect(item.rowCount).toBe(2)
    expect(item.knowledgeText).toContain('客户产品报价.xlsx')

    await docking.confirmOfficeDockingReview()

    expect(item.commitStatus).toBe('committed')
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/knowledge/v1/ingest',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(external.stageExcelAnalysisContext).toHaveBeenCalledWith(item.excelAnalysis)
    expect(external.sendDatabaseImportMessage).toHaveBeenCalledWith(
      '导入数据库，确认导入：客户产品报价.xlsx',
    )
    expect(item.summary).toBe('客户/产品库入库完成：后端回执 2 条')
    expect(external.addAndSaveMessage).toHaveBeenLastCalledWith(
      '[对接] 审核提交结果：已完成 1 个。',
      'ai',
    )
  })

  it('does not mark a network failure as a customer/product database commit', async () => {
    const external = deps()
    external.sendDatabaseImportMessage.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    const docking = useChatOfficeDocking(external)

    await docking.onOfficeDockingFileChange(
      inputEvent(new File(['xlsx'], '客户产品报价.xlsx')).event,
    )
    const item = docking.officeDockingReviewItems.value[0]
    docking.toggleOfficeDockingTarget(item.id, 'knowledge', false)

    await docking.confirmOfficeDockingReview()

    expect(item.commitStatus).toBe('failed')
    expect(item.error).toBe('Failed to fetch')
    expect(external.addAndSaveMessage).toHaveBeenLastCalledWith(
      '[对接] 审核提交结果：已完成 0 个，失败 1 个。',
      'ai',
    )
  })

  it('keeps approval-pending imports pending and explicitly excludes them from success', async () => {
    const external = deps()
    external.sendDatabaseImportMessage.mockResolvedValueOnce({
      status: 'approval_pending',
      reason: '后端已生成写库计划，仍需用户确认；尚未实际入库',
      action: 'workflow_confirmation_required',
    })
    const docking = useChatOfficeDocking(external)

    await docking.onOfficeDockingFileChange(
      inputEvent(new File(['xlsx'], '客户产品报价.xlsx')).event,
    )
    const item = docking.officeDockingReviewItems.value[0]
    docking.toggleOfficeDockingTarget(item.id, 'knowledge', false)

    await docking.confirmOfficeDockingReview()

    expect(item.commitStatus).toBe('approval_pending')
    expect(item.summary).toContain('尚未实际入库')
    expect(docking.officeDockingPendingCount.value).toBe(0)
    expect(external.addAndSaveMessage).toHaveBeenLastCalledWith(
      '[对接] 审核提交结果：已完成 0 个，待确认/审批 1 个（不计为成功）。',
      'ai',
    )
  })

  it('classifies backend confirmation, explicit import success, and bubble-only success truthfully', () => {
    expect(resolveOfficeDatabaseImportResult({
      success: true,
      response: '回复“确认”继续执行',
      data: { action: 'workflow_confirmation_required' },
    })).toMatchObject({ status: 'approval_pending', action: 'workflow_confirmation_required' })

    expect(resolveOfficeDatabaseImportResult({
      success: true,
      response: 'Excel 导入完成',
      data: {
        action: 'workflow_done',
        data: {
          node_results: [
            { success: true, tool_id: 'excel_import', action: 'import_records' },
          ],
        },
      },
    })).toMatchObject({ status: 'committed', action: 'workflow_done' })

    expect(resolveOfficeDatabaseImportResult({
      success: true,
      response: '已经帮你导入完成',
    })).toMatchObject({ status: 'failed' })
  })

  it('routes attendance workbooks to the attendance import endpoint', async () => {
    mocks.mapExcel.mockReturnValue({
      fields: ['部门', '性质', '姓名'],
      preview_data: { sheet_names: ['明细', '月度统计'], sample_rows: [{ 姓名: '张三' }] },
      sheets: [{ sheet_name: '明细', fields: ['部门', '性质', '姓名'] }],
    })
    mocks.apiFetch.mockImplementation(async (url: string) => {
      if (url.includes('attendance/import-workbook')) {
        return response({ success: true, data: { employee_rows: 12, department_rows: 3 } })
      }
      return response({ success: true })
    })
    const docking = useChatOfficeDocking(deps())

    await docking.onOfficeDockingFileChange(
      inputEvent(new File(['xlsx'], '考勤转换结果.xlsx')).event,
    )
    const item = docking.officeDockingReviewItems.value[0]
    expect(item.intentId).toBe('attendance_roster')
    expect(item.databaseTargetLabel).toBe('考勤库')

    await docking.confirmOfficeDockingReview()

    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/mod/taiyangniao-pro/attendance/import-workbook',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(item.summary).toBe('考勤入库完成：人员 12 条，部门 3 条')
    expect(item.commitStatus).toBe('committed')
  })

  it('builds CSV analysis and lets the user deselect database import', async () => {
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/data.json',
        kind: 'json',
        json: {
          columns: ['客户', '产品', '型号', '价格'],
          rows: [{ 客户: '乙公司', 产品: '底漆', 型号: 'M1', 价格: 10 }],
          row_count: 8,
        },
      },
    ])
    const docking = useChatOfficeDocking(deps())

    await docking.onOfficeDockingFileChange(inputEvent(new File(['csv'], '报价.csv')).event)
    const item = docking.officeDockingReviewItems.value[0]
    expect(item.intentId).toBe('customer_product')
    expect(item.rowCount).toBe(8)
    expect(item.excelAnalysis?.excel_import_use_deterministic_shortcut).toBe(true)

    docking.toggleOfficeDockingTarget(item.id, 'database', false)
    expect(item.selectedDatabase).toBe(false)
    docking.toggleOfficeDockingTarget(item.id, 'knowledge', false)
    await docking.confirmOfficeDockingReview()
    expect(item.commitStatus).toBe('')
  })

  it('turns presentation output into knowledge text and supports clearing the review', async () => {
    mocks.readOutputs.mockResolvedValue([
      {
        path: 'outputs/presentation.json',
        kind: 'json',
        json: {
          title: '季度总结',
          slides: [
            { index: 1, title: '结果', texts: ['销售增长'], notes_generated: '复核数据' },
          ],
        },
      },
    ])
    const docking = useChatOfficeDocking(deps())

    await docking.onOfficeDockingFileChange(inputEvent(new File(['ppt'], '总结.pptx')).event)
    const item = docking.officeDockingReviewItems.value[0]
    expect(item.intentId).toBe('document')
    expect(item.textPreview).toContain('季度总结')
    expect(item.knowledgeText).toContain('销售增长')

    docking.clearOfficeDockingReview()
    expect(docking.officeDockingPanelOpen.value).toBe(false)
    expect(docking.officeDockingReviewItems.value).toEqual([])
  })

  it('handles unsupported and failed reads without leaving the composable busy', async () => {
    const external = deps()
    const docking = useChatOfficeDocking(external)
    const click = vi.fn()
    docking.officeDockingInputRef.value = { click } as unknown as HTMLInputElement
    docking.triggerOfficeDocking()
    expect(click).toHaveBeenCalledOnce()

    await docking.onOfficeDockingFileChange(inputEvent(new File(['bin'], 'tool.exe')).event)
    expect(docking.officeDockingReviewItems.value[0].status).toBe('error')

    mocks.uploadFile.mockRejectedValueOnce(new Error('上传失败'))
    await docking.onOfficeDockingFileChange(inputEvent(new File(['pdf'], 'broken.pdf')).event)
    expect(docking.officeDockingReviewItems.value[0]).toMatchObject({
      status: 'error',
      error: '上传失败',
    })
    expect(docking.officeDockingProcessing.value).toBe(false)
    expect(external.addAndSaveMessage).toHaveBeenCalledTimes(2)
  })
})
