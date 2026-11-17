import { computed, ref, watch } from 'vue'
import { ArrayDriver, type DirEntry } from '@/components/template/vuefinder'
import type { TemplatePreviewCtx } from './assemble'
import type { TplRecord } from './tpTemplateMeta'

/**
 * 模板库文件管理器适配层（VueFinder 4.8.0, MIT）。
 * 只把模板列表映射成只读的虚拟目录/文件，业务动作仍走既有 assemble ctx。
 */

const CATEGORY_EXTENSION: Record<string, string> = {
  excel: 'xlsx',
  csv: 'csv',
  word: 'docx',
  pptx: 'pptx',
  pdf: 'pdf',
  label: 'png',
}

const CATEGORY_MIME: Record<string, string> = {
  excel: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  csv: 'text/csv',
  word: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  pdf: 'application/pdf',
  label: 'image/png',
}

const FALLBACK_FOLDER = '未分组'
const STORAGE = 'templates'

function modifiedAt(tpl: TplRecord): number {
  const raw = tpl.updated_at ?? tpl.updatedAt ?? tpl.created_at
  const parsed = typeof raw === 'string' || typeof raw === 'number' ? Date.parse(String(raw)) : NaN
  return Number.isFinite(parsed) ? parsed : Date.now()
}

export function useTpVueFinder(tp: TemplatePreviewCtx) {
  const list = computed<TplRecord[]>(() => {
    const scoped = tp.exportScopedTemplates?.value
    return Array.isArray(scoped) ? scoped : []
  })

  const byPath = new Map<string, TplRecord>()
  const selectedTemplate = ref<TplRecord | null>(null)

  function fileNameFor(tpl: TplRecord): string {
    const category = String(tpl.category || '').trim()
    const extension = CATEGORY_EXTENSION[category] || 'bin'
    const base = String(tpl.name || tpl.filename || '未命名模板').trim()
    return base.toLowerCase().endsWith(`.${extension}`) ? base : `${base}.${extension}`
  }

  function folderFor(tpl: TplRecord): string {
    return String(tp.getTemplateScopeLabel?.(tpl) || FALLBACK_FOLDER).trim() || FALLBACK_FOLDER
  }

  const entries = ref<DirEntry[]>([])
  const libraryVersion = ref(0)
  let selectedPath = ''

  function rebuildEntries() {
    byPath.clear()
    const files: DirEntry[] = []
    const folders = new Set<string>()
    const root = `${STORAGE}://`
    for (const tpl of list.value) {
      const folder = folderFor(tpl)
      folders.add(folder)
      const basename = fileNameFor(tpl)
      const dir = `${root}${encodeURIComponent(folder)}`
      // Identity is independent of the display name, including duplicate names.
      const path = `${dir}/${encodeURIComponent(String(tpl.id))}`
      byPath.set(path, tpl)
      files.push({
        dir,
        basename,
        extension: CATEGORY_EXTENSION[String(tpl.category || '').trim()] || 'bin',
        path,
        storage: STORAGE,
        type: 'file',
        file_size: null,
        last_modified: modifiedAt(tpl),
        mime_type: CATEGORY_MIME[String(tpl.category || '').trim()] || 'application/octet-stream',
        visibility: 'public',
      })
    }
    const dirs: DirEntry[] = [...folders].sort((a, b) => a.localeCompare(b, 'zh-CN')).map((name) => ({
      dir: root,
      basename: name,
      extension: '',
      path: `${root}${encodeURIComponent(name)}`,
      storage: STORAGE,
      type: 'dir',
      file_size: null,
      last_modified: null,
      mime_type: null,
      visibility: 'public',
    }))
    entries.value = [...dirs, ...files]
    libraryVersion.value += 1
    if (selectedTemplate.value) {
      selectedTemplate.value = byPath.get(selectedPath) || null
    }
  }

  const driver = new ArrayDriver({ files: entries, storage: STORAGE, readOnly: true })

  const config = {
    view: 'grid' as const,
    theme: 'silver',
    showMenuBar: false,
    showToolbar: true,
    showBreadcrumbBar: true,
    showTreeView: false,
    showThumbnails: false,
    gridItemWidth: 148,
    gridItemHeight: 132,
    gridItemGap: 12,
    gridItemIconSize: 52,
    persist: false,
  }

  const features = {
    edit: false,
    newfile: false,
    newfolder: false,
    upload: false,
    rename: false,
    delete: false,
    archive: false,
    unarchive: false,
    move: false,
    copy: false,
    download: false,
    preview: false,
    history: false,
    language: false,
    theme: false,
    fullscreen: false,
    search: true,
    pinned: false,
  }

  function onSelect(items: DirEntry[]) {
    const file = items.find((item) => item.type === 'file')
    selectedPath = file?.path || ''
    selectedTemplate.value = file ? byPath.get(file.path) || null : null
  }

  function onFileDclick(event: { item: DirEntry; preventDefault: () => void }) {
    const tpl = byPath.get(event.item.path)
    if (!tpl) return
    event.preventDefault()
    selectedPath = event.item.path
    selectedTemplate.value = tpl
    if (tpl.virtual) tp.startCreateForScope?.(tpl.business_scope)
    else tp.previewTemplate?.(tpl)
  }

  watch(list, rebuildEntries, { immediate: true })

  return {
    driver,
    config,
    features,
    entries,
    libraryVersion,
    selectedTemplate,
    onSelect,
    onFileDclick,
  }
}
