/** 「全量读取/生成」员工包 ID、扩展名解析与文件接受校验（原 tabularReadEmployees 单体拆分） */
import { officeFormatFromExtension, resolveGenerateEmployeeForFormat } from '../officeEmployeeOrchestration'

export const GENERATE_EMPLOYEE_IDS = [
  'word-generate-employee',
  'excel-generate-employee',
  'csv-generate-employee',
  'pdf-generate-employee',
  'ppt-generate-employee',
] as const

const GENERATE_EMPLOYEE_ID_SET = new Set<string>(GENERATE_EMPLOYEE_IDS)

export function isGenerateEmployeeId(employeeId: string): boolean {
  return GENERATE_EMPLOYEE_ID_SET.has(String(employeeId || '').trim())
}

export const TABULAR_READ_EMPLOYEE_IDS = [
  'excel-full-read-employee',
  'csv-full-read-employee',
  'pdf-full-read-employee',
  'ppt-full-read-employee',
  'word-full-read-employee',
] as const

export const JSON_REPORT_EMPLOYEE_ID = 'json-report-employee'

const EXT_TO_READ_EMPLOYEE: Record<string, string> = {
  xlsx: 'excel-full-read-employee',
  xlsm: 'excel-full-read-employee',
  xls: 'excel-full-read-employee',
  csv: 'csv-full-read-employee',
  pdf: 'pdf-full-read-employee',
  pptx: 'ppt-full-read-employee',
  ppt: 'ppt-full-read-employee',
  docx: 'word-full-read-employee',
  doc: 'word-full-read-employee',
  docm: 'word-full-read-employee',
  dotx: 'word-full-read-employee',
  dotm: 'word-full-read-employee',
  rtf: 'word-full-read-employee',
  wps: 'word-full-read-employee',
}

export function resolveReadEmployeeForExtension(ext: string): string | null {
  const e = String(ext || '')
    .trim()
    .toLowerCase()
    .replace(/^\./, '')
  return EXT_TO_READ_EMPLOYEE[e] || null
}

export function isEmployeeExecuteFileExt(ext: string): boolean {
  return resolveReadEmployeeForExtension(ext) !== null
}

function normalizeFileExt(ext: string): string {
  return String(ext || '')
    .trim()
    .toLowerCase()
    .replace(/^\./, '')
}

/** 当前员工包是否接受该扩展名（考试页选文件、工作台发送前校验）。 */
export function employeeAcceptsFileExtension(employeeId: string, ext: string): boolean {
  const e = normalizeFileExt(ext)
  if (!e) return false
  if (employeeId === JSON_REPORT_EMPLOYEE_ID) return e === 'json'
  if (isGenerateEmployeeId(employeeId)) {
    if (e === 'json' || e === 'txt') return true
    if (employeeId === 'word-generate-employee' && e === 'docx') return true
    return false
  }
  const suggested = resolveReadEmployeeForExtension(e)
  if (!suggested) return false
  return suggested === employeeId
}

/** 扩展名与所选员工不匹配时的中文提示（与 employee_api 语义对齐）。 */
export function employeeFileMismatchHint(employeeId: string, ext: string): string {
  const e = normalizeFileExt(ext)
  const readId = resolveReadEmployeeForExtension(e)
  if (isGenerateEmployeeId(employeeId) && readId) {
    const readLabel = readEmployeeDisplayName(readId)
    const fmt = officeFormatFromExtension(e)
    const genId = fmt ? resolveGenerateEmployeeForFormat(fmt) : ''
    const genLabel = genId ? readEmployeeDisplayName(genId) : ''
    if (fmt === 'ppt' && genId) {
      return (
        `生成员「${employeeId}」不能直接上传 .${e} 原稿；请改选「${readLabel}」（${readId}）全量解析，` +
        `或先导出 presentation_full.json 再用「${genLabel}」（${genId}）生成`
      )
    }
    return `生成员「${employeeId}」不接受 .${e}；请改选「${readLabel}」（${readId}）`
  }
  if (readId) {
    return `当前员工不接受 .${e}；请改选「${readEmployeeDisplayName(readId)}」（${readId}）`
  }
  if (e === 'json') {
    return 'JSON 请使用 json-report-employee 或对应格式的 *-generate-employee'
  }
  return `不支持 .${e || '该'} 扩展名；读取类支持 Office/PDF，生成员支持 .json/.txt`
}

/** 根据上传文件扩展名推荐员工包（含 .json → 量化报告员）。 */
export function suggestEmployeeForUploadedFile(ext: string): string | null {
  const e = normalizeFileExt(ext)
  if (e === 'json') return JSON_REPORT_EMPLOYEE_ID
  return resolveReadEmployeeForExtension(e)
}

export function readEmployeeDisplayName(pkgId: string): string {
  const map: Record<string, string> = {
    'excel-full-read-employee': 'Excel 读取员',
    'csv-full-read-employee': 'CSV 全量读取员',
    'pdf-full-read-employee': 'PDF 全量读取员',
    'ppt-full-read-employee': 'PPT 全量读取员',
    'ppt-generate-employee': 'PPT 生成员',
    'word-full-read-employee': 'Word 全量读取员',
    'word-generate-employee': 'Word 生成员',
    'excel-generate-employee': 'Excel 生成员',
    'csv-generate-employee': 'CSV 生成员',
    'pdf-generate-employee': 'PDF 生成员',
    [JSON_REPORT_EMPLOYEE_ID]: 'JSON 量化报告员',
  }
  return map[pkgId] || pkgId
}
