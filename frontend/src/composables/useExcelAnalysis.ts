import { ref } from 'vue'
import type { ChatMessageExtras } from './useChatMessages'

/** 多表 xlsx 在服务端 openpyxl 解析可能远超 30s；过短会 Abort 且任务面板卡在「解析工作簿」进度 */
const EXTRACT_GRID_TIMEOUT_MS = 180_000
const EXTRACT_GRID_SINGLE_SHEET_TIMEOUT_MS = 90_000

/**
 * 必须始终用相对路径（与当前页面同源），经 Vite :5001 代理到后端 :5000。
 * 若改用 apiUrl + VITE_API_BASE_URL 直连 127.0.0.1:5000，用户从局域网 IP（如 http://192.168.x.x:5001）
 * 打开页面时，浏览器会按跨域拦截，后端日志里完全看不到请求。
 */
const EXTRACT_GRID_PATH = '/api/templates/extract-grid'

/** 读取响应体（含大 JSON）；若仅对 fetch 设 Abort，部分环境下 body 读取仍可能挂死，导致「分析中…」永不解除 */
async function readResponseJsonWithTimeout(response: Response, ms: number): Promise<any> {
  let to = 0
  const timeoutP = new Promise<never>((_, rej) => {
    to = window.setTimeout(
      () => rej(new Error(`响应读取超时（${Math.round(ms / 1000)} 秒），请缩小文件或稍后重试`)),
      ms
    )
  })
  try {
    const text = await Promise.race([response.text(), timeoutP])
    window.clearTimeout(to)
    if (!text) return {}
    try {
      return JSON.parse(text)
    } catch {
      return {}
    }
  } catch (e) {
    window.clearTimeout(to)
    throw e
  }
}

/** Excel 分析流程用：先同步写入 UI，再后台持久化，避免服务端重载时 saveMessage 长时间挂起导致「分析中…」永不解除 */
interface UseChatMessagesReturn {
  addMessage: (
    content: string,
    role?: 'user' | 'ai' | 'task',
    extras?: ChatMessageExtras
  ) => void
  saveMessage: (role: 'user' | 'ai' | 'task', content: string) => Promise<void>
}

interface UseExcelAnalysisOptions {
  onAnalyzed?: (payload: {
    fileName: string
    summary: string
    result: ExcelAnalysisResult
  }) => void
  onAnalyzeStart?: (payload: { fileName: string }) => void
  onAnalyzeProgress?: (payload: { fileName: string; step: string; progress?: number }) => void
  onAnalyzeDone?: (payload: { fileName: string; success: boolean; message?: string }) => void
}

export interface ExcelAnalysisResult {
  fields?: string[]
  sheets?: Array<{
    sheet_index?: number
    sheet_name?: string
    fields?: any[]
    sample_rows?: Record<string, any>[]
    grid_preview?: { rows?: any[][] }
    style_cache?: {
      styles?: Record<string, any>
      cell_style_refs?: Record<string, string>
    }
    tables?: Array<{
      table_index?: number
      header_row?: number
      fields?: any[]
      sample_rows?: Record<string, any>[]
    }>
  }>
  preview_data?: {
    sheet_name?: string
    sheet_names?: string[]
    sample_rows?: Record<string, any>[]
    grid_preview?: {
      rows?: any[][]
    }
    all_sheets?: Array<{
      sheet_index?: number
      sheet_name?: string
      fields?: any[]
      sample_rows?: Record<string, any>[]
      grid_preview?: { rows?: any[][] }
      style_cache?: {
        styles?: Record<string, any>
        cell_style_refs?: Record<string, string>
      }
      tables?: Array<{
        table_index?: number
        header_row?: number
        fields?: any[]
        sample_rows?: Record<string, any>[]
      }>
    }>
    tables?: Array<{
      table_index?: number
      header_row?: number
      fields?: any[]
      sample_rows?: Record<string, any>[]
    }>
    grid_style_cache?: {
      styles?: Record<string, any>
      cell_style_refs?: Record<string, string>
    }
  }
}

async function extractSingleSheetDetail(file: File, sheetName: string): Promise<any | null> {
  try {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('sheet_name', sheetName)
    formData.append('analyze_all_sheets', 'false')
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), EXTRACT_GRID_SINGLE_SHEET_TIMEOUT_MS)
    try {
      const response = await fetch(EXTRACT_GRID_PATH, {
        method: 'POST',
        body: formData,
        signal: controller.signal
      })
      const data = await readResponseJsonWithTimeout(response, 60_000)
      if (!response.ok || !data?.success) return null
      return {
        sheet_name: sheetName,
        fields: Array.isArray(data?.fields) ? data.fields : [],
        sample_rows: Array.isArray(data?.preview_data?.sample_rows) ? data.preview_data.sample_rows : [],
        grid_preview: data?.preview_data?.grid_preview || { rows: [] },
        style_cache: data?.preview_data?.grid_style_cache || { styles: {}, cell_style_refs: {} },
        tables: Array.isArray(data?.preview_data?.tables) ? data.preview_data.tables : []
      }
    } finally {
      window.clearTimeout(timeoutId)
    }
  } catch (_e) {
    return null
  }
}

export function useExcelAnalysis(messages: UseChatMessagesReturn, options: UseExcelAnalysisOptions = {}) {
  const excelAnalyzeUploading = ref(false)
  const excelAnalyzeInputRef = ref<HTMLInputElement | null>(null)
  let onMultimodalFileChangeCallback: ((ev: Event) => void) | null = null

  function appendChatLine(
    content: string,
    role: 'user' | 'ai' | 'task' = 'ai',
    extras?: ChatMessageExtras
  ): void {
    messages.addMessage(content, role, extras)
    void messages.saveMessage(role, content).catch(() => {})
  }

  function triggerUpload() {
    if (excelAnalyzeUploading.value) return
    excelAnalyzeInputRef.value?.click()
  }

  function triggerExcelAnalyzeUpload() {
    triggerUpload()
  }

  function setOnMultimodalFileChangeCallback(cb: (ev: Event) => void) {
    onMultimodalFileChangeCallback = cb
  }

  function summarizeExcelAnalysisResult(result: ExcelAnalysisResult): string {
    const sheetList = Array.isArray(result?.sheets)
      ? result.sheets
      : (Array.isArray(result?.preview_data?.all_sheets) ? result.preview_data?.all_sheets : [])
    const sheetNames = Array.isArray((result as any)?.preview_data?.sheet_names)
      ? ((result as any).preview_data.sheet_names as any[])
          .map((x) => String(x || '').trim())
          .filter(Boolean)
      : []

    const fields = Array.isArray(result?.fields) ? result.fields : []
    const sampleRows = Array.isArray(result?.preview_data?.sample_rows) ? result.preview_data.sample_rows : []
    const sheetName = result?.preview_data?.sheet_name || 'Sheet1'
    const gridRows = Array.isArray(result?.preview_data?.grid_preview?.rows)
      ? result.preview_data.grid_preview.rows.length
      : 0

    const fieldNames = fields
      .map((f) => String((f as any)?.label || (f as any)?.name || '').trim())
      .filter(Boolean)
      .slice(0, 40)

    const sheetSummaryLines = sheetList
      .slice(0, 12)
      .map((sheet: any, idx: number) => {
        const no = Number(sheet?.sheet_index) || idx + 1
        const name = String(sheet?.sheet_name || `Sheet${no}`)
        const rowCount = Array.isArray(sheet?.grid_preview?.rows) ? sheet.grid_preview.rows.length : 0
        const fieldCount = Array.isArray(sheet?.fields) ? sheet.fields.length : 0
        return `Sheet ${no}（${name}）：词条${fieldCount}，网格行${rowCount}`
      })

    const totalStyleCellsFromSheets = sheetList.reduce((acc: number, sheet: any) => {
      const refs = sheet?.style_cache?.cell_style_refs
      return acc + (refs ? Object.keys(refs).length : 0)
    }, 0)
    const fallbackStyleRefs = result?.preview_data?.grid_style_cache?.cell_style_refs
    const totalStyleCells = totalStyleCellsFromSheets || (fallbackStyleRefs ? Object.keys(fallbackStyleRefs).length : 0)
    const totalLogicalTables = sheetList.reduce((acc: number, sheet: any) => {
      const tables = Array.isArray(sheet?.tables) ? sheet.tables.length : 0
      return acc + tables
    }, Array.isArray(result?.preview_data?.tables) ? result.preview_data.tables.length : 0)

    const tableSummaryLines = sheetList
      .flatMap((sheet: any, idx: number) => {
        const no = Number(sheet?.sheet_index) || idx + 1
        const name = String(sheet?.sheet_name || `Sheet${no}`)
        const tables = Array.isArray(sheet?.tables) ? sheet.tables : []
        return tables.slice(0, 5).map((tb: any) => {
          const tbNo = Number(tb?.table_index) || 1
          const tbFields = Array.isArray(tb?.fields) ? tb.fields.length : 0
          const tbSamples = Array.isArray(tb?.sample_rows) ? tb.sample_rows.length : 0
          return `Sheet ${no}（${name}）- 表${tbNo}：词条${tbFields}，样例${tbSamples}`
        })
      })
      .slice(0, 12)

    const detailSheets = (sheetList.length ? sheetList : [{
      sheet_index: 1,
      sheet_name: sheetName,
      fields,
      sample_rows: sampleRows,
      grid_preview: { rows: Array.isArray(result?.preview_data?.grid_preview?.rows) ? result.preview_data?.grid_preview?.rows : [] }
    }]).slice(0, 8)

    const sheetDetailLines = detailSheets.flatMap((sheet: any, idx: number) => {
      const no = Number(sheet?.sheet_index) || idx + 1
      const name = String(sheet?.sheet_name || `Sheet${no}`)
      const sheetFields = (Array.isArray(sheet?.fields) ? sheet.fields : [])
        .map((f: any) => String(f?.label || f?.name || '').trim())
        .filter(Boolean)
        .slice(0, 30)
      const sheetRows = Array.isArray(sheet?.grid_preview?.rows) ? sheet.grid_preview.rows.length : 0
      const sheetSamples = (Array.isArray(sheet?.sample_rows) ? sheet.sample_rows : [])
        .slice(0, 2)
        .map((row: any, sIdx: number) => {
          const pairs = Object.entries(row || {})
            .slice(0, 5)
            .map(([k, v]) => `${k}:${String(v ?? '').slice(0, 30)}`)
            .join('；')
          return `  ${sIdx + 1}. ${pairs || '无'}`
        })
      return [
        `Sheet ${no}（${name}）`,
        `- 词条数量：${sheetFields.length}`,
        `- 词条：${sheetFields.length ? sheetFields.join('、') : '无'}`,
        `- 网格行数：${sheetRows}`,
        `- 样例数据：`,
        ...(sheetSamples.length ? sheetSamples : ['  无样例行'])
      ]
    })

    return [
      `Excel 分析完成`,
      `工作表总数：${Math.max(sheetList.length, sheetNames.length, 1)}`,
      `工作表：${sheetName}`,
      `词条数量：${fieldNames.length}`,
      `词条：${fieldNames.length ? fieldNames.join('、') : '无'}`,
      `网格行数：${gridRows}`,
      `识别表块：${totalLogicalTables}`,
      `样式缓存单元格：${totalStyleCells}`,
      ...(sheetSummaryLines.length ? ['分表摘要：', ...sheetSummaryLines] : []),
      ...(tableSummaryLines.length ? ['逻辑表块分类：', ...tableSummaryLines] : []),
      `分表详细分析：`,
      ...sheetDetailLines,
      ...(sheetList.length > 8 ? [`（仅展示前8个工作表，剩余 ${sheetList.length - 8} 个）`] : [])
    ].join('\n')
  }

  async function onExcelAnalyzeFileChange(e: Event): Promise<void> {
    const file = (e?.target as any)?.files?.[0] as File | undefined
    ;(e.target as HTMLInputElement).value = ''
    if (!file) return

    if (/\.(xlsx|xlsm)$/i.test(file.name)) {
      excelAnalyzeUploading.value = true
      try {
        appendChatLine(`开始分析 Excel：${file.name}`, 'user')
        options.onAnalyzeStart?.({ fileName: file.name })
        options.onAnalyzeProgress?.({
          fileName: file.name,
          step: '正在上传并请求解析…',
          progress: 12
        })

        try {
          const formData = new FormData()
          formData.append('file', file)
          formData.append('analyze_all_sheets', 'true')
          const controller = new AbortController()
          const timeoutId = window.setTimeout(() => controller.abort(), EXTRACT_GRID_TIMEOUT_MS)
          options.onAnalyzeProgress?.({
            fileName: file.name,
            step: '服务器正在解析工作簿（多表时可能需数十秒）…',
            progress: 28
          })
          if (import.meta.env.DEV) {
            console.debug(
              '[excel-analysis] POST',
              EXTRACT_GRID_PATH,
              'page=',
              typeof window !== 'undefined' ? window.location.origin : ''
            )
          }
          try {
            const response = await fetch(EXTRACT_GRID_PATH, {
              method: 'POST',
              body: formData,
              signal: controller.signal
            })
            const data = await readResponseJsonWithTimeout(response, 120_000)

            if (!response.ok || !data?.success) {
              throw new Error(data?.message || `HTTP ${response.status}`)
            }

            options.onAnalyzeProgress?.({
              fileName: file.name,
              step: '正在整理分表与字段摘要…',
              progress: 58
            })

            const hasMultiSheetDetails =
              Array.isArray(data?.sheets) && data.sheets.length > 0
                || (Array.isArray(data?.preview_data?.all_sheets) && data.preview_data.all_sheets.length > 0)
            const sheetNames = Array.isArray(data?.preview_data?.sheet_names) ? data.preview_data.sheet_names : []
            if (!hasMultiSheetDetails && sheetNames.length > 1) {
              const detailedSheets: any[] = []
              for (let i = 0; i < sheetNames.length; i += 1) {
                const name = String(sheetNames[i] || '').trim()
                if (!name) continue
                options.onAnalyzeProgress?.({
                  fileName: file.name,
                  step: `补全分表详情 ${i + 1}/${sheetNames.length}`,
                  progress: Math.floor(((i + 1) / sheetNames.length) * 100)
                })
                const detail = await extractSingleSheetDetail(file, name)
                if (detail) {
                  detailedSheets.push({
                    sheet_index: i + 1,
                    ...detail
                  })
                }
              }
              if (detailedSheets.length) {
                data.sheets = detailedSheets
                if (!data.preview_data) data.preview_data = {}
                data.preview_data.all_sheets = detailedSheets
              }
            }

            options.onAnalyzeProgress?.({
              fileName: file.name,
              step: '正在生成对话摘要…',
              progress: 82
            })
            const summary = summarizeExcelAnalysisResult(data)
            appendChatLine(summary, 'ai')
            options.onAnalyzed?.({
              fileName: file.name,
              summary,
              result: data
            })
            options.onAnalyzeDone?.({ fileName: file.name, success: true })
          } finally {
            window.clearTimeout(timeoutId)
          }
        } catch (err: any) {
          const isAbort = err?.name === 'AbortError'
          const raw = String(err?.message || err || '')
          const netFail =
            /Failed to fetch|NetworkError|Load failed|网络/i.test(raw) || err?.name === 'TypeError'
          let hint = ''
          if (netFail && !isAbort) {
            hint =
              '（若后端无日志：请确认本机已启动 :5000、Vite 代理正常；开发环境请尽量用 http://127.0.0.1:5001 打开页面，避免局域网 IP + 直连 API 被浏览器拦截。）'
          }
          const msg = isAbort
            ? `Excel 分析超时（${Math.round(EXTRACT_GRID_TIMEOUT_MS / 1000)} 秒），请尝试更小文件、减少工作表数量或稍后重试。`
            : `Excel 分析失败：${raw || '未知错误'}${hint}`
          appendChatLine(msg, 'ai')
          options.onAnalyzeDone?.({ fileName: file.name, success: false, message: msg })
        }
      } finally {
        excelAnalyzeUploading.value = false
      }
    } else {
      if (onMultimodalFileChangeCallback) {
        onMultimodalFileChangeCallback(e)
      }
    }
  }

  return {
    excelAnalyzeUploading,
    excelAnalyzeInputRef,
    triggerUpload,
    triggerExcelAnalyzeUpload,
    onExcelAnalyzeFileChange,
    setOnMultimodalFileChangeCallback
  }
}
