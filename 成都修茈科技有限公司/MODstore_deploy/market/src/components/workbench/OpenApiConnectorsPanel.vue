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
          <input v-model="importForm.name" class="oac-input" placeholder="例如：jira-cloud" maxlength="128" spellcheck="false" />
        </label>
        <label class="oac-field">
          <span class="oac-field-label">备注</span>
          <input v-model="importForm.description" class="oac-input" placeholder="可选：用途描述" maxlength="200" />
        </label>
        <label class="oac-field oac-field--span">
          <span class="oac-field-label">Spec URL（可选，与下方文本二选一）</span>
          <input v-model="importForm.spec_url" class="oac-input" placeholder="https://example.com/openapi.json" spellcheck="false" />
        </label>
        <label class="oac-field oac-field--span">
          <span class="oac-field-label">覆盖 base_url（可选）</span>
          <input v-model="importForm.base_url_override" class="oac-input" placeholder="留空则使用 spec.servers[0].url" spellcheck="false" />
        </label>
        <label class="oac-field oac-field--span oac-field--full">
          <span class="oac-field-label">或直接粘贴 OpenAPI 文档（JSON / YAML）</span>
          <textarea
            v-model="importForm.spec_text"
            class="oac-textarea"
            rows="8"
            placeholder='{\n  \"openapi\": \"3.0.3\", ...\n}'
            spellcheck="false"
          />
        </label>
      </div>
      <div class="oac-actions">
        <button type="button" class="oac-btn oac-btn--primary" :disabled="state.importing || !canImport" @click="handleImport">
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
        <button type="button" class="oac-btn oac-btn--ghost" @click="loadDetail(detail.connector.id)">刷新</button>
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
              <span class="oac-op-method" :class="`oac-op-method--${op.method.toLowerCase()}`">{{ op.method }}</span>
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
          <pre v-if="testResult" class="oac-preview" :class="{ 'oac-preview--error': testResult.ok === false }">{{
            formatTestResult(testResult)
          }}</pre>

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
// 拆分后本文件为组装入口（façade）：连接器全部交互逻辑在 ./open-api-connectors/，样式在 ./open-api-connectors/openApiConnectors.css。
import { useOpenApiConnectors } from './open-api-connectors/useOpenApiConnectors'

/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const {
  connectors, detail, selectedId, activeOperationId, testResult, publishMessage,
  state, importForm, credentialForm, testForm, publishForm,
  canImport, canPublish, activeOperation, hasCredentialPreview,
  refreshList, loadDetail, selectConnector, formatPreview, formatTestResult,
  buildCredentialConfig, safeJsonParse,
  handleImport, handleDelete, handleSaveCredential, handleClearCredential,
  handleToggle, handleTest, handlePublish,
} = useOpenApiConnectors()
/* eslint-enable @typescript-eslint/no-unused-vars */
</script>

<style scoped src="./open-api-connectors/openApiConnectors.css"></style>
