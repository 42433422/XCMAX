import { primeCsrfCookie } from '@/api/core'
import { EXCEL_FULL_READ_EMPLOYEE_ID, WORD_FULL_READ_EMPLOYEE_ID } from '@/constants/officeEmployeePack'
import type { ExcelAnalysisResult, ExcelFieldInfo, ExcelSheetDetail } from '@/types/excel'
import { apiFetch } from '@/utils/apiBase'
import { resolveOfficeInstalledPackIds } from '@/utils/officeToolDeskRows'
import { fetchEmployeePlannerStatus } from '@/utils/platformShellApi'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

const CHAT_OFFICE_UPLOAD = '/api/platform-shell/chat-office-file-upload'
const TUTORIAL_OFFICE_UPLOAD = '/api/platform-shell/office-sample-upload'
const WORKSPACE_ROOT_PATH = '/api/platform-shell/workspace-root'
const EXTRACT_GRID_UPLOAD_PATH = '/api/templates/extract-grid'

let cachedWorkspaceRoot = ''

async function resolveWorkspaceRoot(fromUpload?: string): Promise<string> {
  const direct = asString(fromUpload).trim()
  if (direct) return direct
  if (cachedWorkspaceRoot) return cachedWorkspaceRoot
  await ensureCsrf()
  const res = await apiFetch(WORKSPACE_ROOT_PATH)
  const body = await res.json().catch(() => ({}))
  const root = asString(asRecord(body?.data).workspace_root).trim()
  if (root) cachedWorkspaceRoot = root
  return root
}

async function uploadOfficeFile(file: File, endpoint: string): Promise<OfficeFileUploadResult> {
  await ensureCsrf()
  const fd = new FormData()
  fd.append('file', file)
  const res = await apiFetch(endpoint, { method: 'POST', body: fd })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.message || body?.error || `上传失败 HTTP ${res.status}`))
  }
  const data = asRecord(body?.data || body)
  const file_path = asString(data.file_path).trim()
  const workspace_root = await resolveWorkspaceRoot(asString(data.workspace_root))
  if (!file_path || !workspace_root) {
    throw new Error('上传成功但未返回 file_path / workspace_root')
  }
  return {
    file_path,
    workspace_root,
    filename: asString(data.filename || file.name).trim() || file.name,
  }
}

function isMissingPlatformShellUpload(err: unknown): boolean {
  const msg = String((err as Error)?.message || err || '')
  return /404|405|Not Found|Method Not Allowed/i.test(msg)
}

async function uploadViaExtractGrid(file: File): Promise<OfficeFileUploadResult> {
  await ensureCsrf()
  const fd = new FormData()
  fd.append('file', file)
  fd.append('analyze_all_sheets', 'false')
  const res = await apiFetch(EXTRACT_GRID_UPLOAD_PATH, { method: 'POST', body: fd })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.message || body?.detail || `上传失败 HTTP ${res.status}`))
  }
  const data = asRecord(body)
  const preview = asRecord(data.preview_data)
  const file_path = asString(data.file_path || preview.file_path).trim()
  const workspace_root = await resolveWorkspaceRoot(asString(data.workspace_root))
  if (!file_path || !workspace_root) {
    throw new Error('extract-grid 上传成功但未返回 file_path / workspace_root')
  }
  return {
    file_path,
    workspace_root,
    filename: asString(data.template_name || file.name).trim() || file.name,
  }
}

export async function uploadChatOfficeFile(file: File): Promise<OfficeFileUploadResult> {
  try {
    return await uploadOfficeFile(file, CHAT_OFFICE_UPLOAD)
  } catch (e) {
    if (!isMissingPlatformShellUpload(e)) throw e
    try {
      return await uploadOfficeFile(file, TUTORIAL_OFFICE_UPLOAD)
    } catch (e2) {
      if (!isMissingPlatformShellUpload(e2)) throw e2
      return uploadViaExtractGrid(file)
    }
  }
}

const EMPLOYEE_RUN_PATHS: Record<string, string> = {
  [EXCEL_FULL_READ_EMPLOYEE_ID]: `/api/mod/${EXCEL_FULL_READ_EMPLOYEE_ID}/employees/${EXCEL_FULL_READ_EMPLOYEE_ID}/run`,
  [WORD_FULL_READ_EMPLOYEE_ID]: `/api/mod/${WORD_FULL_READ_EMPLOYEE_ID}/employees/${WORD_FULL_READ_EMPLOYEE_ID}/run`,
}

export type OfficeFileUploadResult = {
  file_path: string
  workspace_root: string
  filename: string
}

async function ensureCsrf(): Promise<void> {
  const { readCsrfTokenFromCookie } = await import('@/utils/csrfCookie')
  if (readCsrfTokenFromCookie()) return
  await primeCsrfCookie()
}

export async function uploadTutorialOfficeFile(file: File): Promise<OfficeFileUploadResult> {
  return uploadOfficeFile(file, TUTORIAL_OFFICE_UPLOAD)
}

export async function isOfficeExcelReadInstalled(force = false): Promise<boolean> {
  try {
    const st = await fetchEmployeePlannerStatus(force)
    return resolveOfficeInstalledPackIds(st).includes(EXCEL_FULL_READ_EMPLOYEE_ID)
  } catch {
    return false
  }
}

export async function runOfficeEmployeeRead(
  employeeId: string,
  filePath: string,
  workspaceRoot: string,
): Promise<Record<string, unknown>> {
  const path = EMPLOYEE_RUN_PATHS[employeeId]
  if (!path) throw new Error(`未知办公员工：${employeeId}`)
  await ensureCsrf()
  const res = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_path: filePath,
      workspace_root: workspaceRoot,
      action: 'convert',
    }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.message || body?.error || `员工执行失败 HTTP ${res.status}`))
  }
  return asRecord(body?.data || body)
}

function workbookPayloadFromEmployeeData(data: Record<string, unknown>): Record<string, unknown> {
  const items = asArray<unknown>(data.items)
  for (const item of items) {
    const row = asRecord(item)
    if (asArray(row.sheets).length) return row
  }
  if (asArray(data.sheets).length) return data
  const summary = asString(data.summary).trim()
  if (summary.startsWith('{')) {
    try {
      return asRecord(JSON.parse(summary))
    } catch {
      /* ignore */
    }
  }
  return data
}

export function mapOfficeExcelReadToAnalysisResult(
  upload: OfficeFileUploadResult,
  employeeData: Record<string, unknown>,
): ExcelAnalysisResult {
  const book = workbookPayloadFromEmployeeData(employeeData)
  const rawSheets = asArray<Record<string, unknown>>(book.sheets)
  const sheetDetails: ExcelSheetDetail[] = rawSheets.map((sheet, idx) => {
    const headers = asArray<Record<string, unknown>>(sheet.headers)
    const fields: ExcelFieldInfo[] = headers
      .map((h) => asString(h.display || h.value).trim())
      .filter(Boolean)
      .map((name) => ({ name, label: name, type: 'dynamic' }))
    const sample_rows = asArray<Record<string, unknown>>(sheet.rows).map((row) => {
      const cells = asRecord(row.cells)
      return Object.keys(cells).length ? cells : row
    })
    const gridRows = [
      fields.map((f) => f.label || f.name || ''),
      ...sample_rows.slice(0, 20).map((row) =>
        fields.map((f) => {
          const key = String(f.name || f.label || '')
          const val = row[key]
          return val == null ? '' : String(val)
        }),
      ),
    ]
    return {
      sheet_index: idx + 1,
      sheet_name: asString(sheet.name || `Sheet${idx + 1}`),
      fields,
      sample_rows,
      grid_preview: { rows: gridRows },
      tables: [],
    }
  })
  const first = sheetDetails[0]
  return {
    fields: first?.fields,
    sheets: sheetDetails,
    preview_data: {
      sheet_name: first?.sheet_name,
      sheet_names: sheetDetails.map((s) => String(s.sheet_name || '')),
      file_path: upload.file_path,
      sample_rows: first?.sample_rows,
      grid_preview: first?.grid_preview,
      all_sheets: sheetDetails,
    },
  }
}

export function summarizeOfficeExcelRead(fileName: string, employeeData: Record<string, unknown>): string {
  const book = workbookPayloadFromEmployeeData(employeeData)
  const sheets = asArray<Record<string, unknown>>(book.sheets)
  const lines = sheets.slice(0, 12).map((sheet, idx) => {
    const name = asString(sheet.name || `Sheet${idx + 1}`)
    const rowCount = asArray(sheet.rows).length
    const fieldCount = asArray(sheet.headers).length
    return `Sheet ${idx + 1}（${name}）：词条${fieldCount}，数据行${rowCount}`
  })
  return [
    'Excel 读取完成（办公包 · Excel 读取员）',
    `文件：${fileName}`,
    `工作表总数：${Math.max(sheets.length, 1)}`,
    ...(lines.length ? ['分表摘要：', ...lines] : []),
    asString(employeeData.summary).trim() ? `员工摘要：${asString(employeeData.summary).slice(0, 400)}` : '',
  ]
    .filter(Boolean)
    .join('\n')
}

export async function readExcelViaOfficePack(file: File): Promise<{
  upload: OfficeFileUploadResult
  employeeData: Record<string, unknown>
  result: ExcelAnalysisResult
  summary: string
}> {
  const upload = await uploadChatOfficeFile(file)
  const employeeData = await runOfficeEmployeeRead(
    EXCEL_FULL_READ_EMPLOYEE_ID,
    upload.file_path,
    upload.workspace_root,
  )
  if (employeeData.ok === false) {
    throw new Error(asString(employeeData.error || employeeData.summary) || 'Excel 读取员执行失败')
  }
  const result = mapOfficeExcelReadToAnalysisResult(upload, employeeData)
  const summary = summarizeOfficeExcelRead(file.name, employeeData)
  return { upload, employeeData, result, summary }
}

export async function readWordViaOfficePack(
  file: File,
  uploaded?: OfficeFileUploadResult,
): Promise<{ ok: boolean; summary: string }> {
  const upload = uploaded || (await uploadTutorialOfficeFile(file))
  const workspaceRoot = upload.workspace_root
  if (!workspaceRoot) {
    throw new Error('办公样本上传未返回 workspace_root')
  }
  const employeeData = await runOfficeEmployeeRead(
    WORD_FULL_READ_EMPLOYEE_ID,
    upload.file_path,
    workspaceRoot,
  )
  const ok = employeeData.ok !== false
  const summary = asString(employeeData.summary || employeeData.error).trim()
  return { ok, summary: summary || (ok ? 'Word 读取完成' : 'Word 读取失败') }
}
