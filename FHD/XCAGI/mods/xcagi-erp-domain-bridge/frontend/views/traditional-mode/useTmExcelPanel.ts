import { ref, reactive, computed, nextTick } from 'vue'
import type { Ref } from 'vue'
import api from '@/api/core'
import templatePreviewApi from '@/api/templatePreview'
import { traditionalApi, FileInfo } from '@/api/traditional'
import { buildFileFingerprint } from './tmFileUtils'

interface TmExcelPanelDeps {
  showToast: (message: string, type?: 'success' | 'error') => void
  /** 保存成功后刷新目录列表 */
  refresh: () => void
  files: Ref<FileInfo[]>
  relPathFor: (file: FileInfo) => string
  /** 打开/关闭面板时重置手动归纳状态 */
  resetInduct: () => void
  /** 保存成功后作废已加载的归纳行 */
  invalidateInductRows: () => void
}

/** 传统模式侧栏 Excel：直接编辑（read/write）+ 提取网格（extract-grid 轮询）+ 下载缓存 */
export function useTmExcelPanel(deps: TmExcelPanelDeps) {
  /** 直接编辑：read/write；手动归纳：extract-grid + 全表行解析 + 主数据校验入库 */
  const excelPanel = reactive({
    visible: false,
    fileName: '',
    filePath: '',
    mainTab: 'edit' as 'edit' | 'induct',
    loading: false,
    /** 异步 extract-grid 进度（0–100） */
    extractProgressPercent: 0,
    extractProgressStep: '',
    extractResult: null as Record<string, any> | null,
    sheetNames: [] as string[],
    selectedSheetName: '',
    error: '',
    /** 与当前 filePath 一致时表示提取结果仍有效；直接编辑保存后清空以强制刷新 */
    extractLoadedPath: '',
    editContent: null as Record<string, { rows: any[][] }> | null,
    editActiveSheet: '',
    editLoading: false,
    editSaving: false,
    editError: '',
    /** 后端因行/列上限截断预览：禁止保存，避免覆盖未加载区域 */
    editTruncated: false,
    editTruncatedHint: '',
    /** 与目录列表一致的 size|mtime，用于下载缓存与防 HTTP 缓存串文件 */
    sourceFingerprint: '',
  })

  let cachedTradExcel: { path: string; fingerprint: string; file: File } | null = null
  /** 防止快速切换文件时旧请求晚到覆盖新状态 */
  let excelEditLoadGeneration = 0
  /** 防止多次并发 extract-grid 结束时错误清除 loading */
  let traditionalExtractGeneration = 0

  function cloneSheetRowsForEdit(rows: any[][]): any[][] {
    if (typeof structuredClone === 'function') {
      try {
        return structuredClone(rows) as any[][]
      } catch {
        /* 含不可克隆类型时回退 */
      }
    }
    return JSON.parse(JSON.stringify(rows)) as any[][]
  }

  const traditionalExtractTitle = computed(() => {
    return (
      excelPanel.selectedSheetName ||
      excelPanel.extractResult?.preview_data?.sheet_name ||
      excelPanel.extractResult?.preview_data?.selected_sheet_name ||
      'Sheet'
    )
  })

  const editSheetNames = computed(() => {
    if (!excelPanel.editContent) return []
    return Object.keys(excelPanel.editContent)
  })

  const editActiveRows = computed(() => {
    const s = excelPanel.editActiveSheet
    if (!s || !excelPanel.editContent?.[s]) return []
    return excelPanel.editContent[s].rows
  })

  function formatEditCell(cell: unknown): string {
    if (cell === null || cell === undefined) return ''
    if (typeof cell === 'string') return cell
    if (typeof cell === 'number' || typeof cell === 'boolean') return String(cell)
    return String(cell)
  }

  function clearTraditionalExcelCache() {
    cachedTradExcel = null
  }

  async function getTraditionalExcelFile(
    filePath: string,
    displayName: string,
    fingerprint: string
  ): Promise<File> {
    if (
      cachedTradExcel &&
      cachedTradExcel.path === filePath &&
      cachedTradExcel.fingerprint === fingerprint
    ) {
      return cachedTradExcel.file
    }
    const ac = new AbortController()
    const tid = window.setTimeout(() => ac.abort(), 180_000)
    let res: Response
    try {
      res = await api.download(
        '/api/traditional-mode/download',
        { file: filePath, v: fingerprint },
        { signal: ac.signal }
      )
    } finally {
      window.clearTimeout(tid)
    }
    const blob = await res.blob()
    const lower = displayName.toLowerCase()
    const mime =
      blob.type ||
      (lower.endsWith('.xls') && !lower.endsWith('.xlsx')
        ? 'application/vnd.ms-excel'
        : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    const file = new File([blob], displayName, { type: mime })
    cachedTradExcel = { path: filePath, fingerprint, file }
    return file
  }

  /** 列表刷新后：若当前打开的 Excel 在磁盘上已变，更新指纹并丢弃下载缓存，避免「提取预览」仍是旧文档 */
  function syncExcelPanelFingerprintFromList() {
    if (!excelPanel.visible || !excelPanel.filePath || !excelPanel.fileName) return
    const target = excelPanel.filePath
    const row = deps.files.value.find(
      (f) => !f.is_dir && f.name === excelPanel.fileName && deps.relPathFor(f) === target
    )
    if (!row) return
    const next = buildFileFingerprint(row)
    if (next !== excelPanel.sourceFingerprint) {
      excelPanel.sourceFingerprint = next
      clearTraditionalExcelCache()
      excelPanel.extractLoadedPath = ''
    }
  }

  async function openTraditionalExcelPanel(file: FileInfo) {
    const filePath = deps.relPathFor(file)
    traditionalExtractGeneration += 1
    clearTraditionalExcelCache()
    deps.resetInduct()
    excelPanel.visible = true
    excelPanel.fileName = file.name
    excelPanel.filePath = filePath
    excelPanel.mainTab = 'edit'
    excelPanel.loading = false
    excelPanel.extractResult = null
    excelPanel.sheetNames = []
    excelPanel.selectedSheetName = ''
    excelPanel.error = ''
    excelPanel.extractLoadedPath = ''
    excelPanel.editContent = null
    excelPanel.editActiveSheet = ''
    excelPanel.editError = ''
    excelPanel.editTruncated = false
    excelPanel.editTruncatedHint = ''
    excelPanel.sourceFingerprint = buildFileFingerprint(file)
    await loadExcelEditData()
  }

  async function loadExcelEditData() {
    if (!excelPanel.filePath) return
    const myGen = ++excelEditLoadGeneration
    excelPanel.editLoading = true
    excelPanel.editError = ''
    excelPanel.editContent = null
    excelPanel.editActiveSheet = ''
    excelPanel.editTruncated = false
    excelPanel.editTruncatedHint = ''
    const ac = new AbortController()
    const READ_TIMEOUT_MS = 90_000
    const tid = window.setTimeout(() => ac.abort(), READ_TIMEOUT_MS)
    try {
      const res = await traditionalApi.read(
        excelPanel.filePath,
        { signal: ac.signal },
        excelPanel.sourceFingerprint || undefined
      )
      if (myGen !== excelEditLoadGeneration) {
        return
      }
      if (!res.success || !res.data || res.data.type !== 'excel' || !res.data.content) {
        throw new Error((res as { error?: string }).error || '无法读取 Excel（仅支持 .xlsx / .xlsm 等，旧版 .xls 可能不支持）')
      }
      const content = res.data.content as Record<string, { rows?: any[][] }>
      const out: Record<string, { rows: any[][] }> = {}
      await nextTick()
      for (const [name, sheet] of Object.entries(content)) {
        const rows = Array.isArray(sheet?.rows) ? sheet.rows : []
        out[name] = { rows: cloneSheetRowsForEdit(rows) }
      }
      if (myGen !== excelEditLoadGeneration) {
        return
      }
      const names = Object.keys(out)
      if (!names.length) {
        throw new Error('工作簿中无工作表数据')
      }
      excelPanel.editContent = out
      excelPanel.editActiveSheet = names[0]
      const d = res.data as { edit_truncated?: boolean; edit_truncated_hint?: string }
      excelPanel.editTruncated = !!d.edit_truncated
      excelPanel.editTruncatedHint = String(d.edit_truncated_hint || '').trim()
    } catch (e: any) {
      if (myGen !== excelEditLoadGeneration) {
        return
      }
      const aborted =
        e?.name === 'AbortError' ||
        (typeof e?.message === 'string' && /aborted|AbortError|abort/i.test(e.message))
      const msg = aborted
        ? `读取 Excel 超时或已取消（${Math.round(READ_TIMEOUT_MS / 1000)}s 内无完整响应）。请确认本机已启动后端 run.py（5000）、文件不要过大，或改用「下载」后用 Excel 打开。`
        : (e?.message || String(e))
      excelPanel.editError = msg
      deps.showToast(msg, 'error')
    } finally {
      if (myGen === excelEditLoadGeneration) {
        window.clearTimeout(tid)
        excelPanel.editLoading = false
      } else {
        window.clearTimeout(tid)
      }
    }
  }

  function sleepMs(ms: number) {
    return new Promise<void>((resolve) => {
      window.setTimeout(resolve, ms)
    })
  }

  async function runTraditionalGridExtract(preferredSheet: string) {
    if (!excelPanel.visible || !excelPanel.filePath) return
    const myGen = ++traditionalExtractGeneration
    excelPanel.loading = true
    excelPanel.error = ''
    excelPanel.extractProgressPercent = 0
    excelPanel.extractProgressStep = '准备文件…'
    const ac = new AbortController()
    const EXTRACT_TIMEOUT_MS = 120_000
    const tid = window.setTimeout(() => ac.abort(), EXTRACT_TIMEOUT_MS)
    try {
      const f = await getTraditionalExcelFile(
        excelPanel.filePath,
        excelPanel.fileName,
        excelPanel.sourceFingerprint || buildFileFingerprint({
          name: excelPanel.fileName,
          is_dir: false,
          size: 0,
          modified_time: '',
          type: '',
        })
      )
      if (myGen !== traditionalExtractGeneration) {
        return
      }
      const formData = new FormData()
      formData.append('file', f)
      formData.append('analyze_all_sheets', 'false')
      if (preferredSheet) {
        formData.append('sheet_name', preferredSheet)
      }
      excelPanel.extractProgressStep = '提交任务…'
      excelPanel.extractProgressPercent = 2
      const start = (await templatePreviewApi.startExtractGridAsync(formData, {
        signal: ac.signal,
      })) as Record<string, any>
      if (myGen !== traditionalExtractGeneration) {
        return
      }
      if (!start?.success || !start?.task_id) {
        throw new Error(typeof start?.message === 'string' ? start.message : '无法启动提取任务')
      }
      const taskId = String(start.task_id)
      const pollMs = 280
      let res: Record<string, any> | null = null
      while (res === null) {
        if (myGen !== traditionalExtractGeneration) {
          return
        }
        const st = (await templatePreviewApi.getExtractGridStatus(taskId, {
          signal: ac.signal,
        })) as Record<string, any>
        if (myGen !== traditionalExtractGeneration) {
          return
        }
        if (typeof st.percent === 'number' && !Number.isNaN(st.percent)) {
          excelPanel.extractProgressPercent = st.percent
        }
        excelPanel.extractProgressStep = String(st.step || '')
        if (st.status === 'done' && st.result) {
          res = st.result as Record<string, any>
          break
        }
        if (st.status === 'error') {
          throw new Error(String(st.message || '提取失败'))
        }
        if (st.success === false && st.status !== 'running') {
          throw new Error(String(st.message || '提取失败'))
        }
        await sleepMs(pollMs)
      }
      if (myGen !== traditionalExtractGeneration) {
        return
      }
      if (!res?.success) {
        throw new Error(typeof res?.message === 'string' ? res.message : '提取失败')
      }
      excelPanel.extractResult = res
      const names = res?.preview_data?.sheet_names
      excelPanel.sheetNames = Array.isArray(names) ? [...names] : []
      excelPanel.selectedSheetName =
        preferredSheet ||
        res?.preview_data?.selected_sheet_name ||
        res?.preview_data?.sheet_name ||
        (excelPanel.sheetNames[0] || '')
      excelPanel.extractLoadedPath = excelPanel.filePath
    } catch (e: any) {
      if (myGen !== traditionalExtractGeneration) {
        return
      }
      const aborted =
        e?.name === 'AbortError' ||
        (typeof e?.message === 'string' && /aborted|AbortError|abort/i.test(e.message))
      const msg = aborted
        ? `提取网格超时（${Math.round(EXTRACT_TIMEOUT_MS / 1000)}s）。文件可能过大、工作表过多，或接口繁忙；可切换工作表重试或仅用「直接编辑」。`
        : (e?.message || String(e))
      excelPanel.error = msg
      deps.showToast(msg, 'error')
    } finally {
      window.clearTimeout(tid)
      if (myGen === traditionalExtractGeneration) {
        excelPanel.loading = false
        excelPanel.extractProgressPercent = 0
        excelPanel.extractProgressStep = ''
      }
    }
  }

  function updateEditCell(rowIdx: number, colIdx: number, event: FocusEvent) {
    const sheet = excelPanel.editActiveSheet
    if (!sheet || !excelPanel.editContent?.[sheet]) return
    const rows = excelPanel.editContent[sheet].rows
    if (!rows[rowIdx]) {
      rows[rowIdx] = []
    }
    const el = event.target as HTMLElement | null
    rows[rowIdx][colIdx] = el?.textContent ?? ''
  }

  async function saveExcelEdit() {
    if (!excelPanel.filePath || !excelPanel.editContent) return
    if (excelPanel.editTruncated) {
      deps.showToast('当前为截断预览，已禁止保存以免覆盖未加载的行列。请下载后用 Excel 编辑，或调大后端 TRADITIONAL_MODE_EXCEL_MAX_ROWS / MAX_COLS 后重新打开。', 'error')
      return
    }
    excelPanel.editSaving = true
    try {
      const content: Record<string, { rows: any[][] }> = {}
      for (const [k, v] of Object.entries(excelPanel.editContent)) {
        content[k] = { rows: v.rows }
      }
      const active = excelPanel.editActiveSheet || Object.keys(content)[0] || 'Sheet'
      const res = await traditionalApi.write({
        file: excelPanel.filePath,
        type: 'excel',
        data: {
          active_sheet: active,
          content,
        },
      })
      if (res.success) {
        deps.showToast('已保存')
        excelPanel.extractLoadedPath = ''
        deps.invalidateInductRows()
        clearTraditionalExcelCache()
        deps.refresh()
      } else {
        deps.showToast(res.error || '保存失败', 'error')
      }
    } catch (e: any) {
      deps.showToast('保存错误: ' + (e.message || ''), 'error')
    } finally {
      excelPanel.editSaving = false
    }
  }

  function closeExcelPanel() {
    /** 作废进行中的 read/extract，避免关闭后仍被旧 Promise 把状态锁在「加载中」 */
    excelEditLoadGeneration += 1
    traditionalExtractGeneration += 1
    excelPanel.editLoading = false
    excelPanel.loading = false
    excelPanel.visible = false
    excelPanel.mainTab = 'edit'
    deps.resetInduct()
    excelPanel.extractResult = null
    excelPanel.sheetNames = []
    excelPanel.selectedSheetName = ''
    excelPanel.error = ''
    excelPanel.extractLoadedPath = ''
    excelPanel.editContent = null
    excelPanel.editActiveSheet = ''
    excelPanel.editError = ''
    excelPanel.editTruncated = false
    excelPanel.editTruncatedHint = ''
    excelPanel.sourceFingerprint = ''
    clearTraditionalExcelCache()
  }

  /** 离开「手动归纳」时作废进行中的 extract-grid，避免旧请求晚到或 loading 一直为 true */
  function invalidateExtract() {
    traditionalExtractGeneration += 1
    excelPanel.loading = false
  }

  return {
    excelPanel,
    traditionalExtractTitle,
    editSheetNames,
    editActiveRows,
    formatEditCell,
    getTraditionalExcelFile,
    buildFileFingerprint,
    syncExcelPanelFingerprintFromList,
    openTraditionalExcelPanel,
    loadExcelEditData,
    runTraditionalGridExtract,
    updateEditCell,
    saveExcelEdit,
    closeExcelPanel,
    invalidateExtract,
    clearTraditionalExcelCache,
  }
}

export type TmExcelPanel = ReturnType<typeof useTmExcelPanel>
