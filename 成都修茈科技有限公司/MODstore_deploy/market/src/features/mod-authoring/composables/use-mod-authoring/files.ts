// Mod 文件浏览与编辑：文件列表、选中文件加载/保存、完成度 checklist（原单体实现原样迁移）。
import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { api } from '@/api'
import { asLooseRecord } from '../../types'
import type { ModAuthoringData } from './types'
import type { Flash } from './core'

export interface FilesDeps {
  modData: Ref<ModAuthoringData | null>
  modId: ComputedRef<string>
  flash: Flash
  reload: () => Promise<void>
}

export function createFiles(deps: FilesDeps) {
  const { modData, modId, flash, reload } = deps

  const selectedPath = ref('')
  const fileContent = ref('')
  const loadingFile = ref(false)
  const savingFile = ref(false)
  const fileWarnings = ref<string[]>([])

  function normPath(p: unknown): string {
    return String(p || '')
      .replace(/\\/g, '/')
      .replace(/^\//, '')
  }

  const fileSet = computed(() => {
    const files = modData.value?.files
    if (!Array.isArray(files)) return new Set<string>()
    return new Set<string>(files.map((f: unknown) => normPath(f)))
  })

  const scaffoldEnvHint = computed(() => '')

  const sortedFiles = computed(() => {
    const files = modData.value?.files
    if (!Array.isArray(files)) return []
    return [...files].map(normPath).sort((a, b) => a.localeCompare(b))
  })

  const backendEntryRel = computed(() => {
    const backend = asLooseRecord(modData.value?.manifest?.backend)
    const entry = typeof backend.entry === 'string' ? backend.entry : 'blueprints'
    const stem = entry.replace(/\.py$/i, '')
    return `backend/${stem}.py`
  })

  const checklist = computed(() => {
    const fs = fileSet.value
    const entryPath = backendEntryRel.value
    const rows = [
      { key: 'manifest', label: 'manifest.json', ok: fs.has('manifest.json') },
      { key: 'init', label: 'backend/__init__.py', ok: fs.has('backend/__init__.py') },
      { key: 'entry', label: entryPath, ok: fs.has(entryPath) },
      { key: 'routes', label: 'frontend/routes.js', ok: fs.has('frontend/routes.js') },
    ]
    return rows
  })

  const artifactNote = computed(() => {
    const art = modData.value?.manifest?.artifact || modData.value?.manifest?.kind
    if (art === 'employee_pack') return '类型：employee_pack'
    if (art === 'bundle') return '类型：bundle'
    return ''
  })

  async function loadSelectedFile() {
    const p = normPath(selectedPath.value)
    if (!p) return
    loadingFile.value = true
    fileWarnings.value = []
    try {
      const res = await api.getModFile(modId.value, p)
      fileContent.value = res.content ?? ''
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      loadingFile.value = false
    }
  }

  function onPathSelect() {
    fileContent.value = ''
    fileWarnings.value = []
  }

  async function saveFile() {
    const p = normPath(selectedPath.value)
    if (!p) return
    savingFile.value = true
    fileWarnings.value = []
    try {
      const res = await api.putModFile(modId.value, p, fileContent.value)
      fileWarnings.value = Array.isArray(res.manifest_warnings) ? res.manifest_warnings : []
      flash('文件已保存')
      await reload()
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      savingFile.value = false
    }
  }

  return {
    selectedPath,
    fileContent,
    loadingFile,
    savingFile,
    fileWarnings,
    normPath,
    fileSet,
    scaffoldEnvHint,
    sortedFiles,
    backendEntryRel,
    checklist,
    artifactNote,
    loadSelectedFile,
    onPathSelect,
    saveFile,
  }
}
