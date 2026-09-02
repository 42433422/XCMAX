import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import {
  type AdminUser,
  type AssignableMod,
  type EntitlementEmployeePreview,
  type LocalModRow,
  type LocalProfile,
  type WalletRow,
  TIER_OPTIONS,
} from './types'

// AdminEntitlementsView 的状态与纯展示逻辑（与拆分前逐字一致）
export interface AdminEntitlementsState {
  users: Ref<AdminUser[]>
  assignableMods: Ref<AssignableMod[]>
  selectedUserId: Ref<number | null>
  userModIds: Ref<string[]>
  userFilter: Ref<string>
  tierFilter: Ref<string>
  industryFilter: Ref<string>
  loadError: Ref<string>
  modToBind: Ref<string>
  binding: Ref<boolean>
  impersonateLoading: Ref<boolean>
  localStatusLoading: Ref<boolean>
  localStatusError: Ref<string>
  installedMods: Ref<LocalModRow[]>
  syncStatus: Ref<Record<string, unknown> | null>
  forcePushingEntitlements: Ref<boolean>
  walletMap: Ref<Map<number, WalletRow>>
  walletLoadError: Ref<string>
  userProfiles: Ref<Record<string, LocalProfile>>
  userProfilesByMarketId: Ref<Record<string, LocalProfile>>
  profileEditing: Ref<{
    tier: string
    industry_id: string
    account_tier: string
    budget_range: string
    entitled_industries: string[]
  }>
  profileSaving: Ref<boolean>
  createAccountOpen: Ref<boolean>
  creatingAccount: Ref<boolean>
  showNewAccountPassword: Ref<boolean>
  newAccount: Ref<{
    username: string
    password: string
    email: string
    tier: string
    industry_id: string
    is_enterprise: boolean
  }>
  creditingWallet: Ref<boolean>
  creditForm: Ref<{ amount: number; description: string }>
  selectedUser: ComputedRef<AdminUser | null>
  isEnterpriseProfile: ComputedRef<boolean>
  filteredUsers: ComputedRef<AdminUser[]>
  tierStats: ComputedRef<Record<string, number>>
  installedModMap: ComputedRef<Map<string, LocalModRow>>
  installedModIds: ComputedRef<Set<string>>
  selectedInstalledMods: ComputedRef<LocalModRow[]>
  selectedMissingModIds: ComputedRef<string[]>
  selectedWorkflowEmployees: ComputedRef<EntitlementEmployeePreview[]>
  selectedChainCards: ComputedRef<{ label: string; value: string; detail: string }[]>
  syncLastText: ComputedRef<string>
  resolveTier: (u: AdminUser) => string
  tierLabel: (u: AdminUser) => string
  modLabel: (modId: string) => string
  isModInstalled: (modId: string) => boolean
  modInstallText: (modId: string) => string
  walletBalance: (u: AdminUser) => string
  normalizeLocalCatalogRows: (raw: Record<string, unknown>) => LocalModRow[]
}

export function useAdminEntitlementsState(): AdminEntitlementsState {
  const users = ref<AdminUser[]>([])
  const assignableMods = ref<AssignableMod[]>([])
  const selectedUserId = ref<number | null>(null)
  const userModIds = ref<string[]>([])
  const userFilter = ref('')
  const tierFilter = ref('')
  const industryFilter = ref('')
  const loadError = ref('')
  const modToBind = ref('')
  const binding = ref(false)
  const impersonateLoading = ref(false)
  const localStatusLoading = ref(false)
  const localStatusError = ref('')
  const installedMods = ref<LocalModRow[]>([])
  const syncStatus = ref<Record<string, unknown> | null>(null)
  const forcePushingEntitlements = ref(false)

  // 用户钱包余额（远端 market /api/admin/wallets，按 user_id 索引）
  const walletMap = ref<Map<number, WalletRow>>(new Map())
  const walletLoadError = ref('')

  // 用户账号体系（优先按稳定的 market_user_id 合并；username 仅作旧数据兼容）
  const userProfiles = ref<Record<string, LocalProfile>>({})
  const userProfilesByMarketId = ref<Record<string, LocalProfile>>({})
  const profileEditing = ref<{
    tier: string
    industry_id: string
    account_tier: string
    budget_range: string
    entitled_industries: string[]
  }>({ tier: '', industry_id: '', account_tier: '', budget_range: '', entitled_industries: [] })
  const profileSaving = ref(false)
  const createAccountOpen = ref(false)
  const creatingAccount = ref(false)
  const showNewAccountPassword = ref(false)
  const newAccount = ref({
    username: '',
    password: '',
    email: '',
    tier: 'enterprise',
    industry_id: '通用',
    is_enterprise: true,
  })
  const creditingWallet = ref(false)
  const creditForm = ref({
    amount: 100,
    description: '后台加款',
  })

  function resolveTier(u: AdminUser): string {
    return u.tier || (u.is_admin ? 'admin' : u.is_enterprise ? 'enterprise' : 'personal')
  }

  function tierLabel(u: AdminUser): string {
    return TIER_OPTIONS.find((t) => t.value === resolveTier(u))?.label || '个人'
  }

  const selectedUser = computed(() => users.value.find((u) => u.id === selectedUserId.value) || null)
  // 账号等级仅企业用户可设
  const isEnterpriseProfile = computed(() => profileEditing.value.tier === 'enterprise')

  const filteredUsers = computed(() => {
    const q = userFilter.value.trim().toLowerCase()
    const tier = tierFilter.value
    const industry = industryFilter.value
    return users.value.filter((u) => {
      if (tier && resolveTier(u) !== tier) return false
      if (industry && (u.industry_id || '通用') !== industry) return false
      if (!q) return true
      return (
        u.username.toLowerCase().includes(q) ||
        String(u.email || '')
          .toLowerCase()
          .includes(q)
      )
    })
  })

  const tierStats = computed(() => {
    const stats: Record<string, number> = { personal: 0, enterprise: 0, admin: 0 }
    for (const u of users.value) stats[resolveTier(u)] = (stats[resolveTier(u)] || 0) + 1
    return stats
  })

  const installedModMap = computed(() => {
    const m = new Map<string, LocalModRow>()
    for (const row of installedMods.value) {
      const id = String(row?.id || '').trim()
      if (id) m.set(id, row)
    }
    return m
  })

  const installedModIds = computed(() => new Set(installedModMap.value.keys()))

  const selectedInstalledMods = computed(() =>
    userModIds.value.map((id) => installedModMap.value.get(String(id || '').trim())).filter((row): row is LocalModRow => Boolean(row)),
  )

  const selectedMissingModIds = computed(() => userModIds.value.filter((id) => !installedModMap.value.has(String(id || '').trim())))

  const selectedWorkflowEmployees = computed<EntitlementEmployeePreview[]>(() => {
    const seen = new Set<string>()
    const rows: EntitlementEmployeePreview[] = []
    for (const mod of selectedInstalledMods.value) {
      const modId = String(mod.id || '').trim()
      const modName = modLabel(modId)
      for (const employee of mod.workflow_employees || []) {
        const id = String(employee?.id || '').trim()
        if (!id || seen.has(`${modId}:${id}`)) continue
        seen.add(`${modId}:${id}`)
        rows.push({
          id,
          label: String(employee.label || employee.name || employee.title || employee.panel_title || id).trim(),
          modId,
          modName,
          summary: String(employee.panel_summary || '').trim(),
        })
      }
    }
    return rows
  })

  const selectedChainCards = computed(() => {
    const modTotal = userModIds.value.length
    const installedTotal = selectedInstalledMods.value.length
    const employeeTotal = selectedWorkflowEmployees.value.length
    return [
      {
        label: '账号权益',
        value: selectedUser.value?.is_enterprise ? '企业账号' : '普通账号',
        detail: `${modTotal} 个客户 Mod 权益`,
      },
      {
        label: '本机落地',
        value: `${installedTotal}/${modTotal} 可用`,
        detail: selectedMissingModIds.value.length ? '存在未安装 Mod' : '本机安装状态可用',
      },
      {
        label: '信息/手机',
        value: `${employeeTotal} 个员工`,
        detail: '进入信息页、员工空间和手机 AI 员工列表',
      },
      {
        label: '设备执行',
        value: employeeTotal ? '可派工' : '待补员工',
        detail: '手机可经局域网或服务器中继把任务派到电脑执行',
      },
    ]
  })

  const syncLastText = computed(() => {
    const raw = String(syncStatus.value?.last_sync_at || '').trim()
    if (!raw) return ''
    const d = new Date(raw)
    if (Number.isNaN(d.getTime())) return raw
    return d.toLocaleString()
  })

  function modLabel(modId: string) {
    const hit = assignableMods.value.find((m) => m.id === modId)
    return hit?.name || modId
  }

  function isModInstalled(modId: string) {
    return installedModMap.value.has(String(modId || '').trim())
  }

  function modInstallText(modId: string) {
    const row = installedModMap.value.get(String(modId || '').trim())
    if (!row) return '未安装'
    const version = String(row.version || '').trim()
    return version ? `已安装 v${version}` : '已安装'
  }
  function normalizeLocalCatalogRows(raw: Record<string, unknown>): LocalModRow[] {
    const data = (raw?.data && typeof raw.data === 'object' ? raw.data : raw) as Record<string, unknown>
    const installed = Array.isArray(data.installed) ? data.installed : []
    const available = Array.isArray(data.available) ? data.available : []
    const byId = new Map<string, LocalModRow>()
    for (const row of [...available, ...installed]) {
      if (!row || typeof row !== 'object') continue
      const r = row as LocalModRow
      const id = String(r.id || '').trim()
      if (!id) continue
      const prev = byId.get(id) || {}
      const installedFlag = Boolean(prev.is_installed || r.is_installed || installed.includes(row))
      byId.set(id, { ...prev, ...r, id, is_installed: installedFlag })
    }
    return Array.from(byId.values()).filter((row) => row.is_installed)
  }

  function walletBalance(u: AdminUser): string {
    if (walletLoadError.value) return '查询失败'
    const w = walletMap.value.get(u.id)
    if (!w || w.balance === null || w.balance === undefined) return '¥0.00'
    const n = typeof w.balance === 'string' ? parseFloat(w.balance) : w.balance
    if (Number.isNaN(n)) return '—'
    return `¥${n.toFixed(2)}`
  }

  return {
    users,
    assignableMods,
    selectedUserId,
    userModIds,
    userFilter,
    tierFilter,
    industryFilter,
    loadError,
    modToBind,
    binding,
    impersonateLoading,
    localStatusLoading,
    localStatusError,
    installedMods,
    syncStatus,
    forcePushingEntitlements,
    walletMap,
    walletLoadError,
    userProfiles,
    userProfilesByMarketId,
    profileEditing,
    profileSaving,
    createAccountOpen,
    creatingAccount,
    showNewAccountPassword,
    newAccount,
    creditingWallet,
    creditForm,
    selectedUser,
    isEnterpriseProfile,
    filteredUsers,
    tierStats,
    installedModMap,
    installedModIds,
    selectedInstalledMods,
    selectedMissingModIds,
    selectedWorkflowEmployees,
    selectedChainCards,
    syncLastText,
    resolveTier,
    tierLabel,
    modLabel,
    isModInstalled,
    modInstallText,
    walletBalance,
    normalizeLocalCatalogRows,
  }
}
