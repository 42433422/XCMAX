/**
 * 管理员 AI 员工账号池视图逻辑（由 AdminAiAccountsView.vue 原单文件机械迁出，行为不变）。
 * 覆盖：账号列表/过滤、新建/编辑/轮换/删除、QQ 桥接状态与 webhook URL 复制。
 *
 * 设计原则：
 * - 不在前端缓存任何明文密钥；所有 secret 字段在表单提交后立即清空。
 * - webhook URL 由后端 channel.paths 直接给，前端只负责拼接 host。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { api } from '../../api'

export type ChannelPath = { label: string; path: string }
export type Channel = { platform: string; paths: ChannelPath[] }
export type Account = {
  id: number
  platform: string
  external_id: string
  employee_id: string
  display_name: string
  status: string
  sandbox: boolean
  notes: string
  has_secret: boolean
  secrets_path: string
  created_at?: string
  updated_at?: string
  channel: Channel
}
export type ListResp = { items: Account[]; total: number; limit: number; offset: number }
export type FirstClassEmp = {
  employee_id: string
  app_id: string
  webhook_key: string
  webhook_path: string
  by_employee_path: string
  app_secret_env: string
  app_secret_present: boolean
  uses_executor: boolean
}
export type QqStatus = {
  configured: boolean
  credential_source: string
  app_id: string | null
  butler_employee_id: string
  first_class_employees: FirstClassEmp[]
  sandbox: boolean
  api_base: string
}

export function useAdminAiAccounts() {
  const router = useRouter()
  const authStore = useAuthStore()
  const { isAdmin } = storeToRefs(authStore)

  const loading = ref(false)
  const error = ref('')
  const items = ref<Account[]>([])
  const total = ref(0)
  const filterPlatform = ref('')
  const filterEmployee = ref('')
  const filterStatus = ref('')

  const qqStatus = ref<QqStatus | null>(null)

  const createOpen = ref(false)
  const createForm = reactive({
    platform: 'qq',
    external_id: '',
    employee_id: '',
    display_name: '',
    sandbox: false,
    notes: '',
    app_id: '',
    app_secret: '',
    bot_token: '',
  })
  const createBusy = ref(false)

  const rotateOpenId = ref<number | null>(null)
  const rotateForm = reactive({ app_id: '', app_secret: '', bot_token: '' })
  const rotateBusy = ref(false)

  const editOpenId = ref<number | null>(null)
  const editForm = reactive({ employee_id: '', display_name: '', status: 'active', sandbox: false, notes: '' })
  const editBusy = ref(false)

  function host(): string {
    if (typeof window === 'undefined') return ''
    return `${window.location.protocol}//${window.location.host}`
  }

  const fullWebhookList = computed(() => {
    const base = host()
    return items.value.map((it) => ({
      id: it.id,
      employee_id: it.employee_id,
      paths: (it.channel?.paths || []).map((p) => ({ label: p.label, url: `${base}${p.path}` })),
    }))
  })

  async function loadAll() {
    if (!isAdmin.value) return
    loading.value = true
    error.value = ''
    try {
      const params: Record<string, string | number> = { limit: 200 }
      if (filterPlatform.value) params.platform = filterPlatform.value
      if (filterEmployee.value) params.employee_id = filterEmployee.value
      if (filterStatus.value) params.status = filterStatus.value
      const resp = (await api.adminListAiAccounts(params as never)) as ListResp
      items.value = resp.items || []
      total.value = resp.total || 0
      try {
        qqStatus.value = (await api.butlerQqStatus()) as QqStatus
      } catch {
        qqStatus.value = null
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  function openCreate() {
    createForm.platform = 'qq'
    createForm.external_id = ''
    createForm.employee_id = ''
    createForm.display_name = ''
    createForm.sandbox = false
    createForm.notes = ''
    createForm.app_id = ''
    createForm.app_secret = ''
    createForm.bot_token = ''
    createOpen.value = true
  }

  function closeCreate() {
    createOpen.value = false
    createForm.app_secret = ''
    createForm.bot_token = ''
  }

  async function submitCreate() {
    if (createBusy.value) return
    if (!createForm.platform || !createForm.external_id || !createForm.employee_id) {
      error.value = 'platform / external_id / employee_id 都不能为空'
      return
    }
    if (createForm.platform === 'qq' && (!createForm.app_id || !createForm.app_secret || !createForm.bot_token)) {
      error.value = 'QQ 平台需要 app_id / app_secret / bot_token 三个字段'
      return
    }
    createBusy.value = true
    error.value = ''
    try {
      const secret =
        createForm.platform === 'qq'
          ? { app_id: createForm.app_id, app_secret: createForm.app_secret, bot_token: createForm.bot_token }
          : {}
      await api.adminCreateAiAccount({
        platform: createForm.platform,
        external_id: createForm.external_id,
        employee_id: createForm.employee_id,
        display_name: createForm.display_name || undefined,
        sandbox: createForm.sandbox,
        notes: createForm.notes || undefined,
        secret,
      })
      closeCreate()
      await loadAll()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      createBusy.value = false
    }
  }

  function openEdit(a: Account) {
    editOpenId.value = a.id
    editForm.employee_id = a.employee_id
    editForm.display_name = a.display_name || ''
    editForm.status = a.status
    editForm.sandbox = !!a.sandbox
    editForm.notes = a.notes || ''
  }
  function closeEdit() {
    editOpenId.value = null
  }
  async function submitEdit() {
    if (editOpenId.value == null || editBusy.value) return
    editBusy.value = true
    error.value = ''
    try {
      await api.adminUpdateAiAccount(editOpenId.value, {
        employee_id: editForm.employee_id,
        display_name: editForm.display_name,
        status: editForm.status,
        sandbox: editForm.sandbox,
        notes: editForm.notes,
      })
      closeEdit()
      await loadAll()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      editBusy.value = false
    }
  }

  function openRotate(a: Account) {
    rotateOpenId.value = a.id
    rotateForm.app_id = ''
    rotateForm.app_secret = ''
    rotateForm.bot_token = ''
  }
  function closeRotate() {
    rotateOpenId.value = null
    rotateForm.app_secret = ''
    rotateForm.bot_token = ''
  }
  async function submitRotate() {
    if (rotateOpenId.value == null || rotateBusy.value) return
    if (!rotateForm.app_id || !rotateForm.app_secret || !rotateForm.bot_token) {
      error.value = 'QQ 轮换需要 app_id / app_secret / bot_token 三个字段（粘贴 QQ 后台最新值）'
      return
    }
    rotateBusy.value = true
    error.value = ''
    try {
      await api.adminRotateAiAccountSecret(rotateOpenId.value, {
        app_id: rotateForm.app_id,
        app_secret: rotateForm.app_secret,
        bot_token: rotateForm.bot_token,
      })
      closeRotate()
      await loadAll()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      rotateBusy.value = false
    }
  }

  async function removeAccount(a: Account) {
    if (!window.confirm(`确认删除账号 #${a.id}（${a.platform}/${a.external_id}）？密钥文件也会一并销毁。`)) return
    error.value = ''
    try {
      await api.adminDeleteAiAccount(a.id)
      await loadAll()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function copyText(text: string) {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        const el = document.createElement('textarea')
        el.value = text
        document.body.appendChild(el)
        el.select()
        document.execCommand('copy')
        document.body.removeChild(el)
      }
    } catch {
      /* clipboard 权限问题就静默失败，让用户手动选 */
    }
  }

  onMounted(() => void loadAll())

  return {
    router,
    isAdmin,
    loading,
    error,
    items,
    total,
    filterPlatform,
    filterEmployee,
    filterStatus,
    qqStatus,
    createOpen,
    createForm,
    createBusy,
    rotateOpenId,
    rotateForm,
    rotateBusy,
    editOpenId,
    editForm,
    editBusy,
    host,
    fullWebhookList,
    loadAll,
    openCreate,
    closeCreate,
    submitCreate,
    openEdit,
    closeEdit,
    submitEdit,
    openRotate,
    closeRotate,
    submitRotate,
    removeAccount,
    copyText,
  }
}
