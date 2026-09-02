// 拆分自 RepositoryView.vue：货架数据、筛选、企业启用范围与提示条状态（逻辑逐字迁移，行为不变）。
import { computed, ref } from 'vue'
import { api } from '../../api'
import { listIndustryPresets, type IndustryPreset } from '../../constants/industryPresets'
import type { EnterpriseUserRow, ModRow } from './repositoryTypes'
import { modIndustryId, modShelfStatus } from './repositoryTypes'

export function useRepositoryCatalog() {
  const mods = ref<ModRow[]>([])
  const loading = ref(true)
  const message = ref('')
  const messageOk = ref(true)
  const industryPresets: IndustryPreset[] = listIndustryPresets()
  const usageByModId = ref<Record<string, string[]>>({})
  const usageLoadError = ref('')
  const shelfQ = ref('')
  const shelfIndustry = ref('')
  const shelfStatus = ref('')
  const shelfVersion = ref('')
  const shelfTest = ref('')
  const shelfScope = ref('')

  const versionOptions = computed(() => {
    const set = new Set<string>()
    for (const m of mods.value) {
      const v = String(m.version || '').trim()
      if (v) set.add(v)
    }
    return Array.from(set).sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
  })

  const hasActiveShelfFilters = computed(
    () => !!(shelfQ.value.trim() || shelfIndustry.value || shelfStatus.value || shelfVersion.value || shelfTest.value || shelfScope.value),
  )

  const filteredMods = computed(() => {
    const q = shelfQ.value.trim().toLowerCase()
    return mods.value.filter((m) => {
      if (q) {
        const hay = [m.id, m.name, m.description, m.library_blurb].map((x) => String(x || '').toLowerCase()).join('\n')
        if (!hay.includes(q)) return false
      }
      if (shelfIndustry.value && modIndustryId(m) !== shelfIndustry.value) return false
      if (shelfStatus.value && modShelfStatus(m) !== shelfStatus.value) return false
      if (shelfVersion.value && String(m.version || '').trim() !== shelfVersion.value) return false
      if (shelfTest.value === 'pass' && !m.ok) return false
      if (shelfTest.value === 'fix' && m.ok) return false
      if (shelfScope.value === 'assigned' && usageNames(m.id).length === 0) return false
      if (shelfScope.value === 'unassigned' && usageNames(m.id).length > 0) return false
      return true
    })
  })

  function modIndustryLabel(m: ModRow): string {
    const id = modIndustryId(m)
    return industryPresets.find((p) => p.id === id)?.name || id
  }

  function usageNames(modId: string): string[] {
    return usageByModId.value[String(modId || '').trim()] || []
  }

  function usageText(modId: string): string {
    const names = usageNames(modId)
    if (!names.length) {
      return usageLoadError.value ? '企业授权：未读取' : '企业授权：未配置（当前账号可编辑，未分配给企业）'
    }
    const preview = names.slice(0, 3).join('、')
    const detail = names.length > 3 ? `${names.length} 家企业（${preview}…）` : `${names.length} 家企业（${preview}）`
    return `企业授权：${detail}`
  }

  function clearShelfFilters() {
    shelfQ.value = ''
    shelfIndustry.value = ''
    shelfStatus.value = ''
    shelfVersion.value = ''
    shelfTest.value = ''
    shelfScope.value = ''
  }

  function flash(msg: string, ok = true) {
    message.value = msg
    messageOk.value = ok
    setTimeout(() => {
      message.value = ''
    }, 5000)
  }

  async function load(opts?: { cacheBust?: boolean }) {
    loading.value = true
    try {
      const res = await api.listMods(!!opts?.cacheBust)
      mods.value = Array.isArray(res?.data) ? res.data : []
    } catch (e) {
      flash('加载 Mod 库失败: ' + ((e as Error)?.message || String(e)), false)
      mods.value = []
    } finally {
      loading.value = false
    }
  }

  async function loadEnterpriseUsage() {
    usageLoadError.value = ''
    try {
      const res = (await api.adminListUsers(200, 0, true)) as {
        users?: EnterpriseUserRow[]
        data?: { users?: EnterpriseUserRow[] }
      }
      const rows: EnterpriseUserRow[] = Array.isArray(res?.users) ? res.users : Array.isArray(res?.data?.users) ? res.data.users : []
      const next: Record<string, string[]> = {}
      for (const user of rows) {
        const label = String(user.username || user.email || user.id || '').trim()
        for (const mid of user.mod_ids || []) {
          const id = String(mid || '').trim()
          if (!id) continue
          if (!next[id]) next[id] = []
          if (label) next[id].push(label)
        }
      }
      usageByModId.value = next
    } catch (e) {
      usageByModId.value = {}
      usageLoadError.value = (e as Error)?.message || String(e)
    }
  }

  return {
    industryPresets,
    mods,
    loading,
    message,
    messageOk,
    usageByModId,
    usageLoadError,
    shelfQ,
    shelfIndustry,
    shelfStatus,
    shelfVersion,
    shelfTest,
    shelfScope,
    versionOptions,
    hasActiveShelfFilters,
    filteredMods,
    modIndustryLabel,
    usageNames,
    usageText,
    clearShelfFilters,
    flash,
    load,
    loadEnterpriseUsage,
  }
}
