/** 进阶教程：部门 + 人员 Excel 教学样本（public/tutorial/） */
export const TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX = '/tutorial/xcagi-tutorial-dept-employee.xlsx'

/** 快速上手：办公包装完后 Excel / Word 导入演示样本 */
export const TUTORIAL_QUICKSTART_EXCEL_A = '/tutorial/xcagi-quickstart-sample-a.xlsx'
export const TUTORIAL_QUICKSTART_EXCEL_B = '/tutorial/xcagi-quickstart-sample-b.xlsx'
export const TUTORIAL_QUICKSTART_WORD = '/tutorial/xcagi-quickstart-sample.docx'

/** 导入行前缀，便于在列表中搜索与批量删除教学数据 */
export const TUTORIAL_SAMPLE_NAME_PREFIX = '教程示例-'

const TUTORIAL_UPLOAD_PATHS_KEY = 'xcagi_tutorial_office_upload_paths'

export function trackTutorialOfficeUploadPath(filePath: string): void {
  if (typeof window === 'undefined' || !filePath) return
  try {
    const prev = JSON.parse(sessionStorage.getItem(TUTORIAL_UPLOAD_PATHS_KEY) || '[]') as string[]
    if (!prev.includes(filePath)) prev.push(filePath)
    sessionStorage.setItem(TUTORIAL_UPLOAD_PATHS_KEY, JSON.stringify(prev.slice(-12)))
  } catch {
    /* ignore */
  }
}

export function readTutorialOfficeUploadPaths(): string[] {
  if (typeof window === 'undefined') return []
  try {
    return JSON.parse(sessionStorage.getItem(TUTORIAL_UPLOAD_PATHS_KEY) || '[]') as string[]
  } catch {
    return []
  }
}

export function clearTutorialOfficeUploadPaths(): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.removeItem(TUTORIAL_UPLOAD_PATHS_KEY)
  } catch {
    /* ignore */
  }
}

