/**
 * 数据库管理 · 企业 Mod 分配弹窗（由 AdminDatabaseView.vue 原单文件机械迁出，行为不变）。
 */
import { computed, ref } from 'vue'
import { api } from '../../api'
import type { AdminUserRow, AssignableModRow } from './adminDatabaseHelpers'
import { errMsg } from './adminDatabaseHelpers'

interface UseModEditorCtx {
  flash: (msg: string, ok?: boolean) => void
  loadDatabase: () => Promise<void>
}

export function useModEditor(ctx: UseModEditorCtx) {
  const { flash, loadDatabase } = ctx

  const assignableMods = ref<AssignableModRow[]>([])
  const modEditorOpen = ref(false)
  const modEditorUser = ref<AdminUserRow | null>(null)
  const modEditorSelected = ref<string[]>([])
  const modEditorLoading = ref(false)
  const modEditorSaving = ref(false)

  const assignableModNameById = computed(() => {
    const map: Record<string, string> = {}
    for (const m of assignableMods.value) {
      map[m.id] = m.name
    }
    return map
  })

  function modDisplayName(modId: string): string {
    return assignableModNameById.value[modId] || modId
  }

  async function ensureAssignableModsLoaded() {
    if (assignableMods.value.length > 0) return
    const res = await api.adminEnterpriseAssignableMods()
    assignableMods.value = (res.mods || []) as AssignableModRow[]
  }

  async function openModEditor(row: AdminUserRow) {
    if (!row.is_enterprise) {
      flash('请先将该用户设为企业级', false)
      return
    }
    modEditorUser.value = row
    modEditorOpen.value = true
    modEditorLoading.value = true
    modEditorSelected.value = []
    try {
      await ensureAssignableModsLoaded()
      const detail = await api.adminListUserMods(Number(row.id))
      modEditorSelected.value = Array.isArray(detail.mod_ids) ? [...detail.mod_ids] : [...(row.mod_ids || [])]
    } catch (e) {
      flash(`加载 Mod 列表失败: ${errMsg(e)}`, false)
      modEditorOpen.value = false
    } finally {
      modEditorLoading.value = false
    }
  }

  function closeModEditor() {
    if (modEditorSaving.value) return
    modEditorOpen.value = false
    modEditorUser.value = null
    modEditorSelected.value = []
  }

  async function saveModEditor() {
    const row = modEditorUser.value
    if (!row) return
    const uid = Number(row.id)
    const prev = new Set((row.mod_ids || []).map(String))
    const next = new Set(modEditorSelected.value.map(String))
    const toBind = [...next].filter((id) => !prev.has(id))
    const toUnbind = [...prev].filter((id) => !next.has(id))
    if (!toBind.length && !toUnbind.length) {
      closeModEditor()
      return
    }
    modEditorSaving.value = true
    try {
      for (const mid of toBind) {
        await api.adminBindUserMod(uid, mid)
      }
      for (const mid of toUnbind) {
        await api.adminUnbindUserMod(uid, mid)
      }
      flash(`用户 #${uid} 企业 Mod 已更新`)
      closeModEditor()
      await loadDatabase()
    } catch (e) {
      flash(`保存失败: ${errMsg(e)}`, false)
    } finally {
      modEditorSaving.value = false
    }
  }

  return {
    assignableMods,
    modEditorOpen,
    modEditorUser,
    modEditorSelected,
    modEditorLoading,
    modEditorSaving,
    modDisplayName,
    ensureAssignableModsLoaded,
    openModEditor,
    closeModEditor,
    saveModEditor,
  }
}
