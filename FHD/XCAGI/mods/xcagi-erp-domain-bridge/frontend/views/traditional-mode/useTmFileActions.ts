import { ref, nextTick } from 'vue'
import type { Ref } from 'vue'
import api, { buildFullApiUrl } from '@/api/core'
import { traditionalApi, FileInfo } from '@/api/traditional'
import { appConfirm } from '@/utils/appDialog'
import { isExcelFile, isImageFile } from './tmFileUtils'
import type { TmExplorer } from './useTmExplorer'
import type { TmExcelPanel } from './useTmExcelPanel'

interface TmFileActionsDeps {
  showToast: (message: string, type?: 'success' | 'error') => void
  explorer: TmExplorer
  excel: TmExcelPanel
  renameInputRef: Ref<HTMLInputElement | null>
}

/** 目录文件操作：选择/双击/右键菜单/重命名/删除/新建/上传/下载 */
export function useTmFileActions(deps: TmFileActionsDeps) {
  const { explorer, excel } = deps
  const { currentPath, refresh, traditionalRelPathForFile, loadList, navigate } = explorer
  const { excelPanel } = excel

  const showMkdirDialog = ref(false)
  const newFolderName = ref('')
  const previewImage = ref({ visible: false, url: '', name: '' })
  const contextMenu = ref({ visible: false, x: 0, y: 0, file: null as FileInfo | null })
  const renameDialog = ref({ show: false, file: null as FileInfo | null, newName: '' })

  function showContextMenu(event: MouseEvent, file: FileInfo) {
    contextMenu.value = { visible: true, x: event.clientX, y: event.clientY, file }
    window.addEventListener('click', hideContextMenu, { once: true })
  }

  function hideContextMenu() {
    contextMenu.value.visible = false
  }

  function openFile(file: FileInfo) {
    hideContextMenu()
    onFileDoubleClick(file)
  }

  function startRename(file: FileInfo) {
    hideContextMenu()
    renameDialog.value = { show: true, file, newName: file.name }
    nextTick(() => deps.renameInputRef.value?.focus())
  }

  async function doRename() {
    if (!renameDialog.value.file || !renameDialog.value.newName.trim()) return
    try {
      const res = await traditionalApi.rename({
        path: currentPath.value,
        old_name: renameDialog.value.file.name,
        new_name: renameDialog.value.newName.trim()
      })
      if (res.success) {
        renameDialog.value.show = false
        deps.showToast('重命名成功')
        refresh()
      } else {
        deps.showToast(res.error || '重命名失败', 'error')
      }
    } catch (e: any) {
      deps.showToast('操作失败: ' + (e.message || ''), 'error')
    }
  }

  async function confirmDelete(file: FileInfo) {
    hideContextMenu()
    if (!(await appConfirm(`确定要删除 "${file.name}" 吗？\n${file.is_dir ? '这将删除整个文件夹及其内容！' : ''}`, { danger: true }))) return
    deleteFile(file)
  }

  async function deleteFile(file: FileInfo) {
    const rel = traditionalRelPathForFile(file)
    if (excelPanel.visible && excelPanel.filePath === rel) {
      excel.closeExcelPanel()
    }
    try {
      const res = await traditionalApi.delete({
        path: currentPath.value,
        name: file.name,
        rel_target: rel,
      })
      if (res.success) {
        deps.showToast('删除成功')
        refresh()
      } else {
        deps.showToast(res.error || '删除失败', 'error')
      }
    } catch (e: any) {
      deps.showToast('删除失败: ' + (e.message || ''), 'error')
    }
  }

  async function createFolder() {
    const name = newFolderName.value.trim()
    if (!name) return
    if (/[/\\:*?"<>|]/.test(name)) {
      deps.showToast('文件夹名称包含非法字符', 'error')
      return
    }
    try {
      const res = await traditionalApi.mkdir({ path: currentPath.value, name })
      if (res.success) {
        showMkdirDialog.value = false
        newFolderName.value = ''
        deps.showToast('文件夹创建成功')
        refresh()
      } else {
        deps.showToast(res.error || '创建失败', 'error')
      }
    } catch (e: any) {
      deps.showToast('创建失败: ' + (e.message || ''), 'error')
    }
  }

  async function handleUpload(event: Event) {
    const input = event.target as HTMLInputElement
    const fileList = input.files
    if (!fileList || fileList.length === 0) return

    const uploadPath = currentPath.value
    let uploadedCount = 0
    let failedCount = 0

    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i]
      try {
        const res = await traditionalApi.upload(uploadPath, file)
        if (res.success) {
          uploadedCount++
        } else {
          failedCount++
          deps.showToast(`${file.name} 上传失败: ${res.error || '未知错误'}`, 'error')
        }
      } catch (e: any) {
        failedCount++
        deps.showToast(`${file.name} 上传失败: ${e.message || ''}`, 'error')
      }
    }

    input.value = ''

    if (uploadedCount > 0 && failedCount === 0) {
      deps.showToast(`上传成功：${uploadedCount} 个文件已上传到 "${uploadPath || '根目录'}"`)
    } else if (uploadedCount > 0 && failedCount > 0) {
      deps.showToast(`部分上传成功：${uploadedCount} 个成功，${failedCount} 个失败`, 'error')
    }

    loadList(currentPath.value)
  }

  function selectFile(file: FileInfo) {
    explorer.selectedFile.value = file
    /**
     * 图标视图下单击整块 tile 只会选中，不会走「图标上的读取」；
     * 若侧栏 Excel 已打开，容易仍显示上一个文件，表现为「点的文件和网格/内容不对」。
     * 选中变化时与侧栏同步：Excel 切到当前文件，目录/非 Excel 则关闭侧栏。
     */
    if (!excelPanel.visible) return
    if (file.is_dir) {
      excel.closeExcelPanel()
      return
    }
    if (isExcelFile(file)) {
      const p = traditionalRelPathForFile(file)
      if (p !== excelPanel.filePath) {
        void excel.openTraditionalExcelPanel(file)
      }
      return
    }
    excel.closeExcelPanel()
  }

  /**
   * 双击：文件夹进入；图片内置预览；其它文件走「读取」流程（Excel → GET /read 网页编辑，其它 → 下载）。
   */
  async function onFileDoubleClick(file: FileInfo) {
    if (file.is_dir) {
      const nextPath = traditionalRelPathForFile(file)
      navigate(nextPath)
    } else if (isImageFile(file)) {
      openImagePreview(file)
    } else {
      await openFileByRead(file)
    }
  }

  /** 单击图标/双击非图片：Excel 用 traditionalApi.read 拉取并在侧栏编辑；其它类型走下载。 */
  async function openFileByRead(file: FileInfo) {
    if (!file || file.is_dir) return
    if (isExcelFile(file)) {
      await excel.openTraditionalExcelPanel(file)
      return
    }
    await openTraditionalFileLocally(file, { skipHideMenu: true })
  }

  function getImageUrl(file: FileInfo): string {
    const filePath = traditionalRelPathForFile(file)
    return buildFullApiUrl(`/api/traditional-mode/read?file=${encodeURIComponent(filePath)}`)
  }

  function openImagePreview(file: FileInfo) {
    previewImage.value = { visible: true, url: getImageUrl(file), name: file.name }
  }

  function closeImagePreview() {
    previewImage.value = { visible: false, url: '', name: '' }
  }

  /** 浏览器侧：下载后用户可用本机默认程序打开（Chrome 下载条也可点「打开」）。 */
  async function openTraditionalFileLocally(
    file: FileInfo | null | undefined,
    opts?: { skipHideMenu?: boolean }
  ) {
    if (!opts?.skipHideMenu) {
      hideContextMenu()
    }
    if (!file || file.is_dir) return
    const filePath = traditionalRelPathForFile(file)
    try {
      const res = await api.download('/api/traditional-mode/download', { file: filePath })
      if (!res.ok) {
        let msg = `下载失败 (${res.status})`
        const ct = res.headers.get('content-type') || ''
        if (ct.includes('application/json')) {
          try {
            const j = await res.json()
            msg =
              (typeof j?.error === 'string' && j.error) ||
              (typeof j?.message === 'string' && j.message) ||
              msg
          } catch {
            /* ignore */
          }
        }
        throw new Error(msg)
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = file.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      deps.showToast('已开始下载，完成后可在「下载」中点击「打开」或用资源管理器双击', 'success')
    } catch (e: any) {
      deps.showToast(e?.message || '下载失败', 'error')
    }
  }

  return {
    showMkdirDialog,
    newFolderName,
    previewImage,
    contextMenu,
    renameDialog,
    showContextMenu,
    hideContextMenu,
    openFile,
    startRename,
    doRename,
    confirmDelete,
    deleteFile,
    createFolder,
    handleUpload,
    selectFile,
    onFileDoubleClick,
    openFileByRead,
    getImageUrl,
    openImagePreview,
    closeImagePreview,
    openTraditionalFileLocally,
  }
}

export type TmFileActions = ReturnType<typeof useTmFileActions>
