<template>
  <div class="admin-cs">
    <header class="admin-cs__header">
      <div>
        <p>AI 客服后台</p>
        <h1>审核标准与外部 API 对接</h1>
      </div>
      <button class="btn" @click="loadAll">刷新</button>
    </header>

    <p v-if="message" class="notice">{{ message }}</p>

    <section class="panel">
      <h2>新增/编辑审核标准</h2>
      <div class="form-grid">
        <label>名称<input v-model="standardForm.name" /></label>
        <label>场景<input v-model="standardForm.scenario" placeholder="refund / catalog_complaint / catalog_review" /></label>
        <label>风险等级<input v-model="standardForm.risk_level" /></label>
        <label>优先级<input v-model.number="standardForm.priority" type="number" /></label>
      </div>
      <label>说明<textarea v-model="standardForm.description" /></label>
      <label>规则 JSON<textarea v-model="standardRulesText" /></label>
      <label>动作策略 JSON<textarea v-model="standardPolicyText" /></label>
      <div class="row">
        <label class="check"><input v-model="standardForm.auto_enabled" type="checkbox" /> 启用自动化</label>
        <button class="btn" @click="saveStandard">{{ editingStandardId ? '保存标准' : '创建标准' }}</button>
        <button class="btn ghost" @click="resetStandard">清空</button>
      </div>
    </section>

    <section class="panel">
      <h2>审核标准列表</h2>
      <div v-for="item in standards" :key="item.id" class="list-row">
        <div>
          <b>{{ item.name }}</b>
          <span>{{ item.scenario }} · {{ item.risk_level }} · 优先级 {{ item.priority }}</span>
        </div>
        <button class="btn ghost" @click="editStandard(item)">编辑</button>
      </div>
    </section>

    <section class="panel">
      <h2>新增/编辑对接能力</h2>
      <div class="form-grid">
        <label>名称<input v-model="integrationForm.name" /></label>
        <label>类型
          <select v-model="integrationForm.integration_type">
            <option value="openapi">OpenAPI 网页 API</option>
            <option value="workflow">平台工作流</option>
          </select>
        </label>
        <label>场景<input v-model="integrationForm.scenario" /></label>
        <label>连接器 ID<input v-model.number="integrationForm.connector_id" type="number" /></label>
        <label>工作流 ID<input v-model.number="integrationForm.workflow_id" type="number" /></label>
      </div>
      <label>配置 JSON<textarea v-model="integrationConfigText" placeholder='{"operation_id":"createTicket","auto_invoke":true}' /></label>
      <div class="row">
        <label class="check"><input v-model="integrationForm.enabled" type="checkbox" /> 启用</label>
        <button class="btn" @click="saveIntegration">{{ editingIntegrationId ? '保存对接' : '创建对接' }}</button>
        <button class="btn ghost" @click="resetIntegration">清空</button>
      </div>
    </section>

    <section class="panel">
      <h2>对接列表</h2>
      <div v-for="item in integrations" :key="item.id" class="list-row">
        <div>
          <b>{{ item.name }}</b>
          <span>{{ item.integration_type }} · {{ item.scenario }} · {{ item.enabled ? '启用' : '停用' }}</span>
        </div>
        <button class="btn ghost" @click="editIntegration(item)">编辑</button>
      </div>
      <p v-if="integrations.length === 0" class="muted">暂无对接配置</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const standards = ref<any[]>([])
const integrations = ref<any[]>([])
const message = ref('')
const editingStandardId = ref<number | null>(null)
const editingIntegrationId = ref<number | null>(null)
const standardRulesText = ref('{}')
const standardPolicyText = ref('{}')
const integrationConfigText = ref('{"auto_invoke":true}')

const standardForm = reactive({
  name: '',
  scenario: 'general',
  description: '',
  risk_level: 'low',
  priority: 100,
  auto_enabled: true,
})

const integrationForm = reactive({
  name: '',
  integration_type: 'openapi',
  connector_id: null as number | null,
  workflow_id: null as number | null,
  scenario: 'general',
  enabled: true,
})

onMounted(loadAll)

async function loadAll() {
  const [s, i] = await Promise.all([
    api.customerServiceStandards().catch(() => ({ items: [] })),
    api.customerServiceIntegrations().catch(() => ({ items: [] })),
  ])
  standards.value = Array.isArray((s as any)?.items) ? (s as any).items : []
  integrations.value = Array.isArray((i as any)?.items) ? (i as any).items : []
}

async function saveStandard() {
  try {
    const payload = {
      ...standardForm,
      rules: JSON.parse(standardRulesText.value || '{}'),
      action_policy: JSON.parse(standardPolicyText.value || '{}'),
    }
    if (editingStandardId.value) await api.customerServiceUpdateStandard(editingStandardId.value, payload)
    else await api.customerServiceCreateStandard(payload)
    message.value = '审核标准已保存'
    resetStandard()
    await loadAll()
  } catch (e: any) {
    message.value = e?.message || '保存审核标准失败'
  }
}

function editStandard(item: any) {
  editingStandardId.value = item.id
  standardForm.name = item.name || ''
  standardForm.scenario = item.scenario || 'general'
  standardForm.description = item.description || ''
  standardForm.risk_level = item.risk_level || 'low'
  standardForm.priority = Number(item.priority || 100)
  standardForm.auto_enabled = Boolean(item.auto_enabled)
  standardRulesText.value = JSON.stringify(item.rules || {}, null, 2)
  standardPolicyText.value = JSON.stringify(item.action_policy || {}, null, 2)
}

function resetStandard() {
  editingStandardId.value = null
  standardForm.name = ''
  standardForm.scenario = 'general'
  standardForm.description = ''
  standardForm.risk_level = 'low'
  standardForm.priority = 100
  standardForm.auto_enabled = true
  standardRulesText.value = '{}'
  standardPolicyText.value = '{}'
}

async function saveIntegration() {
  try {
    const payload = {
      ...integrationForm,
      connector_id: integrationForm.connector_id || null,
      workflow_id: integrationForm.workflow_id || null,
      config: JSON.parse(integrationConfigText.value || '{}'),
    }
    if (editingIntegrationId.value) await api.customerServiceUpdateIntegration(editingIntegrationId.value, payload)
    else await api.customerServiceCreateIntegration(payload)
    message.value = '对接配置已保存'
    resetIntegration()
    await loadAll()
  } catch (e: any) {
    message.value = e?.message || '保存对接配置失败'
  }
}

function editIntegration(item: any) {
  editingIntegrationId.value = item.id
  integrationForm.name = item.name || ''
  integrationForm.integration_type = item.integration_type || 'openapi'
  integrationForm.connector_id = item.connector_id || null
  integrationForm.workflow_id = item.workflow_id || null
  integrationForm.scenario = item.scenario || 'general'
  integrationForm.enabled = Boolean(item.enabled)
  integrationConfigText.value = JSON.stringify(item.config || {}, null, 2)
}

function resetIntegration() {
  editingIntegrationId.value = null
  integrationForm.name = ''
  integrationForm.integration_type = 'openapi'
  integrationForm.connector_id = null
  integrationForm.workflow_id = null
  integrationForm.scenario = 'general'
  integrationForm.enabled = true
  integrationConfigText.value = '{"auto_invoke":true}'
}
</script>

<style scoped>
.admin-cs {
  min-height: calc(100vh - var(--nav-h, 64px));
  padding: 32px;
  color: #fff;
  background: #0a0c12;
}

.admin-cs__header,
.row,
.list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.admin-cs__header {
  max-width: 1180px;
  margin: 0 auto 20px;
}

.admin-cs__header p {
  color: #f6c86d;
  font-weight: 800;
}

.panel {
  max-width: 1180px;
  margin: 16px auto;
  padding: 20px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.06);
  border-radius: 22px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
}

label {
  display: grid;
  gap: 6px;
  margin-top: 12px;
  color: rgba(255, 255, 255, 0.72);
}

input,
select,
textarea {
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.25);
  color: #fff;
  padding: 10px;
}

textarea {
  min-height: 96px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.check {
  display: flex;
  grid-template-columns: none;
  flex-direction: row;
  align-items: center;
}

.btn {
  border: 0;
  border-radius: 999px;
  padding: 10px 16px;
  background: #f6c86d;
  color: #17130a;
  font-weight: 800;
  cursor: pointer;
}

.btn.ghost {
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.list-row {
  padding: 12px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.list-row div {
  display: grid;
  gap: 4px;
}

.list-row span,
.muted {
  color: rgba(255, 255, 255, 0.62);
}

.notice {
  max-width: 1180px;
  margin: 0 auto;
  color: #d7fbe8;
}

html[data-workbench-theme='light'] .admin-cs{background:#f8f9fa;color:#1a1a1a}
html[data-workbench-theme='light'] .admin-cs__header p{color:#d97706}
html[data-workbench-theme='light'] .panel{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] label{color:rgba(0,0,0,0.65)}
html[data-workbench-theme='light'] input,html[data-workbench-theme='light'] select,html[data-workbench-theme='light'] textarea{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .btn{background:#d97706;color:#fff}
html[data-workbench-theme='light'] .btn.ghost{background:rgba(0,0,0,0.04);color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .list-row{border-top-color:rgba(0,0,0,0.06)}
html[data-workbench-theme='light'] .list-row span,html[data-workbench-theme='light'] .muted{color:#64748b}
html[data-workbench-theme='light'] .notice{color:#059669}
</style>
