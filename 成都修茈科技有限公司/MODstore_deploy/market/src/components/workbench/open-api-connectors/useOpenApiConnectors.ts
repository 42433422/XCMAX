/**
 * 第三方 API 连接器 · 全部交互逻辑（由 OpenApiConnectorsPanel.vue 原单文件机械迁出，行为不变）。
 */
import { computed, reactive, ref, watch } from 'vue'
import {
  importConnector,
  listConnectors,
  getConnector,
  deleteConnector,
  saveCredentials,
  deleteCredentials,
  toggleOperation,
  testOperation,
  publishWorkflowNode,
  type ConnectorDetailResponse,
  type OpenApiAuthType,
  type OpenApiConnectorSummary,
  type OpenApiOperationSummary,
  type OpenApiTestResult,
} from '../../../application/openApiConnectorsApi'

export function useOpenApiConnectors() {
  const connectors = ref<OpenApiConnectorSummary[]>([])
  const detail = ref<ConnectorDetailResponse | null>(null)
  const selectedId = ref<number | null>(null)
  const activeOperationId = ref<string>('')
  const testResult = ref<OpenApiTestResult | null>(null)
  const publishMessage = ref('')

  const state = reactive({
    listLoading: false,
    importing: false,
    importError: '',
    savingCredential: false,
    testing: false,
    publishing: false,
  })

  const importForm = reactive({
    name: '',
    description: '',
    spec_text: '',
    spec_url: '',
    base_url_override: '',
  })

  const credentialForm = reactive({
    auth_type: 'none' as OpenApiAuthType,
    token: '',
    key: '',
    name: 'X-API-Key',
    in: 'header' as 'header' | 'query',
    username: '',
    password: '',
    token_url: '',
    client_id: '',
    client_secret: '',
    scope: '',
  })

  const testForm = reactive({
    params: '{}',
    body: '',
    headers: '{}',
    error: '',
  })

  const publishForm = reactive({
    workflow_id: 0,
    name: '',
  })

  const canImport = computed(
    () => importForm.name.trim().length > 0 && (importForm.spec_text.trim().length > 0 || importForm.spec_url.trim().length > 0),
  )
  const canPublish = computed(() => publishForm.workflow_id > 0 && !!activeOperationId.value)

  const activeOperation = computed<OpenApiOperationSummary | null>(() => {
    if (!detail.value) return null
    return detail.value.operations.find((op) => op.operation_id === activeOperationId.value) || null
  })

  const hasCredentialPreview = computed(() => {
    if (!detail.value) return false
    const preview = detail.value.credential.config_preview
    return !!preview && Object.keys(preview).length > 0
  })

  async function refreshList() {
    state.listLoading = true
    try {
      const res = await listConnectors()
      connectors.value = res.items || []
      if (selectedId.value && !connectors.value.some((c) => c.id === selectedId.value)) {
        selectedId.value = null
        detail.value = null
      }
    } finally {
      state.listLoading = false
    }
  }

  async function loadDetail(id: number) {
    const res = await getConnector(id)
    detail.value = res
    selectedId.value = id
    activeOperationId.value = res.operations[0]?.operation_id || ''
    syncCredentialForm(res)
  }

  async function selectConnector(id: number) {
    if (selectedId.value === id) return
    testResult.value = null
    publishMessage.value = ''
    await loadDetail(id)
  }

  function syncCredentialForm(res: ConnectorDetailResponse) {
    const cur = res.credential
    credentialForm.auth_type = (cur.auth_type as OpenApiAuthType) || 'none'
    credentialForm.token = ''
    credentialForm.key = ''
    credentialForm.name = (cur.config_preview?.name as string) || 'X-API-Key'
    credentialForm.in = ((cur.config_preview?.in as 'header' | 'query') || 'header') as 'header' | 'query'
    credentialForm.username = (cur.config_preview?.username as string) || ''
    credentialForm.password = ''
    credentialForm.token_url = (cur.config_preview?.token_url as string) || ''
    credentialForm.client_id = (cur.config_preview?.client_id as string) || ''
    credentialForm.client_secret = ''
    credentialForm.scope = (cur.config_preview?.scope as string) || ''
  }

  function formatPreview(view: ConnectorDetailResponse['credential']) {
    return JSON.stringify(
      {
        auth_type: view.auth_type,
        configured: view.configured,
        preview: view.config_preview,
        updated_at: view.updated_at,
      },
      null,
      2,
    )
  }

  function formatTestResult(result: OpenApiTestResult) {
    return JSON.stringify(
      {
        ok: result.ok,
        status_code: result.status_code,
        duration_ms: result.duration_ms,
        url: result.url,
        method: result.method,
        error: result.error || undefined,
        body: result.body,
      },
      null,
      2,
    )
  }

  function buildCredentialConfig(): Record<string, unknown> {
    switch (credentialForm.auth_type) {
      case 'none':
        return {}
      case 'bearer':
        return { token: credentialForm.token }
      case 'api_key':
        return {
          key: credentialForm.key,
          name: credentialForm.name || 'X-API-Key',
          in: credentialForm.in,
        }
      case 'basic':
        return { username: credentialForm.username, password: credentialForm.password }
      case 'oauth2_client_credentials':
        return {
          token_url: credentialForm.token_url,
          client_id: credentialForm.client_id,
          client_secret: credentialForm.client_secret,
          scope: credentialForm.scope,
        }
      default:
        return {}
    }
  }

  async function handleImport() {
    state.importError = ''
    state.importing = true
    try {
      const res = await importConnector({
        name: importForm.name.trim(),
        description: importForm.description.trim(),
        spec_text: importForm.spec_text.trim() || undefined,
        spec_url: importForm.spec_url.trim() || undefined,
        base_url_override: importForm.base_url_override.trim() || undefined,
      })
      importForm.spec_text = ''
      importForm.spec_url = ''
      await refreshList()
      await loadDetail(res.connector.id)
    } catch (err) {
      state.importError = err instanceof Error ? err.message : String(err)
    } finally {
      state.importing = false
    }
  }

  async function handleDelete() {
    if (!detail.value) return
    if (!window.confirm(`确认删除连接器「${detail.value.connector.name}」？`)) return
    await deleteConnector(detail.value.connector.id)
    detail.value = null
    selectedId.value = null
    activeOperationId.value = ''
    await refreshList()
  }

  async function handleSaveCredential() {
    if (!detail.value) return
    state.savingCredential = true
    try {
      await saveCredentials(detail.value.connector.id, credentialForm.auth_type, buildCredentialConfig())
      await loadDetail(detail.value.connector.id)
    } finally {
      state.savingCredential = false
    }
  }

  async function handleClearCredential() {
    if (!detail.value) return
    await deleteCredentials(detail.value.connector.id)
    await loadDetail(detail.value.connector.id)
  }

  async function handleToggle(op: OpenApiOperationSummary, enabled: boolean) {
    if (!detail.value) return
    await toggleOperation(detail.value.connector.id, op.operation_id, enabled)
    op.enabled = enabled
  }

  function safeJsonParse(raw: string, fallback: unknown): unknown {
    const trimmed = raw.trim()
    if (!trimmed) return fallback
    return JSON.parse(trimmed)
  }

  async function handleTest() {
    if (!detail.value || !activeOperation.value) return
    testForm.error = ''
    state.testing = true
    try {
      const params = safeJsonParse(testForm.params, {}) as Record<string, unknown>
      const body = testForm.body.trim() ? safeJsonParse(testForm.body, null) : null
      const headers = safeJsonParse(testForm.headers, {}) as Record<string, string>
      testResult.value = await testOperation(detail.value.connector.id, activeOperation.value.operation_id, {
        params,
        body,
        headers,
      })
    } catch (err) {
      testForm.error = err instanceof Error ? err.message : String(err)
    } finally {
      state.testing = false
    }
  }

  async function handlePublish() {
    if (!detail.value || !activeOperation.value) return
    state.publishing = true
    publishMessage.value = ''
    try {
      const res = await publishWorkflowNode(detail.value.connector.id, {
        workflow_id: publishForm.workflow_id,
        operation_id: activeOperation.value.operation_id,
        name: publishForm.name.trim() || undefined,
      })
      publishMessage.value = `已添加节点 #${(res.node as { id?: number })?.id ?? '?'}`
    } catch (err) {
      publishMessage.value = err instanceof Error ? err.message : String(err)
    } finally {
      state.publishing = false
    }
  }

  watch(
    () => activeOperationId.value,
    () => {
      testResult.value = null
      testForm.error = ''
    },
  )

  void refreshList()

  return {
    connectors,
    detail,
    selectedId,
    activeOperationId,
    testResult,
    publishMessage,
    state,
    importForm,
    credentialForm,
    testForm,
    publishForm,
    canImport,
    canPublish,
    activeOperation,
    hasCredentialPreview,
    refreshList,
    loadDetail,
    selectConnector,
    formatPreview,
    formatTestResult,
    buildCredentialConfig,
    safeJsonParse,
    handleImport,
    handleDelete,
    handleSaveCredential,
    handleClearCredential,
    handleToggle,
    handleTest,
    handlePublish,
  }
}
