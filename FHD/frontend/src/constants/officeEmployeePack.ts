export const OFFICE_EMPLOYEE_PKG_IDS = [
  'excel-generate-employee',
  'excel-full-read-employee',
  'csv-generate-employee',
  'csv-full-read-employee',
  'pdf-generate-employee',
  'pdf-full-read-employee',
  'ppt-generate-employee',
  'ppt-full-read-employee',
  'word-generate-employee',
  'word-full-read-employee',
] as const

export const EXCEL_FULL_READ_EMPLOYEE_ID = 'excel-full-read-employee'
export const WORD_FULL_READ_EMPLOYEE_ID = 'word-full-read-employee'

/** 办公员工附属包1：JSON 量化报告 + 智慧分析可视化图表员工。 */
export const OFFICE_AUX_PACK_1_PKG_IDS = [
  'json-report-employee',
  'chart-bar-employee',
  'chart-line-employee',
  'chart-pie-employee',
  'chart-dashboard-employee',
] as const

export const OFFICE_EMPLOYEE_COLLECTION = 'office_employee_pack'
export const OFFICE_AUX_PACK_1_COLLECTION = 'office_employee_aux_pack_1'

export type EmployeePackIconKind =
  | 'ppt'
  | 'excel'
  | 'csv'
  | 'pdf'
  | 'word'
  | 'report'
  | 'chart'
  | 'office'
  | 'generic'

export function employeePackIconKind(pkgId?: string | null): EmployeePackIconKind {
  const id = (pkgId || '').toLowerCase()
  if (id.startsWith('ppt-')) return 'ppt'
  if (id.startsWith('excel-')) return 'excel'
  if (id.startsWith('csv-')) return 'csv'
  if (id.startsWith('pdf-')) return 'pdf'
  if (id.startsWith('word-')) return 'word'
  if (id.startsWith('json-report')) return 'report'
  if (id.startsWith('chart-')) return 'chart'
  if (OFFICE_EMPLOYEE_PKG_IDS.some((p) => p === id)) return 'office'
  if (OFFICE_AUX_PACK_1_PKG_IDS.some((p) => p === id)) return 'report'
  return 'generic'
}

export function isOfficeEmployeePkg(pkgId?: string | null): boolean {
  return OFFICE_EMPLOYEE_PKG_IDS.includes((pkgId || '') as (typeof OFFICE_EMPLOYEE_PKG_IDS)[number])
}

export function isOfficeAuxPack1Pkg(pkgId?: string | null): boolean {
  return OFFICE_AUX_PACK_1_PKG_IDS.includes((pkgId || '') as (typeof OFFICE_AUX_PACK_1_PKG_IDS)[number])
}

/** 主办公包分组（不含 report；附属包单独导航） */
export const OFFICE_GROUP_ORDER: EmployeePackIconKind[] = ['ppt', 'excel', 'csv', 'pdf', 'word']

export const OFFICE_AUX_GROUP_ORDER: EmployeePackIconKind[] = ['report', 'chart']

export const OFFICE_GROUP_LABELS: Record<EmployeePackIconKind, string> = {
  ppt: 'PPT',
  excel: 'Excel',
  csv: 'CSV',
  pdf: 'PDF',
  word: 'Word',
  report: '报告',
  chart: '可视化',
  office: '办公',
  generic: '其他',
}

/** 员工职责：读取 / 生成 */
export function employeePackRole(pkgId?: string | null): 'read' | 'generate' | 'report' | '' {
  const id = (pkgId || '').toLowerCase()
  if (id.includes('full-read') || id.includes('-read-employee')) return 'read'
  if (id.includes('generate')) return 'generate'
  if (id.includes('json-report')) return 'report'
  if (id.startsWith('chart-')) return 'generate'
  return ''
}
