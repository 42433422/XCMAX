import { describe, expect, it, vi } from 'vitest'
import {
  isOfficeExcelReadInstalled,
  mapOfficeExcelReadToAnalysisResult,
  summarizeOfficeExcelRead,
} from './officeEmployeeReadApi'

vi.mock('@/utils/platformShellApi', () => ({
  fetchEmployeePlannerStatus: vi.fn(),
}))

import { fetchEmployeePlannerStatus } from '@/utils/platformShellApi'

describe('officeEmployeeReadApi', () => {
  it('detects excel read employee when office_ready but office_installed_ids missing', async () => {
    vi.mocked(fetchEmployeePlannerStatus).mockResolvedValue({
      installed_employee_pack_count: 10,
      registered_tool_count: 10,
      registered_tool_names: ['excel-full-read-employee'],
      office_catalog_count: 10,
      office_installed_count: 10,
      office_installed_ids: [],
      missing_office_pack_ids: [],
      office_ready: true,
      runtime_missing_pack_ids: [],
    })
    await expect(isOfficeExcelReadInstalled(true)).resolves.toBe(true)
  })

  it('maps employee workbook payload to excel analysis result', () => {
    const upload = {
      file_path: 'uploads/chat/abc-test.xlsx',
      workspace_root: '/tmp/workspace',
      filename: 'test.xlsx',
    }
    const employeeData = {
      ok: true,
      items: [
        {
          sheet_count: 1,
          sheets: [
            {
              name: 'Sheet1',
              headers: [{ display: '姓名' }],
              rows: [{ cells: { 姓名: '张三' } }],
            },
          ],
        },
      ],
    }
    const result = mapOfficeExcelReadToAnalysisResult(upload, employeeData)
    expect(result.sheets?.[0]?.sheet_name).toBe('Sheet1')
    expect(result.preview_data?.file_path).toBe(upload.file_path)
    expect(summarizeOfficeExcelRead('test.xlsx', employeeData)).toContain('Excel 读取完成')
  })
})
