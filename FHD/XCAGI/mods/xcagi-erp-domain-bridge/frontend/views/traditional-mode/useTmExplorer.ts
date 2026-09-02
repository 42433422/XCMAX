import { ref, computed, nextTick } from 'vue'
import { traditionalApi, FileInfo } from '@/api/traditional'
import type { ExplorerViewMode, SortKey } from './tmFileUtils'

const VIEW_MODE_STORAGE_KEY = 'xcagi_traditional_view_mode'

export const ROOT_NAME = 'bang'

function readStoredViewMode(): ExplorerViewMode {
  if (typeof localStorage === 'undefined') return 'icons'
  try {
    const v = localStorage.getItem(VIEW_MODE_STORAGE_KEY)
    if (v === 'details' || v === 'icons' || v === 'large') return v
  } catch {
    /* ignore */
  }
  return 'icons'
}

interface TmExplorerDeps {
  showToast: (message: string, type?: 'success' | 'error') => void
  /** 视图模式切换后需要重建缩略图懒加载观察 */
  onViewModeChanged: () => void
  /** 列表加载成功后同步侧栏 Excel 指纹 */
  onAfterListLoaded: () => void
  /** 导航后清空变更标记与监听快照 */
  onNavigateReset: () => void
  /** 刷新时仅清空变更标记 */
  onRefreshReset: () => void
  /** 导航后重置目录监听（仅当连接已建立） */
  restartSseIfActive: () => void
}

export function useTmExplorer(deps: TmExplorerDeps) {
  const viewMode = ref<ExplorerViewMode>(readStoredViewMode())

  function setViewMode(m: ExplorerViewMode) {
    viewMode.value = m
    try {
      localStorage.setItem(VIEW_MODE_STORAGE_KEY, m)
    } catch {
      /* ignore */
    }
    nextTick(() => deps.onViewModeChanged())
  }

  const currentPath = ref('')
  const files = ref<FileInfo[]>([])
  const loading = ref(false)
  const pathInput = ref('')
  const selectedFile = ref<FileInfo | null>(null)
  const history = ref<string[]>([''])
  const historyIndex = ref(0)

  const pathSegments = computed(() => {
    if (!currentPath.value) return []
    return currentPath.value.replace(/\\/g, '/').split('/').filter(Boolean)
  })

  const displayPath = computed(() => {
    if (!currentPath.value) return ROOT_NAME
    return `${ROOT_NAME}\\${currentPath.value.replace(/\//g, '\\')}`
  })

  /** 地址栏：根目录与多级路径均带逻辑根名，反斜杠风格同资源管理器 */
  function formatPathInput(path: string): string {
    if (!path) return ROOT_NAME
    return `${ROOT_NAME}\\${path.replace(/\//g, '\\')}`
  }

  const sortKey = ref<SortKey>('name')
  const sortAsc = ref(true)

  function toggleSort(key: SortKey) {
    if (sortKey.value === key) {
      sortAsc.value = !sortAsc.value
    } else {
      sortKey.value = key
      sortAsc.value = key !== 'size'
    }
  }

  const sortedFiles = computed(() => {
    const k = sortKey.value
    const asc = sortAsc.value ? 1 : -1
    const byName = (a: FileInfo, b: FileInfo) =>
      a.name.localeCompare(b.name, 'zh-CN', { numeric: true, sensitivity: 'base' })

    return [...files.value].sort((a, b) => {
      if (k === 'name') {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
        return asc * byName(a, b)
      }
      if (k === 'type') {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
        const ta = a.is_dir ? '\u0000' : (a.type || '')
        const tb = b.is_dir ? '\u0000' : (b.type || '')
        const c = ta.localeCompare(tb, 'zh-CN')
        if (c !== 0) return asc * c
        return asc * byName(a, b)
      }
      if (k === 'size') {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
        const sa = a.is_dir ? 0 : (a.size || 0)
        const sb = b.is_dir ? 0 : (b.size || 0)
        if (sa !== sb) return asc * (sa < sb ? -1 : 1)
        return asc * byName(a, b)
      }
      const ta = new Date(a.modified_time || 0).getTime()
      const tb = new Date(b.modified_time || 0).getTime()
      if (ta !== tb) return asc * (ta < tb ? -1 : 1)
      return byName(a, b)
    })
  })

  async function loadList(path?: string) {
    const target = path !== undefined ? path : currentPath.value
    loading.value = true
    try {
      const res = await traditionalApi.list(target)
      if (res.success && res.data) {
        files.value = res.data.files || []
        if (path === undefined || path === null) {
          currentPath.value = res.data.path || ''
        }
        deps.onAfterListLoaded()
        nextTick(() => deps.onViewModeChanged())
      } else {
        deps.showToast(res.error || '加载目录失败', 'error')
      }
    } catch (e: any) {
      deps.showToast('网络错误: ' + (e.message || ''), 'error')
    } finally {
      loading.value = false
    }
  }

  function navigate(path: string, pushHistory = true) {
    if (pushHistory) {
      const lastPath = history.value[history.value.length - 1]
      if (lastPath !== path) {
        history.value = history.value.slice(0, historyIndex.value + 1)
        history.value.push(path)
        historyIndex.value = history.value.length - 1
      }
    }
    currentPath.value = path
    pathInput.value = formatPathInput(path)
    selectedFile.value = null
    deps.onNavigateReset()
    deps.restartSseIfActive()
    loadList(path)
  }

  function navigateToSegment(idx: number) {
    if (idx < 0) { navigate(''); return }
    const segs = pathSegments.value
    const newPath = segs.slice(0, idx + 1).join('/')
    navigate(newPath)
  }

  function goToPath() {
    let input = (pathInput.value || '').trim().replace(/\\/g, '/')
    if (input === '/' || input === '\\') input = ''
    const lower = input.toLowerCase()
    const rootPref = `${ROOT_NAME.toLowerCase()}/`
    if (lower.startsWith(rootPref)) {
      input = input.slice(rootPref.length).replace(/^\/+/, '')
    } else if (lower === ROOT_NAME.toLowerCase()) {
      input = ''
    }
    if (input.includes('..')) {
      deps.showToast('路径不能包含 ..', 'error')
      return
    }
    navigate(input)
  }

  function goBack() {
    if (historyIndex.value > 0) {
      historyIndex.value--
      const path = history.value[historyIndex.value]
      currentPath.value = path
      pathInput.value = formatPathInput(path)
      selectedFile.value = null
      loadList(path)
    }
  }

  function goForward() {
    if (historyIndex.value < history.value.length - 1) {
      historyIndex.value++
      const path = history.value[historyIndex.value]
      currentPath.value = path
      pathInput.value = formatPathInput(path)
      selectedFile.value = null
      loadList(path)
    }
  }

  function goUp() {
    if (!currentPath.value) return
    const parts = currentPath.value.replace(/\\/g, '/').split('/').filter(Boolean)
    parts.pop()
    navigate(parts.join('/') || '', true)
  }

  function refresh() {
    deps.onRefreshReset()
    loadList()
  }

  /** 传统模式根下文件的逻辑相对路径（与 list/read/download 的 file 参数一致） */
  function traditionalRelPathForFile(file: FileInfo): string {
    return currentPath.value ? `${currentPath.value}/${file.name}` : file.name
  }

  return {
    viewMode,
    setViewMode,
    currentPath,
    files,
    loading,
    pathInput,
    selectedFile,
    history,
    historyIndex,
    pathSegments,
    displayPath,
    formatPathInput,
    sortKey,
    sortAsc,
    toggleSort,
    sortedFiles,
    loadList,
    navigate,
    navigateToSegment,
    goToPath,
    goBack,
    goForward,
    goUp,
    refresh,
    traditionalRelPathForFile,
  }
}

export type TmExplorer = ReturnType<typeof useTmExplorer>
