import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useTmToast } from './useTmToast'
import { useTmLazyImages } from './useTmLazyImages'
import { useTmSseWatch } from './useTmSseWatch'
import { useTmExplorer, ROOT_NAME } from './useTmExplorer'
import { useTmExcelPanel } from './useTmExcelPanel'
import { useTmInduct } from './useTmInduct'
import { useTmFileActions } from './useTmFileActions'
import { isImageFile, isExcelFile, getFileIcon, formatSize, formatTime } from './tmFileUtils'

/**
 * 组装传统模式视图全部状态与动作；子组件通过单一 ctx prop 共享，
 * 模板自 TraditionalModeView.vue 逐字迁移，行为不变。
 */
export function assembleTmTraditionalMode() {
  const renameInputRef = ref<HTMLInputElement | null>(null)
  const mkdirInputRef = ref<HTMLInputElement | null>(null)

  const toast = useTmToast()
  const lazy = useTmLazyImages()
  const sse = useTmSseWatch({
    getWatchPath: () => explorer.currentPath.value,
    onFilesChanged: () => { void explorer.loadList(explorer.currentPath.value) },
    onPageVisible: () => lazy.initLazyObserver(),
    onPageHidden: () => lazy.destroyLazyObserver(),
  })
  const explorer = useTmExplorer({
    showToast: toast.showToast,
    onViewModeChanged: () => lazy.initLazyObserver(),
    onAfterListLoaded: () => excel.syncExcelPanelFingerprintFromList(),
    onNavigateReset: () => sse.resetWatchState(),
    onRefreshReset: () => sse.clearChangedFiles(),
    restartSseIfActive: () => sse.restartIfActive(),
  })
  const excel = useTmExcelPanel({
    showToast: toast.showToast,
    refresh: () => explorer.refresh(),
    files: explorer.files,
    relPathFor: explorer.traditionalRelPathForFile,
    resetInduct: () => induct.resetInductState(),
    invalidateInductRows: () => induct.invalidateInductRows(),
  })
  const induct = useTmInduct({ excel, showToast: toast.showToast })
  const fileActions = useTmFileActions({
    showToast: toast.showToast,
    explorer,
    excel,
    renameInputRef,
  })

  onMounted(async () => {
    await explorer.loadList('')
    explorer.pathInput.value = explorer.displayPath.value
    document.addEventListener('visibilitychange', sse.onVisibilityChange)
    sse.startSSE()
    lazy.initLazyObserver()
    document.addEventListener('click', fileActions.hideContextMenu)
  })

  onBeforeUnmount(() => {
    sse.disposeSse()
    lazy.destroyLazyObserver()
    document.removeEventListener('visibilitychange', sse.onVisibilityChange)
    document.removeEventListener('click', fileActions.hideContextMenu)
    toast.disposeToast()
  })

  return {
    ROOT_NAME,
    renameInputRef,
    mkdirInputRef,
    ...toast,
    ...lazy,
    ...sse,
    ...explorer,
    ...excel,
    ...induct,
    ...fileActions,
    isImageFile,
    isExcelFile,
    getFileIcon,
    formatSize,
    formatTime,
  }
}

export type TraditionalModeCtx = ReturnType<typeof assembleTmTraditionalMode>
