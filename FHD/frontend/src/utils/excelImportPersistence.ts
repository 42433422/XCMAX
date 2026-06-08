/**
 * Excel 导入持久化工具
 * 
 * 解决聊天记录中断导致 pending_import_id 丢失的问题
 * 将待导入的 Excel 数据存储在 sessionStorage 中
 */

const STORAGE_PREFIX = 'xcagi_excel_pending_import_'

/**
 * 待导入数据结构
 */
export interface PendingExcelImport {
  pending_id: string
  records: Record<string, any>[]
  excel_analysis: {
    file_name: string
    file_path: string
    sheet_name: string
    fields: any[]
    summary: string
  }
  created_at: number
  session_id: string
}

/**
 * 保存待导入数据到 sessionStorage
 */
export function savePendingImport(data: PendingExcelImport): void {
  try {
    const key = STORAGE_PREFIX + data.pending_id
    sessionStorage.setItem(key, JSON.stringify(data))
    
    // 同时保存到 localStorage 作为备份（防止页面刷新丢失）
    localStorage.setItem(key, JSON.stringify(data))
    
    console.log('[ExcelImport] 保存待导入数据:', data.pending_id)
  } catch (error) {
    console.error('[ExcelImport] 保存失败:', error)
  }
}

/**
 * 从 sessionStorage 读取待导入数据
 */
export function getPendingImport(pending_id: string): PendingExcelImport | null {
  try {
    // 优先从 sessionStorage 读取
    const key = STORAGE_PREFIX + pending_id
    const sessionData = sessionStorage.getItem(key)
    if (sessionData) {
      return JSON.parse(sessionData)
    }
    
    // 如果 sessionStorage 没有，尝试从 localStorage 读取
    const localData = localStorage.getItem(key)
    if (localData) {
      const parsed = JSON.parse(localData)
      // 复制到 sessionStorage
      sessionStorage.setItem(key, localData)
      return parsed
    }
    
    return null
  } catch (error) {
    console.error('[ExcelImport] 读取失败:', error)
    return null
  }
}

/**
 * 删除待导入数据
 */
export function removePendingImport(pending_id: string): void {
  try {
    const key = STORAGE_PREFIX + pending_id
    sessionStorage.removeItem(key)
    localStorage.removeItem(key)
    console.log('[ExcelImport] 清除待导入数据:', pending_id)
  } catch (error) {
    console.error('[ExcelImport] 清除失败:', error)
  }
}

/**
 * 清理过期的待导入数据（超过 24 小时）
 */
export function cleanupExpiredImports(): void {
  try {
    const now = Date.now()
    const EXPIRY_MS = 24 * 60 * 60 * 1000 // 24 小时
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && key.startsWith(STORAGE_PREFIX)) {
        try {
          const data = JSON.parse(localStorage.getItem(key) || '')
          if (data && data.created_at) {
            const age = now - data.created_at
            if (age > EXPIRY_MS) {
              localStorage.removeItem(key)
              sessionStorage.removeItem(key)
              console.log('[ExcelImport] 清理过期数据:', key)
            }
          }
        } catch (e) {
          // 忽略解析错误的数据
        }
      }
    }
  } catch (error) {
    console.error('[ExcelImport] 清理失败:', error)
  }
}

/**
 * 获取所有待导入数据列表
 */
export function getAllPendingImports(): PendingExcelImport[] {
  try {
    const imports: PendingExcelImport[] = []
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && key.startsWith(STORAGE_PREFIX)) {
        try {
          const data = JSON.parse(localStorage.getItem(key) || '')
          if (data && data.pending_id) {
            imports.push(data)
          }
        } catch (e) {
          // 忽略解析错误的数据
        }
      }
    }
    
    return imports.sort((a, b) => b.created_at - a.created_at)
  } catch (error) {
    console.error('[ExcelImport] 获取列表失败:', error)
    return []
  }
}
