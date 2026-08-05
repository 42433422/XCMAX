import { computed, reactive, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { get } from '@/api'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { appAlert } from '@/utils/appDialog'
import { intakeCompanyName } from './useCustomerServiceFormat'
import type { ClientSummaries, EnterpriseUserRow, MarketUserPickerRow, PipelineReadShape } from './internalCsTypes'

const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge'

type CustomerListDeps = {
  selectedUserId: Ref<number | null>
  selectedEnterpriseUser: ComputedRef<EnterpriseUserRow | null>
  /** 展开中的客户实时 pipeline（仅读取展示所需字段） */
  customerPipeline: PipelineReadShape
  clientSummaries: ClientSummaries
  expandedClientId: Ref<number | null>
  enterpriseUsers: Ref<EnterpriseUserRow[]>
  loadingEnterpriseUsers: Ref<boolean>
  loadEnterpriseUsers: () => Promise<void>
  loadClientSummary: (userId: number, username?: string) => Promise<void>
  loadPipelineForCustomer: () => Promise<void>
  selectEnterprise: (userId: number) => void
}

/**
 * 内部客服左侧客户列表 + 商机漏斗 + 客户摘要 + 「添加企业客户」模态框。
 * 仅持有列表/漏斗/摘要相关的状态与逻辑。
 */
export function useCustomerList(deps: CustomerListDeps) {
  const {
    selectedUserId,
    selectedEnterpriseUser,
    customerPipeline,
    clientSummaries,
    expandedClientId,
    enterpriseUsers,
    loadingEnterpriseUsers,
    loadEnterpriseUsers,
    loadClientSummary,
    loadPipelineForCustomer,
    selectEnterprise,
  } = deps

  const funnelExpanded = ref(true)
  const funnelLoading = ref(false)
  const funnelStages = ref<Array<{ id: string; label: string; count: number }>>([])
  const funnelTotalClients = ref(0)
  const funnelStageFilter = ref('')

  async function loadPipelineFunnel() {
    funnelLoading.value = true
    try {
      const res = await get(`${CS_BRIDGE}/user-cs/pipeline/funnel`, { max_clients_per_stage: 8 })
      const data = (res as { data?: { stages?: Array<{ id: string; label: string; count: number }>; total_clients?: number } })
        ?.data
      funnelStages.value = data?.stages || []
      funnelTotalClients.value = Number(data?.total_clients || 0)
    } catch {
      funnelStages.value = []
      funnelTotalClients.value = 0
    } finally {
      funnelLoading.value = false
    }
  }

  function toggleFunnelStageFilter(stageId: string) {
    funnelStageFilter.value = funnelStageFilter.value === stageId ? '' : stageId
  }

  function getClientSummary(userId: number) {
    return (
      clientSummaries[userId] || {
        stage: 'idle',
        last_message_preview: '',
        intake_sent: false,
        display_name: '',
      }
    )
  }

  function liveCompanyName(): string {
    return intakeCompanyName(customerPipeline)
  }

  function displayClientName(u: { id: number; username: string }) {
    if (expandedClientId.value === u.id) {
      const live = liveCompanyName()
      if (live) return live
      const pipeName = customerPipeline.username.trim()
      if (pipeName && pipeName.toLowerCase() !== u.username.toLowerCase()) return pipeName
    }
    const cached = getClientSummary(u.id).display_name
    if (cached) return cached
    return u.username
  }

  function cardNameTitle(u: { id: number; username: string }) {
    const shown = displayClientName(u)
    const login = String(u.username || '').trim()
    if (shown && login && shown.toLowerCase() !== login.toLowerCase()) {
      return `登录账号：${login}`
    }
    return ''
  }

  const filteredEnterpriseUsers = computed(() => {
    const filter = funnelStageFilter.value
    if (!filter) return enterpriseUsers.value
    return enterpriseUsers.value.filter((u) => getClientSummary(u.id).stage === filter)
  })

  async function loadAllClientSummaries() {
    await Promise.all(enterpriseUsers.value.map((u) => loadClientSummary(u.id, u.username)))
  }

  // ---- 添加企业客户模态框 ----
  const addCustomerModal = reactive({
    visible: false,
    loading: false,
    filter: '',
    savingId: 0,
    marketUsers: [] as MarketUserPickerRow[],
    pipelineIds: new Set<number>(),
  })

  const addCustomerPickerRows = computed(() => {
    const q = addCustomerModal.filter.trim().toLowerCase()
    let rows = addCustomerModal.marketUsers
    if (q) {
      rows = rows.filter(
        (u) =>
          u.username.toLowerCase().includes(q) ||
          String(u.email || '')
            .toLowerCase()
            .includes(q) ||
          String(u.id).includes(q),
      )
    }
    return rows.slice(0, 80)
  })

  function isCustomerListed(userId: number) {
    return enterpriseUsers.value.some((u) => u.id === userId)
  }

  async function openAddCustomerModal() {
    addCustomerModal.visible = true
    addCustomerModal.loading = true
    addCustomerModal.filter = ''
    try {
      const [adminRes, clientsRes] = await Promise.all([
        xcmaxAdminApi.listUsers(),
        get<{ data?: { clients?: Array<{ market_user_id: number }> } }>(`${CS_BRIDGE}/user-cs/clients`),
      ])
      const data = adminRes as {
        users?: MarketUserPickerRow[]
        data?: { users?: MarketUserPickerRow[] }
      }
      const users = data.users || data.data?.users || []
      const pipelineIds = new Set(
        (clientsRes?.data?.clients || [])
          .map((c) => Number(c.market_user_id))
          .filter((id) => id > 0),
      )
      addCustomerModal.pipelineIds = pipelineIds
      addCustomerModal.marketUsers = users
        .map((u) => ({
          ...u,
          has_pipeline: pipelineIds.has(u.id),
        }))
        .sort((a, b) => {
          const aListed = isCustomerListed(a.id) ? 0 : 1
          const bListed = isCustomerListed(b.id) ? 0 : 1
          if (aListed !== bListed) return aListed - bListed
          return a.username.localeCompare(b.username, 'zh-CN')
        })
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : String(e))
      addCustomerModal.visible = false
    } finally {
      addCustomerModal.loading = false
    }
  }

  async function markUserEnterprise(u: MarketUserPickerRow) {
    addCustomerModal.savingId = u.id
    try {
      await xcmaxAdminApi.setUserEnterprise(u.id, true)
      u.is_enterprise = true
      await loadEnterpriseUsers()
      await loadAllClientSummaries()
      expandedClientId.value = u.id
      selectEnterprise(u.id)
      await loadPipelineForCustomer()
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : String(e))
    } finally {
      addCustomerModal.savingId = 0
    }
  }

  function focusListedCustomer(userId: number) {
    addCustomerModal.visible = false
    expandedClientId.value = userId
    selectEnterprise(userId)
    loadPipelineForCustomer()
  }

  return {
    enterpriseUsers,
    loadingEnterpriseUsers,
    loadEnterpriseUsers,
    funnelExpanded,
    funnelLoading,
    funnelStages,
    funnelTotalClients,
    funnelStageFilter,
    loadPipelineFunnel,
    toggleFunnelStageFilter,
    getClientSummary,
    displayClientName,
    cardNameTitle,
    filteredEnterpriseUsers,
    loadAllClientSummaries,
    addCustomerModal,
    addCustomerPickerRows,
    isCustomerListed,
    openAddCustomerModal,
    markUserEnterprise,
    focusListedCustomer,
  }
}