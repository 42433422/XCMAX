<template>
  <section class="oac-panel">
    <header class="oac-toolbar">
      <h2 class="oac-title">第三方 API 连接器</h2>
      <p class="oac-tip">导入 OpenAPI 3.x 文档后，平台会解析、生成受控调用客户端，并把 operation 暴露给工作流和 AI 员工。</p>
    </header>

    <section class="oac-import" :aria-busy="state.importing">
      <h3 class="oac-section-title">导入或更新</h3>
      <div class="oac-import-grid">
        <label class="oac-field">
          <span class="oac-field-label">连接器名称 *</span>
          <input
            v-model="importForm.name"
            class="oac-input"
            placeholder="例如：jira-cloud"
            maxlength="128"
            spellcheck="false"
          />
        </label>
        <label class="oac-field">
          <span class="oac-field-label">备注</span>
          <input
            v-model="importForm.description"
            class="oac-input"
            placeholder="可选：用途描述"
            maxlength="200"
          />
        </label>
        <label class="oac-field oac-field--span">
          <span class="oac-field-label">Spec URL（可选，与下方文本二选一）</span>
          <input
            v-model="importForm.spec_url"
            class="oac-input"
            placeholder="https://example.com/openapi.json"
            spellcheck="false"
          />
        </label>
        <label class="oac-field oac-field--span">
          <span class="oac-field-label">覆盖 base_url（可选）</span>
          <input
            v-model="importForm.base_url_override"
            class="oac-input"
            placeholder="留空则使用 spec.servers[0].url"
            spellcheck="false"
          />
        </label>
        <label class="oac-field oac-field--span oac-field--full">
          <span class="oac-field-label">或直接粘贴 OpenAPI 文档（JSON / YAML）</span>
          <textarea
            v-model="importForm.spec_text"
            class="oac-textarea"
            rows="8"
            placeholder="{\n  \&quot;openapi\&quot;: \&quot;3.0.3\&quot;, ...\n}"
            spellcheck="false"
          />
        </label>
      </div>
      <div class="oac-actions">
        <button
          type="button"
          class="oac-btn oac-btn--primary"
          :disabled="state.importing || !canImport"
          @click="handleImport"
        >
          {{ state.importing ? '导入中…' : '解析并导入' }}
        </button>
        <span v-if="state.importError" class="oac-error" role="alert">{{ state.importError }}</span>
      </div>
    </section>

    <section class="oac-list">
      <h3 class="oac-section-title">已有连接器</h3>
      <p v-if="state.listLoading" class="oac-tip">载入中…</p>
      <p v-else-if="!connectors.length" class="oac-tip">还没有连接器，先在上方导入一份 OpenAPI 文档。</p>
      <ul v-else class="oac-cards">
        <li
          v-for="c in connectors"
          :key="c.id"
          class="oac-card"
          :class="{ 'oac-card--selected': selectedId === c.id }"
          @click="selectConnector(c.id)"
        >
          <div class="oac-card-head">
            <strong>{{ c.name }}</strong>
            <span class="oac-card-status">{{ c.status }}</span>
          </div>
          <div class="oac-card-meta">
            <span>{{ c.title || '—' }}</span>
            <span>v{{ c.spec_version || '?' }}</span>
            <span>{{ c.operation_count }} ops</span>
          </div>
          <div class="oac-card-base">{{ c.base_url || '未配置 base_url' }}</div>
        </li>
      </ul>
    </section>

    <section v-if="detail" class="oac-detail">
      <header class="oac-detail-head">
        <h3 class="oac-section-title">{{ detail.connector.name }} · 详情</h3>
        <button type="button" class="oac-btn oac-btn--ghost" @click="loadDetail(detail.connector.id)">
          刷新
        </button>
        <button type="button" class="oac-btn oac-btn--danger" @click="handleDelete">删除</button>
      </header>

      <div class="oac-detail-grid">
        <article class="oac-credential">
          <h4>鉴权配置</h4>
          <p class="oac-tip">密钥仅服务端持有，前端不会留存明文。</p>
          <label class="oac-field">
            <span class="oac-field-label">类型</span>
            <select v-model="credentialForm.auth_type" class="oac-input">
              <option value="none">不需要鉴权</option>
              <option value="bearer">Bearer Token</option>
              <option value="api_key">API Key</option>
              <option value="basic">HTTP Basic</option>
              <option value="oauth2_client_credentials">OAuth2 client_credentials</option>
            </select>
          </label>

          <template v-if="credentialForm.auth_type === 'bearer'">
            <label class="oac-field">
              <span class="oac-field-label">Token</span>
              <input v-model="credentialForm.token" class="oac-input" type="password" autocomplete="off" />
            </label>
          </template>

          <template v-if="credentialForm.auth_type === 'api_key'">
            <label class="oac-field">
              <span class="oac-field-label">API Key</span>
              <input v-model="credentialForm.key" class="oac-input" type="password" autocomplete="off" />
            </label>
            <label class="oac-field">
              <span class="oac-field-label">字段名</span>
              <input v-model="credentialForm.name" class="oac-input" placeholder="X-API-Key" />
            </label>
            <label class="oac-field">
              <span class="oac-field-label">位置</span>
              <select v-model="credentialForm.in" class="oac-input">
                <option value="header">header</option>
                <option value="query">query</option>
              </select>
            </label>
          </template>

          <template v-if="credentialForm.auth_type === 'basic'">
            <label class="oac-field">
              <span class="oac-field-label">用户名</span>
              <input v-model="credentialForm.username" class="oac-input" autocomplete="off" />
            </label>
            <label class="oac-field">
              <span class="oac-field-label">密码</span>
              <input v-model="credentialForm.password" class="oac-input" type="password" autocomplete="off" />
            </label>
          </template>

          <template v-if="credentialForm.auth_type === 'oauth2_client_credentials'">
            <label class="oac-field">
              <span class="oac-field-label">Token URL</span>
              <input v-model="credentialForm.token_url" class="oac-input" />
            </label>
            <label class="oac-field">
              <span class="oac-field-label">Client ID</span>
              <input v-model="credentialForm.client_id" class="oac-input" />
            </label>
            <label class="oac-field">
              <span class="oac-field-label">Client Secret</span>
              <input v-model="credentialForm.client_secret" class="oac-input" type="password" autocomplete="off" />
            </label>
            <label class="oac-field">
              <span class="oac-field-label">Scope</span>
              <input v-model="credentialForm.scope" class="oac-input" placeholder="可选" />
            </label>
          </template>

          <div class="oac-actions">
            <button type="button" class="oac-btn oac-btn--primary" :disabled="state.savingCredential" @click="handleSaveCredential">
              {{ state.savingCredential ? '保存中…' : '保存鉴权' }}
            </button>
            <button v-if="detail.credential.configured" type="button" class="oac-btn oac-btn--ghost" @click="handleClearCredential">
              清除
            </button>
          </div>
          <pre v-if="hasCredentialPreview" class="oac-preview">{{ formatPreview(detail.credential) }}</pre>
        </article>

        <article class="oac-operations">
          <h4>Operations（{{ detail.operations.length }}）</h4>
          <ul class="oac-op-list">
            <li
              v-for="op in detail.operations"
              :key="op.operation_id"
              class="oac-op"
              :class="{ 'oac-op--active': activeOperationId === op.operation_id }"
              @click="activeOperationId = op.operation_id"
            >
              <span class="oac-op-method" :data-method="op.method">{{ op.method }}</span>
              <span class="oac-op-path">{{ op.path }}</span>
              <span class="oac-op-id">{{ op.operation_id }}</span>
              <label class="oac-op-toggle" @click.stop>
                <input type="checkbox" :checked="op.enabled" @change="handleToggle(op, ($event.target as HTMLInputElement).checked)" />
                <span>{{ op.enabled ? '启用' : '已停' }}</span>
              </label>
            </li>
          </ul>
        </article>

        <article v-if="activeOperation" class="oac-test">
          <h4>试调用：{{ activeOperation.operation_id }}</h4>
          <p class="oac-tip">{{ activeOperation.summary || '（无 summary）' }}</p>
          <label class="oac-field">
            <span class="oac-field-label">params (JSON)</span>
            <textarea v-model="testForm.params" class="oac-textarea" rows="3" spellcheck="false" />
          </label>
          <label class="oac-field">
            <span class="oac-field-label">body (JSON, 可空)</span>
            <textarea v-model="testForm.body" class="oac-textarea" rows="4" spellcheck="false" />
          </label>
          <label class="oac-field">
            <span class="oac-field-label">headers (JSON)</span>
            <textarea v-model="testForm.headers" class="oac-textarea" rows="2" spellcheck="false" />
          </label>
          <div class="oac-actions">
            <button type="button" class="oac-btn oac-btn--primary" :disabled="state.testing" @click="handleTest">
              {{ state.testing ? '调用中…' : '发起调用' }}
            </button>
            <span v-if="testForm.error" class="oac-error">{{ testForm.error }}</span>
          </div>
          <pre v-if="testResult" class="oac-preview" :class="{ 'oac-preview--error': testResult.ok === false }">{{ formatTestResult(testResult) }}</pre>

          <h4 class="oac-publish-title">发布到工作流</h4>
          <div class="oac-publish-row">
            <label class="oac-field">
              <span class="oac-field-label">workflow_id</span>
              <input v-model.number="publishForm.workflow_id" class="oac-input" type="number" min="1" />
            </label>
            <label class="oac-field">
              <span class="oac-field-label">节点名称</span>
              <input v-model="publishForm.name" class="oac-input" placeholder="留空使用默认" />
            </label>
          </div>
          <div class="oac-actions">
            <button type="button" class="oac-btn oac-btn--primary" :disabled="state.publishing || !canPublish" @click="handlePublish">
              {{ state.publishing ? '发布中…' : '发布为 openapi_operation 节点' }}
            </button>
            <span v-if="publishMessage" class="oac-success">{{ publishMessage }}</span>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
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
} from '../../application/openApiConnectorsApi'

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

const canImport = computed(() => importForm.name.trim().length > 0 && (importForm.spec_text.trim().length > 0 || importForm.spec_url.trim().length > 0))
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
</script>

<style scoped>
.oac-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  color: rgba(230, 240, 255, 0.92);
  min-height: 0;
}

.oac-toolbar {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.oac-title {
  margin: 0;
  font-size: 1.1rem;
}

.oac-tip {
  margin: 0;
  color: rgba(180, 200, 220, 0.65);
  font-size: 0.85rem;
}

.oac-section-title {
  font-size: 0.95rem;
  margin: 0 0 0.4rem;
}

.oac-import-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}

.oac-field {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.oac-field--span {
  grid-column: span 2;
}

.oac-field-label {
  font-size: 0.78rem;
  color: rgba(180, 200, 220, 0.7);
}

.oac-input,
.oac-textarea,
select.oac-input {
  background: rgba(10, 14, 22, 0.85);
  color: inherit;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  padding: 0.4rem 0.55rem;
  font-size: 0.85rem;
  font-family: inherit;
}

.oac-textarea {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 0.8rem;
}

.oac-actions {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.5rem;
  flex-wrap: wrap;
}

.oac-btn {
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.04);
  color: inherit;
  padding: 0.4rem 0.85rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
}

.oac-btn--primary {
  background: linear-gradient(180deg, #2ba8ff, #0f7be8);
  border-color: #1f8ce0;
  color: #fff;
}

.oac-btn--primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.oac-btn--ghost {
  background: transparent;
}

.oac-btn--danger {
  background: rgba(255, 80, 80, 0.12);
  border-color: rgba(255, 80, 80, 0.4);
  color: #ffb3b3;
}

.oac-cards {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.6rem;
}

.oac-card {
  background: rgba(8, 10, 16, 0.82);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 0.6rem;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.oac-card--selected {
  border-color: #2ba8ff;
  box-shadow: 0 0 0 1px rgba(43, 168, 255, 0.3) inset;
}

.oac-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}

.oac-card-status {
  font-size: 0.7rem;
  padding: 0 0.4rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
}

.oac-card-meta {
  display: flex;
  gap: 0.6rem;
  font-size: 0.78rem;
  color: rgba(180, 200, 220, 0.65);
}

.oac-card-base {
  font-size: 0.75rem;
  color: rgba(180, 200, 220, 0.5);
  word-break: break-all;
}

.oac-detail-head {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.6rem;
}

.oac-detail-head .oac-section-title {
  flex: 1 1 auto;
}

.oac-detail-grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
}

@media (max-width: 1100px) {
  .oac-detail-grid {
    grid-template-columns: 1fr;
  }
  .oac-import-grid {
    grid-template-columns: 1fr;
  }
  .oac-field--span {
    grid-column: span 1;
  }
}

.oac-credential,
.oac-operations,
.oac-test {
  background: rgba(8, 10, 16, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.oac-test {
  grid-column: 1 / -1;
}

.oac-op-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  max-height: 320px;
  overflow: auto;
}

.oac-op {
  display: grid;
  grid-template-columns: 60px 1fr auto auto;
  align-items: center;
  gap: 0.5rem;
  background: rgba(255, 255, 255, 0.02);
  padding: 0.35rem 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}

.oac-op--active {
  border-color: rgba(43, 168, 255, 0.6);
  background: rgba(43, 168, 255, 0.08);
}

.oac-op-method {
  font-size: 0.7rem;
  font-weight: 600;
  text-align: center;
  border-radius: 4px;
  padding: 0.1rem 0.3rem;
  background: rgba(255, 255, 255, 0.08);
}

.oac-op-method[data-method='GET'] {
  background: rgba(60, 200, 120, 0.15);
  color: #6cf;
}

.oac-op-method[data-method='POST'] {
  background: rgba(43, 168, 255, 0.18);
}

.oac-op-method[data-method='DELETE'] {
  background: rgba(255, 100, 100, 0.18);
  color: #fbb;
}

.oac-op-method[data-method='PUT'],
.oac-op-method[data-method='PATCH'] {
  background: rgba(255, 200, 50, 0.18);
  color: #ffd66e;
}

.oac-op-path {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.85);
}

.oac-op-id {
  font-size: 0.72rem;
  color: rgba(180, 200, 220, 0.65);
}

.oac-op-toggle {
  font-size: 0.72rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.oac-preview {
  background: rgba(0, 0, 0, 0.45);
  border-radius: 6px;
  padding: 0.5rem;
  font-size: 0.75rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
}

.oac-preview--error {
  border: 1px solid rgba(255, 80, 80, 0.4);
}

.oac-publish-title {
  margin-top: 0.6rem;
  font-size: 0.85rem;
}

.oac-publish-row {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 0.6rem;
}

.oac-error {
  color: #ff8c8c;
  font-size: 0.8rem;
}

.oac-success {
  color: #95e8a4;
  font-size: 0.8rem;
}
</style>
