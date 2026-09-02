// 开发者 Token 面板主逻辑：列表加载、创建/吊销、明文展示与桌面加密导出。
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../../../api'
import { confirmDanger } from '../../../composables/useDangerConfirm'
import { errText, type DeveloperToken, type KeyExportAuditEvent } from './developerTokenTypes'

export function useDeveloperTokens() {
  const tokens = ref<DeveloperToken[]>([])
  const activeTokens = computed(() => tokens.value.filter((t) => t.is_active))
  const loading = ref(false)
  const errMsg = ref('')

  const showDialog = ref(false)
  const submitBusy = ref(false)
  const draft = reactive({ name: '', scopesCsv: 'mod:sync,catalog:read', expiresDays: '90' })

  const justCreated = ref<{ token: string; meta: DeveloperToken } | null>(null)
  const copied = ref(false)

  const desktopPubB64 = ref('')
  const exportPassword = ref('')
  const exportSelected = ref<number[]>([])
  const exportBusy = ref(false)
  const exportAuditOpen = ref(false)
  const exportAudit = ref<KeyExportAuditEvent[]>([])
  const exportAuditLoading = ref(false)

  function onExportCheck(id: number, ev: Event) {
    const el = ev.target as HTMLInputElement
    if (el.checked) {
      if (!exportSelected.value.includes(id)) exportSelected.value = [...exportSelected.value, id]
    } else {
      exportSelected.value = exportSelected.value.filter((x) => x !== id)
    }
  }

  function selectAllActiveForExport() {
    exportSelected.value = activeTokens.value.map((t) => t.id)
  }

  async function runExportBundle() {
    errMsg.value = ''
    if (!desktopPubB64.value.trim()) {
      errMsg.value = '请粘贴桌面端公钥（SPKI DER 的 base64）'
      return
    }
    if (!exportPassword.value) {
      errMsg.value = '请输入当前登录密码以确认导出'
      return
    }
    if (!exportSelected.value.length) {
      errMsg.value = '请至少勾选一个要下发的 Token'
      return
    }
    if (!confirm('将使用所选 Token 的同名同权限**轮换签发**新明文，并仅写入加密包；网页上旧前缀将立即失效。确定继续？')) return
    exportBusy.value = true
    try {
      const resp = (await api.developerExportKeyBundle({
        recipient_public_key_spki_b64: desktopPubB64.value.trim(),
        current_password: exportPassword.value,
        token_ids: exportSelected.value,
        rotate_source_tokens: true,
      })) as { cipher_b64?: string }
      const b64 = resp.cipher_b64
      if (!b64) throw new Error('响应缺少 cipher_b64')
      const bin = atob(b64)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      const blob = new Blob([bytes], { type: 'application/octet-stream' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `modstore-keybundle-${Date.now()}.msk1`
      a.click()
      URL.revokeObjectURL(url)
      exportPassword.value = ''
      await refresh()
    } catch (e: unknown) {
      errMsg.value = errText(e, '导出失败')
    } finally {
      exportBusy.value = false
    }
  }

  async function loadExportAudit() {
    exportAuditLoading.value = true
    try {
      const r = (await api.developerListKeyExportAudit(30)) as { events?: KeyExportAuditEvent[] }
      exportAudit.value = Array.isArray(r?.events) ? r.events : []
    } catch {
      exportAudit.value = []
    } finally {
      exportAuditLoading.value = false
    }
  }

  async function toggleAudit() {
    exportAuditOpen.value = !exportAuditOpen.value
    if (exportAuditOpen.value && !exportAudit.value.length) await loadExportAudit()
  }

  async function refresh() {
    loading.value = true
    errMsg.value = ''
    try {
      const list = await api.developerListTokens()
      tokens.value = Array.isArray(list) ? list : []
    } catch (e: unknown) {
      errMsg.value = errText(e, '加载失败')
    } finally {
      loading.value = false
    }
  }

  onMounted(refresh)

  function openCreate() {
    draft.name = ''
    draft.scopesCsv = 'mod:sync,catalog:read'
    draft.expiresDays = '90'
    showDialog.value = true
  }

  function addScope(scope: string) {
    const scopes = draft.scopesCsv
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    if (!scopes.includes(scope)) scopes.push(scope)
    draft.scopesCsv = scopes.join(',')
  }

  function closeCreate() {
    if (submitBusy.value) return
    showDialog.value = false
  }

  async function submitCreate() {
    if (!draft.name.trim()) {
      errMsg.value = '请填写 Token 名称'
      return
    }
    const ok = await confirmDanger({
      title: '创建开发者 Token',
      message: `将创建名为「${draft.name.trim()}」的 API Token。创建后请立即复制保存，明文仅显示一次。`,
      confirmLabel: '创建',
    })
    if (!ok) return
    submitBusy.value = true
    errMsg.value = ''
    try {
      const scopes = draft.scopesCsv
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      const days = draft.expiresDays.trim() ? Number(draft.expiresDays) : null
      const resp = (await api.developerCreateToken(
        draft.name.trim(),
        scopes,
        Number.isFinite(days as number) && (days as number) > 0 ? (days as number) : null,
      )) as DeveloperToken & { token?: string }
      showDialog.value = false
      if (resp?.token) {
        const { token, ...meta } = resp
        justCreated.value = { token, meta: meta as DeveloperToken }
        copied.value = false
      }
      await refresh()
    } catch (e: unknown) {
      errMsg.value = errText(e, '创建失败')
    } finally {
      submitBusy.value = false
    }
  }

  async function copyJustCreated() {
    if (!justCreated.value) return
    try {
      await navigator.clipboard.writeText(justCreated.value.token)
      copied.value = true
    } catch {
      const ta = document.createElement('textarea')
      ta.value = justCreated.value.token
      document.body.appendChild(ta)
      ta.select()
      try {
        document.execCommand('copy')
        copied.value = true
      } finally {
        document.body.removeChild(ta)
      }
    }
  }

  function dismissJustCreated() {
    if (!copied.value && !confirm('确定关闭？关闭后将无法再次查看明文，请确认已经复制并妥善保管。')) return
    justCreated.value = null
  }

  async function revoke(row: DeveloperToken) {
    const ok = await confirmDanger({
      title: '吊销 Token',
      message: `确认吊销「${row.name}」？已分发的客户端将立即失效。`,
      confirmLabel: '吊销',
      destructive: true,
    })
    if (!ok) return
    try {
      await api.developerRevokeToken(row.id)
      await refresh()
    } catch (e: unknown) {
      errMsg.value = errText(e, '吊销失败')
    }
  }

  function justCreatedHasScope(scope: string): boolean {
    return !!justCreated.value?.meta?.scopes?.includes(scope)
  }

  return {
    tokens,
    activeTokens,
    loading,
    errMsg,
    showDialog,
    submitBusy,
    draft,
    justCreated,
    copied,
    desktopPubB64,
    exportPassword,
    exportSelected,
    exportBusy,
    exportAuditOpen,
    exportAudit,
    exportAuditLoading,
    onExportCheck,
    selectAllActiveForExport,
    runExportBundle,
    loadExportAudit,
    toggleAudit,
    refresh,
    openCreate,
    addScope,
    closeCreate,
    submitCreate,
    copyJustCreated,
    dismissJustCreated,
    revoke,
    justCreatedHasScope,
  }
}
