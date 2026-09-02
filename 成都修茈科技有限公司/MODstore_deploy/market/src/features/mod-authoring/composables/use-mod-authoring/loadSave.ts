// 核心加载与保存：详情/摘要刷新、AI 蓝图读取、manifest 保存、前端再生成（原单体实现原样迁移）。
import { ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { api } from '@/api'
import type { LooseRecord } from '../../types'
import type { ModAuthoringData, ModAuthoringSummary } from './types'
import type { Flash } from './core'

export interface ManifestSidebarStatusLike {
  industryId: string
  industryName: string
  menuCount: number
  menuOverrideCount: number
  modId: string
}

export interface LoadSaveDeps {
  modData: Ref<ModAuthoringData | null>
  summary: Ref<ModAuthoringSummary | null>
  aiBlueprint: Ref<LooseRecord | null>
  manifestText: Ref<string>
  manifestSaveWarnings: Ref<string[]>
  loading: Ref<boolean>
  loadError: Ref<string>
  modId: ComputedRef<string>
  flash: Flash
  fileSet: ComputedRef<Set<string>>
  normPath: (p: unknown) => string
  selectedPath: Ref<string>
  fileContent: Ref<string>
  fileWarnings: Ref<string[]>
  loadSelectedFile: () => Promise<void>
  refreshSnapshots: () => Promise<void>
  loadLinkableWorkflows: () => Promise<void>
  manifestSidebarStatus: ComputedRef<ManifestSidebarStatusLike>
}

export function createLoadSave(deps: LoadSaveDeps) {
  const {
    modData,
    summary,
    aiBlueprint,
    manifestText,
    manifestSaveWarnings,
    loading,
    loadError,
    modId,
    flash,
    fileSet,
    normPath,
    selectedPath,
    fileContent,
    fileWarnings,
    loadSelectedFile,
    refreshSnapshots,
    loadLinkableWorkflows,
    manifestSidebarStatus,
  } = deps

  const savingManifest = ref(false)
  const loadingSummary = ref(false)
  const frontendBusy = ref(false)
  const frontendBrief = ref('')

  async function refreshSummary() {
    if (!modId.value) return
    loadingSummary.value = true
    try {
      summary.value = (await api.getModAuthoringSummary(modId.value)) as ModAuthoringSummary
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      loadingSummary.value = false
    }
  }

  async function loadAiBlueprint() {
    aiBlueprint.value = null
    if (!modId.value) return
    if (!fileSet.value.has('config/ai_blueprint.json')) return
    try {
      const res = await api.getModFile(modId.value, 'config/ai_blueprint.json')
      const parsed = JSON.parse(String(res?.content || '{}'))
      aiBlueprint.value = parsed && typeof parsed === 'object' ? (parsed as LooseRecord) : null
    } catch {
      aiBlueprint.value = null
    }
  }

  async function reload() {
    loadError.value = ''
    loading.value = true
    manifestSaveWarnings.value = []
    fileWarnings.value = []
    try {
      const [detail, sum] = await Promise.all([api.getMod(modId.value), api.getModAuthoringSummary(modId.value).catch(() => null)])
      modData.value = detail as ModAuthoringData
      summary.value = sum as ModAuthoringSummary | null
      manifestText.value = JSON.stringify(detail.manifest || {}, null, 2)
      await loadAiBlueprint()
      void loadLinkableWorkflows()
      void refreshSnapshots()
      if (!selectedPath.value || !fileSet.value.has(normPath(selectedPath.value))) {
        selectedPath.value = ''
        fileContent.value = ''
      }
    } catch (e) {
      modData.value = null
      summary.value = null
      loadError.value = (e as Error)?.message || String(e)
    } finally {
      loading.value = false
    }
  }

  async function saveManifest(opts?: { successMessage?: string; flashDurationMs?: number }) {
    let parsed
    try {
      parsed = JSON.parse(manifestText.value)
    } catch (e) {
      flash('JSON 解析失败: ' + ((e as Error)?.message || String(e)), false)
      return
    }
    savingManifest.value = true
    manifestSaveWarnings.value = []
    try {
      try {
        await api.captureModSnapshot(modId.value, `保存前 ${new Date().toISOString().slice(0, 19)}`)
      } catch {
        /* 快照失败不阻断保存 */
      }
      const res = await api.putModManifest(modId.value, parsed)
      manifestSaveWarnings.value = Array.isArray(res.warnings) ? res.warnings : []
      flash(opts?.successMessage ?? 'manifest 已保存', true, opts?.flashDurationMs ?? 5000)
      await reload()
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      savingManifest.value = false
    }
  }

  async function regenerateFrontend() {
    if (!modId.value) return
    frontendBusy.value = true
    try {
      const res = await api.regenerateModFrontend(modId.value, frontendBrief.value.trim())
      const menuN = manifestSidebarStatus.value.menuCount
      flash(`前端已生成（菜单 ${menuN} 项）`, true, 4000)
      if (res.frontend_spec && typeof res.frontend_spec === 'object') {
        aiBlueprint.value = {
          ...(aiBlueprint.value && typeof aiBlueprint.value === 'object' ? aiBlueprint.value : {}),
          frontend_app: res.frontend_spec,
        }
      }
      selectedPath.value = 'frontend/views/HomeView.vue'
      await reload()
      if (fileSet.value.has(selectedPath.value)) {
        await loadSelectedFile()
      }
    } catch (e) {
      flash((e as Error)?.message || String(e), false)
    } finally {
      frontendBusy.value = false
    }
  }

  return {
    savingManifest,
    loadingSummary,
    frontendBusy,
    frontendBrief,
    refreshSummary,
    loadAiBlueprint,
    reload,
    saveManifest,
    regenerateFrontend,
  }
}
