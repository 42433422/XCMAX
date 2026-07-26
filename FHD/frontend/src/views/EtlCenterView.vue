<template>
  <main id="view-business-docking" class="etl-center">
    <header class="etl-hero">
      <div>
        <span class="etl-eyebrow">企业版 · 通用 ETL</span>
        <h1>数据对接中心</h1>
        <p>文件先预演、再确认。AI 只给建议，最终写入由确定性规则和你的确认控制。</p>
      </div>
      <div class="etl-hero__limits">
        <span>单文件 50MB</span>
        <span>最多 10 万行</span>
        <span>模板仅自己可见</span>
      </div>
    </header>

    <div v-if="pageError" class="etl-alert etl-alert--error" role="alert">
      <strong>{{ pageError }}</strong>
      <button type="button" @click="bootstrap">重试</button>
    </div>

    <nav class="etl-tabs" aria-label="数据对接工作区">
      <button
        v-for="item in tabs"
        :key="item.id"
        type="button"
        :class="{ active: activeTab === item.id }"
        @click="activeTab = item.id"
      >
        <span>{{ item.step }}</span>
        {{ item.label }}
      </button>
    </nav>

    <section v-if="activeTab === 'upload'" class="etl-panel">
      <div class="etl-panel__title">
        <div>
          <h2>上传与目标</h2>
          <p>每个任务只绑定一个目标；需要多目标时复制为多个运行。</p>
        </div>
      </div>
      <div class="etl-upload-grid">
        <label class="etl-dropzone" :class="{ busy: busy }">
          <input
            type="file"
            accept=".xlsx,.xlsm,.csv,.pdf,.jpg,.jpeg,.png,.doc,.docx,.ppt,.pptx"
            :disabled="busy"
            @change="onFileChange"
          >
          <i class="fa fa-cloud-upload" aria-hidden="true"></i>
          <strong>{{ selectedFile?.name || '选择办公文件或扫描单据' }}</strong>
          <span>XLSX / XLSM / CSV · PDF / JPG / PNG OCR · Word / PPT 仅知识库</span>
        </label>

        <div class="etl-form-card">
          <label>
            目标
            <select v-model="targetType" :disabled="busy">
              <option v-for="target in capabilities?.targets || []" :key="target.type" :value="target.type">
                {{ target.label }}{{ target.reversible ? ' · 可撤销' : ' · 不可撤销' }}
              </option>
            </select>
          </label>
          <label>
            个人模板
            <select v-model="templateId" :disabled="busy">
              <option value="">新建任务（自动建议映射）</option>
              <option
                v-for="template in compatibleTemplates"
                :key="template.id"
                :value="template.id"
              >
                {{ template.name }} · v{{ template.current_version }}
              </option>
            </select>
          </label>
          <label v-if="targetType === 'webhook'">
            Webhook 配置
            <select v-model="targetConfigId">
              <option value="">请选择配置</option>
              <option v-for="config in targetConfigs" :key="config.id" :value="config.id">
                {{ config.name }}
              </option>
            </select>
          </label>
          <button
            v-if="targetType === 'webhook' && targetConfigId"
            type="button"
            class="etl-link-button"
            :disabled="busy"
            @click="testWebhook"
          >
            测试当前 Webhook
          </button>
          <small v-if="webhookTestMessage" class="etl-webhook-test">{{ webhookTestMessage }}</small>
          <button
            v-if="targetType === 'webhook'"
            type="button"
            class="etl-link-button"
            @click="showWebhookForm = !showWebhookForm"
          >
            {{ showWebhookForm ? '收起配置' : '新建 Webhook 配置' }}
          </button>
          <button
            type="button"
            class="etl-primary"
            :disabled="!selectedFile || busy || (targetType === 'webhook' && !targetConfigId)"
            @click="startPreview"
          >
            {{ busy ? '正在创建后台预演…' : '上传并开始预演' }}
          </button>
        </div>
      </div>
      <p v-if="capabilities?.compatibility_presets?.length" class="etl-compat-note">
        已加载 {{ capabilities.compatibility_presets.length }} 个旧 YAML/知识库兼容预设；
        预演确认后请保存为仅自己可见的个人模板。
      </p>

      <form v-if="showWebhookForm" class="etl-webhook-form" @submit.prevent="saveWebhook">
        <label>名称<input v-model.trim="webhookDraft.name" required maxlength="160"></label>
        <label>HTTPS 地址<input v-model.trim="webhookDraft.endpoint_url" required type="url"></label>
        <label>
          普通请求头 JSON
          <textarea v-model="webhookDraft.headersJson" rows="2" placeholder="{&quot;X-System&quot;:&quot;FHD&quot;}"></textarea>
        </label>
        <label>Bearer 密钥<input v-model="webhookDraft.secret" type="password" autocomplete="new-password"></label>
        <button class="etl-secondary" type="submit" :disabled="busy">保存到系统凭据管理器</button>
      </form>

      <div v-if="currentRun && ['queued', 'previewing'].includes(currentRun.status)" class="etl-progress-card">
        <div>
          <strong>{{ stageLabel(currentRun.stage) }}</strong>
          <span>{{ currentRun.progress }}%</span>
        </div>
        <progress :value="currentRun.progress" max="100"></progress>
        <p>后台分块处理中，可以留在本页查看进度。</p>
      </div>
    </section>

    <section v-else-if="activeTab === 'mapping'" class="etl-panel">
      <div class="etl-panel__title">
        <div>
          <h2>字段映射</h2>
          <p>确认源字段、目标字段与安全转换。转换规则只接受受限 JSON DSL。</p>
        </div>
        <button type="button" class="etl-secondary" :disabled="!editableMappings.length || busy" @click="saveMappings">
          保存并重新校验
        </button>
      </div>
      <div v-if="!currentRun" class="etl-empty">请先在“上传文件”中创建预演。</div>
      <div v-else class="etl-mapping-table-wrap">
        <table class="etl-table etl-mapping-table">
          <thead>
            <tr><th>源字段</th><th>样例</th><th>目标字段</th><th>转换</th><th>置信度</th><th>必填</th></tr>
          </thead>
          <tbody>
            <tr v-for="(mapping, mappingIndex) in editableMappings" :key="`${mappingIndex}-${mapping.target}`">
              <td>
                <input v-model="mapping.source" :placeholder="mapping.required ? '请选择源字段' : '可留空'">
              </td>
              <td><small>{{ mappingSample(mapping.source) }}</small></td>
              <td>
                <input
                  v-if="currentCapability?.allow_dynamic_fields"
                  v-model.trim="mapping.target"
                  aria-label="输出字段名"
                  maxlength="160"
                >
                <template v-else>
                  <strong>{{ targetField(mapping.target)?.label || mapping.target }}</strong>
                  <small>{{ mapping.target }}</small>
                </template>
              </td>
              <td>
                <select v-model="mappingUiTransform[String(mappingIndex)]" @change="applyCommonTransform(String(mappingIndex))">
                  <option value="">无</option>
                  <option value="trim">去空格</option>
                  <option value="number">数字标准化</option>
                  <option value="date">日期标准化</option>
                  <option value="custom">高级 JSON</option>
                </select>
                <textarea
                  v-model="mappingUiTransformJson[String(mappingIndex)]"
                  rows="2"
                  spellcheck="false"
                  aria-label="安全转换 JSON"
                  placeholder="[]"
                ></textarea>
              </td>
              <td>
                <span :class="confidenceClass(mapping.confidence)">
                  {{ Math.round((mapping.confidence || 0) * 100) }}%
                </span>
              </td>
              <td>{{ mapping.required ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="hasOcrRows" class="etl-ocr-confirm">
          <label>
            <input v-model="ocrConfirmed" type="checkbox">
            我已对照原图复核 OCR 表格位置和原文片段
          </label>
          <span>未确认前，OCR 行会保持错误状态并阻止写入。</span>
        </div>
        <fieldset v-if="updatableFields.length" class="etl-update-fields">
          <legend>允许更新的字段（默认全部不更新）</legend>
          <label v-for="field in updatableFields" :key="field.key">
            <input v-model="allowedUpdateFields" type="checkbox" :value="field.key">
            {{ field.label }}
          </label>
        </fieldset>
        <fieldset v-if="currentRun.draft.match_keys?.length" class="etl-update-fields">
          <legend>确定性匹配键</legend>
          <span v-for="key in currentRun.draft.match_keys" :key="key" class="etl-match-key">{{ key }}</span>
        </fieldset>
      </div>
    </section>

    <section v-else-if="activeTab === 'preview'" class="etl-panel" data-tutorial-anchor="business-dock-results">
      <div class="etl-panel__title">
        <div>
          <h2>预演与确认</h2>
          <p>重复数据默认跳过；更新只会使用模板中明确允许的字段。</p>
        </div>
        <div class="etl-actions">
          <button type="button" class="etl-secondary" :disabled="!currentRun || busy" @click="saveCurrentAsTemplate">
            保存个人模板
          </button>
          <button
            type="button"
            class="etl-primary"
            :disabled="!canExecute || busy"
            @click="executeCurrentRun"
          >
            确认执行
          </button>
        </div>
      </div>
      <div v-if="!currentRun" class="etl-empty">暂无预演任务。</div>
      <template v-else>
        <div class="etl-summary-grid">
          <button v-for="item in summaryCards" :key="item.action" type="button" @click="rowActionFilter = item.action">
            <span :class="`etl-dot etl-dot--${item.action}`"></span>
            <strong>{{ item.count }}</strong>
            <small>{{ item.label }}</small>
          </button>
        </div>
        <div v-if="currentRun.summary.error" class="etl-alert etl-alert--warning">
          <div>
            <strong>存在 {{ currentRun.summary.error }} 行错误，默认阻断整批</strong>
            <span>修正映射后重新校验，或明确选择仅写入正确行。</span>
          </div>
          <label>
            <input v-model="validRowsOnly" type="checkbox">
            仅写入正确行
          </label>
        </div>
        <div v-if="currentRun.error" class="etl-alert etl-alert--error">
          {{ currentRun.error.message }}（{{ currentRun.error.code }}）
        </div>
        <div class="etl-table-toolbar">
          <div class="etl-bulk-actions">
            <select v-model="rowActionFilter" @change="loadRows">
              <option value="">全部动作</option>
              <option value="new">新增</option>
              <option value="update">更新</option>
              <option value="skip">跳过</option>
              <option value="error">错误</option>
            </select>
            <button type="button" :disabled="busy || !runRows.length" @click="bulkOverride('skip')">本页全部跳过</button>
            <button type="button" :disabled="busy || !bulkNewRows.length" @click="bulkOverride('new')">本页可新增行设为新增</button>
          </div>
          <a
            v-if="currentRun.summary.error"
            :href="etlApi.errorExportUrl(currentRun.id)"
            target="_blank"
            rel="noopener"
          >导出错误行</a>
        </div>
        <div class="etl-table-wrap">
          <table class="etl-table">
            <thead>
              <tr><th>来源</th><th>标准化结果</th><th>最终动作</th><th>AI 建议</th><th>问题 / 差异</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="row in runRows"
                :key="row.id"
                :class="{
                  'etl-row-error': row.final_action === 'error',
                  'etl-row-ocr-low': Array.isArray(row.provenance.low_confidence_fields) && row.provenance.low_confidence_fields.length > 0,
                }"
              >
                <td>
                  <strong>{{ row.source_sheet }} · {{ row.source_row }}</strong>
                  <small>{{ compactRecord(row.source) }}</small>
                  <details v-if="row.provenance.ocr === true" class="etl-ocr-evidence">
                    <summary>
                      OCR 第 {{ row.provenance.page || 1 }} 页 · 表格行 {{ ocrTableRow(row) }}
                    </summary>
                    <pre>{{ JSON.stringify(row.provenance.cells || row.provenance.original_fragment || {}, null, 2) }}</pre>
                  </details>
                  <small
                    v-if="Array.isArray(row.provenance.low_confidence_fields) && row.provenance.low_confidence_fields.length"
                    class="etl-ocr-low-note"
                  >
                    OCR 低置信：{{ row.provenance.low_confidence_fields.join('、') }}
                  </small>
                </td>
                <td><small>{{ compactRecord(row.normalized) }}</small></td>
                <td>
                  <select
                    :value="row.final_action"
                    :disabled="row.validation_issues.length > 0 || busy"
                    @change="overrideRow(row, $event)"
                  >
                    <option v-for="action in allowedActionsForRow(row)" :key="action" :value="action">
                      {{ actionLabel(action) }}
                    </option>
                    <option v-if="row.final_action === 'error'" value="error">错误</option>
                  </select>
                </td>
                <td>
                  <span>{{ actionLabel(row.llm_suggestion.action || row.suggested_action) }}</span>
                  <small>{{ row.llm_suggestion.reason || '确定性规则建议' }} · 仅供参考</small>
                </td>
                <td>
                  <ul v-if="row.validation_issues.length" class="etl-issues">
                    <li v-for="issue in row.validation_issues" :key="`${row.id}-${issue.code}`">
                      {{ issue.message }}
                    </li>
                  </ul>
                  <details v-else-if="row.final_action === 'update'">
                    <summary>查看前后差异</summary>
                    <pre>{{ diffText(row) }}</pre>
                  </details>
                  <span v-else>{{ actionReason(row.final_action) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="etl-pagination">
          <button type="button" :disabled="rowPage <= 1" @click="rowPage--; loadRows()">上一页</button>
          <span>第 {{ rowPage }} 页 · 共 {{ rowTotal }} 行</span>
          <button type="button" :disabled="rowPage * 50 >= rowTotal" @click="rowPage++; loadRows()">下一页</button>
        </div>
      </template>
    </section>

    <section v-else class="etl-panel">
      <div class="etl-panel__title">
        <div>
          <h2>运行历史</h2>
          <p>查看进度、回执、重试和撤销。外部导出与 Webhook 明确不可撤销。</p>
        </div>
        <button type="button" class="etl-secondary" @click="refreshRuns">刷新</button>
      </div>
      <div v-if="!runs.length" class="etl-empty">暂无运行记录。</div>
      <div v-else class="etl-history">
        <button
          v-for="run in runs"
          :key="run.id"
          type="button"
          class="etl-history__item"
          :class="{ active: currentRun?.id === run.id }"
          @click="selectRun(run)"
        >
          <div>
            <strong>{{ targetLabel(run.target_type) }}</strong>
            <span>{{ run.id.slice(0, 8) }} · {{ formatTime(run.created_at) }}</span>
          </div>
          <div>
            <span :class="`etl-status etl-status--${run.status}`">{{ statusLabel(run.status) }}</span>
            <small>{{ run.summary.executed }}/{{ run.total_rows }} · {{ run.progress }}%</small>
          </div>
        </button>
      </div>
      <article v-if="currentRun" class="etl-receipt">
        <header>
          <div>
            <h3>运行回执</h3>
            <p>{{ currentRun.id }}</p>
          </div>
          <div class="etl-actions">
            <a
              v-if="['export_xlsx', 'export_csv'].includes(currentRun.target_type) && currentRun.status === 'completed'"
              :href="etlApi.exportUrl(currentRun.id)"
              target="_blank"
              rel="noopener"
              class="etl-secondary"
            >下载导出</a>
            <button
              v-if="['failed', 'interrupted'].includes(currentRun.status)"
              type="button"
              class="etl-secondary"
              :disabled="busy"
              @click="retryRun"
            >重新预演</button>
            <button
              v-if="['completed', 'failed', 'interrupted'].includes(currentRun.status) && currentRun.summary.executed > 0 && currentRun.reversible && currentRun.rollback_status !== 'completed'"
              type="button"
              class="etl-danger"
              :disabled="busy"
              @click="rollbackRun"
            >撤销本次写入</button>
          </div>
        </header>
        <dl>
          <div><dt>状态</dt><dd>{{ statusLabel(currentRun.status) }}</dd></div>
          <div><dt>目标</dt><dd>{{ targetLabel(currentRun.target_type) }}</dd></div>
          <div><dt>已执行</dt><dd>{{ currentRun.summary.executed }} 行</dd></div>
          <div><dt>进度</dt><dd>{{ currentRun.progress }}%</dd></div>
          <div><dt>撤销能力</dt><dd>{{ currentRun.reversible ? '内部目标可撤销' : '外部目标不可撤销' }}</dd></div>
        </dl>
        <pre>{{ JSON.stringify(currentRun.receipt, null, 2) }}</pre>
      </article>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  etlApi,
  type EtlAction,
  type EtlCapabilities,
  type EtlFieldMapping,
  type EtlRun,
  type EtlRunRow,
  type EtlTargetConfig,
  type EtlTemplate,
} from '@/api/etl'

type TabId = 'upload' | 'mapping' | 'preview' | 'history'

const route = useRoute()
const router = useRouter()
const tabs: Array<{ id: TabId; step: string; label: string }> = [
  { id: 'upload', step: '1', label: '上传文件' },
  { id: 'mapping', step: '2', label: '字段映射' },
  { id: 'preview', step: '3', label: '预演确认' },
  { id: 'history', step: '4', label: '运行历史' },
]

const activeTab = ref<TabId>('upload')
const capabilities = ref<EtlCapabilities | null>(null)
const templates = ref<EtlTemplate[]>([])
const targetConfigs = ref<EtlTargetConfig[]>([])
const runs = ref<EtlRun[]>([])
const currentRun = ref<EtlRun | null>(null)
const selectedFile = ref<File | null>(null)
const targetType = ref('customers')
const templateId = ref('')
const targetConfigId = ref('')
const runRows = ref<EtlRunRow[]>([])
const rowPage = ref(1)
const rowTotal = ref(0)
const rowActionFilter = ref('')
const busy = ref(false)
const pageError = ref('')
const validRowsOnly = ref(false)
const editableMappings = ref<EtlFieldMapping[]>([])
const mappingUiTransform = reactive<Record<string, string>>({})
const mappingUiTransformJson = reactive<Record<string, string>>({})
const allowedUpdateFields = ref<string[]>([])
const ocrConfirmed = ref(false)
const hasOcrRows = ref(false)
const showWebhookForm = ref(false)
const webhookDraft = reactive({ name: '', endpoint_url: '', headersJson: '{}', secret: '' })
const webhookTestMessage = ref('')
let pollTimer: ReturnType<typeof setTimeout> | null = null

const compatibleTemplates = computed(() => templates.value.filter((item) => item.target_type === targetType.value))
const currentCapability = computed(() => capabilities.value?.targets.find((item) => item.type === currentRun.value?.target_type || targetType.value))
const updatableFields = computed(() => currentCapability.value?.fields.filter((field) => field.updatable) || [])
function allowedActionsForRow(row: EtlRunRow): EtlAction[] {
  const actions = currentCapability.value?.supported_actions || ['new', 'skip']
  return [...new Set([...actions, 'skip'])].filter((item): item is EtlAction => {
    if (item === 'error') return false
    if (item === 'update' && (!row.match_ref || allowedUpdateFields.value.length === 0)) return false
    if (item === 'new' && (row.match_ref || row.suggested_action === 'skip')) return false
    return true
  })
}
const bulkNewRows = computed(() => runRows.value.filter((row) => (
  row.validation_issues.length === 0
  && !row.match_ref
  && row.suggested_action !== 'skip'
)))
const canExecute = computed(() => {
  if (!currentRun.value || currentRun.value.status !== 'preview_ready') return false
  if (currentRun.value.summary.error && !validRowsOnly.value) return false
  return currentRun.value.summary.new + currentRun.value.summary.update > 0
})
const summaryCards = computed(() => [
  { action: 'new', label: '新增', count: currentRun.value?.summary.new || 0 },
  { action: 'update', label: '更新', count: currentRun.value?.summary.update || 0 },
  { action: 'skip', label: '跳过', count: currentRun.value?.summary.skip || 0 },
  { action: 'error', label: '错误', count: currentRun.value?.summary.error || 0 },
])

async function bootstrap() {
  busy.value = true
  pageError.value = ''
  try {
    const [caps, templateRows, history, configs] = await Promise.all([
      etlApi.capabilities(),
      etlApi.templates(),
      etlApi.runs(),
      etlApi.targetConfigs(),
    ])
    capabilities.value = caps
    templates.value = templateRows
    runs.value = history
    targetConfigs.value = configs
    if (!caps.targets.some((item) => item.type === targetType.value)) {
      targetType.value = caps.targets[0]?.type || 'customers'
    }
    const requestedRun = String(route.query.run_id || '')
    if (requestedRun) {
      currentRun.value = await etlApi.run(requestedRun)
      syncDraft()
      activeTab.value = ['queued', 'previewing'].includes(currentRun.value.status) ? 'upload' : 'preview'
      if (currentRun.value.status === 'preview_ready') await loadRows()
      schedulePoll()
    }
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '数据对接中心加载失败'
  } finally {
    busy.value = false
  }
}

function onFileChange(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null
  const suffix = selectedFile.value?.name.toLowerCase().split('.').pop() || ''
  if (['doc', 'docx', 'ppt', 'pptx'].includes(suffix)) targetType.value = 'knowledge'
}

async function startPreview() {
  if (!selectedFile.value) return
  busy.value = true
  pageError.value = ''
  try {
    const upload = await etlApi.upload(selectedFile.value)
    const run = await etlApi.preview({
      upload_id: upload.upload_id,
      target_type: targetType.value,
      template_id: templateId.value || undefined,
      target_config_id: targetConfigId.value || undefined,
    })
    currentRun.value = run
    syncDraft()
    runs.value = [run, ...runs.value.filter((item) => item.id !== run.id)]
    await router.replace({ path: '/business-docking', query: { run_id: run.id } })
    schedulePoll()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '创建预演失败'
  } finally {
    busy.value = false
  }
}

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer)
  if (!currentRun.value || !['queued', 'previewing', 'executing'].includes(currentRun.value.status)) return
  pollTimer = setTimeout(async () => {
    if (!currentRun.value) return
    try {
      currentRun.value = await etlApi.run(currentRun.value.id)
      syncDraft()
      if (currentRun.value.status === 'preview_ready') {
        activeTab.value = 'preview'
        await loadRows()
        await refreshRuns()
      }
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '读取运行进度失败'
    }
    schedulePoll()
  }, 1200)
}

function syncDraft() {
  if (!currentRun.value) return
  editableMappings.value = (currentRun.value.draft.field_mappings || []).map((item) => ({
    ...item,
    transforms: [...(item.transforms || [])],
  }))
  for (const [index, mapping] of editableMappings.value.entries()) {
    const firstOp = String(mapping.transforms?.[0]?.op || '')
    mappingUiTransform[String(index)] = ['', 'trim', 'number', 'date'].includes(firstOp) ? firstOp : 'custom'
    mappingUiTransformJson[String(index)] = JSON.stringify(mapping.transforms || [])
  }
  allowedUpdateFields.value = [...(currentRun.value.draft.allowed_update_fields || [])]
  ocrConfirmed.value = Boolean(currentRun.value.draft.ocr_confirmed)
}

async function saveMappings() {
  if (!currentRun.value) return
  busy.value = true
  try {
    const mappings = editableMappings.value.map((mapping, index) => {
      const parsed = JSON.parse(mappingUiTransformJson[String(index)] || '[]')
      if (!Array.isArray(parsed)) throw new Error(`${mapping.target} 的转换规则必须是 JSON 数组`)
      return { ...mapping, transforms: parsed }
    })
    currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
      field_mappings: mappings,
      allowed_update_fields: allowedUpdateFields.value,
      ocr_confirmed: ocrConfirmed.value,
    })
    syncDraft()
    activeTab.value = currentRun.value.status === 'previewing' ? 'upload' : 'preview'
    if (currentRun.value.status === 'preview_ready') await loadRows()
    schedulePoll()
    await refreshRuns()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '映射保存失败'
  } finally {
    busy.value = false
  }
}

async function loadRows() {
  if (!currentRun.value || currentRun.value.total_rows === 0) {
    runRows.value = []
    rowTotal.value = 0
    return
  }
  const result = await etlApi.rows(currentRun.value.id, rowPage.value, 50, rowActionFilter.value)
  runRows.value = result.items
  rowTotal.value = result.total
  hasOcrRows.value = result.items.some((row) => row.provenance.ocr === true)
}

async function overrideRow(row: EtlRunRow, event: Event) {
  if (!currentRun.value) return
  const action = (event.target as HTMLSelectElement).value
  busy.value = true
  try {
    currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
      row_overrides: { [String(row.id)]: action },
    })
    await loadRows()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '逐行动作保存失败'
  } finally {
    busy.value = false
  }
}

async function bulkOverride(action: 'new' | 'skip') {
  if (!currentRun.value) return
  const candidates = action === 'new'
    ? bulkNewRows.value
    : runRows.value.filter((row) => row.validation_issues.length === 0)
  if (!candidates.length) return
  busy.value = true
  try {
    currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
      row_overrides: Object.fromEntries(candidates.map((row) => [String(row.id), action])),
    })
    await loadRows()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '批量动作保存失败'
  } finally {
    busy.value = false
  }
}

async function executeCurrentRun() {
  if (!currentRun.value || !canExecute.value) return
  busy.value = true
  try {
    currentRun.value = await etlApi.execute(currentRun.value.id, validRowsOnly.value)
    activeTab.value = 'history'
    await refreshRuns()
    schedulePoll()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '执行失败'
    if (currentRun.value) currentRun.value = await etlApi.run(currentRun.value.id).catch(() => currentRun.value)
  } finally {
    busy.value = false
  }
}

async function saveCurrentAsTemplate() {
  if (!currentRun.value) return
  const name = window.prompt('模板名称', `${targetLabel(currentRun.value.target_type)}-${new Date().toLocaleDateString()}`)
  if (!name?.trim()) return
  busy.value = true
  try {
    await etlApi.createTemplate({
      name: name.trim(),
      target_type: currentRun.value.target_type,
      draft: currentRun.value.draft,
      source_features: currentRun.value.source_features,
    })
    templates.value = await etlApi.templates()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '模板保存失败'
  } finally {
    busy.value = false
  }
}

async function refreshRuns() {
  runs.value = await etlApi.runs()
  if (currentRun.value) {
    const latest = runs.value.find((item) => item.id === currentRun.value?.id)
    if (latest) currentRun.value = latest
  }
}

async function selectRun(run: EtlRun) {
  currentRun.value = await etlApi.run(run.id)
  syncDraft()
  await router.replace({ path: '/business-docking', query: { run_id: run.id } })
  schedulePoll()
}

async function retryRun() {
  if (!currentRun.value) return
  busy.value = true
  try {
    currentRun.value = await etlApi.retry(currentRun.value.id)
    activeTab.value = 'upload'
    schedulePoll()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '重试失败'
  } finally {
    busy.value = false
  }
}

async function rollbackRun() {
  if (!currentRun.value || !window.confirm('确认撤销本次内部写入？更新将恢复前镜像，新增记录将被删除。')) return
  busy.value = true
  try {
    currentRun.value = await etlApi.rollback(currentRun.value.id)
    await refreshRuns()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '撤销失败'
  } finally {
    busy.value = false
  }
}

async function saveWebhook() {
  busy.value = true
  try {
    const headers = JSON.parse(webhookDraft.headersJson || '{}')
    if (!headers || Array.isArray(headers) || typeof headers !== 'object') {
      throw new Error('普通请求头必须是 JSON 对象')
    }
    const config = await etlApi.createTargetConfig({
      name: webhookDraft.name,
      endpoint_url: webhookDraft.endpoint_url,
      headers,
      secret: webhookDraft.secret,
    })
    targetConfigs.value = await etlApi.targetConfigs()
    targetConfigId.value = config.id
    showWebhookForm.value = false
    webhookDraft.name = ''
    webhookDraft.endpoint_url = ''
    webhookDraft.headersJson = '{}'
    webhookDraft.secret = ''
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : 'Webhook 配置保存失败'
  } finally {
    busy.value = false
  }
}

async function testWebhook() {
  if (!targetConfigId.value) return
  busy.value = true
  webhookTestMessage.value = ''
  try {
    await etlApi.testTarget(targetConfigId.value)
    webhookTestMessage.value = '连接测试成功'
  } catch (error) {
    webhookTestMessage.value = error instanceof Error ? error.message : '连接测试失败'
  } finally {
    busy.value = false
  }
}

function targetField(key: string) {
  return currentCapability.value?.fields.find((field) => field.key === key)
}

function applyCommonTransform(target: string) {
  const op = mappingUiTransform[target]
  if (op === 'custom') return
  mappingUiTransformJson[target] = JSON.stringify(op ? [{ op }] : [])
}

function mappingSample(source: string): string {
  if (!source) return '—'
  const value = runRows.value.find((row) => row.source[source] != null)?.source[source]
  return value == null ? '—' : String(value).slice(0, 80)
}
function targetLabel(type: string) {
  return capabilities.value?.targets.find((item) => item.type === type)?.label || type
}
function actionLabel(action: string) {
  return ({ new: '新增', update: '更新', skip: '跳过', error: '错误' } as Record<string, string>)[action] || action
}
function actionReason(action: string) {
  return action === 'skip' ? '重复数据，默认不写入' : '无差异'
}
function stageLabel(stage: string) {
  return ({ queued: '等待后台任务', parsing: '解析文件', validating: '转换与校验', preview_ready: '预演完成', executing: '执行写入' } as Record<string, string>)[stage] || stage
}
function statusLabel(status: string) {
  return ({ queued: '排队中', previewing: '预演中', preview_ready: '待确认', executing: '执行中', completed: '已完成', failed: '失败', interrupted: '已中断' } as Record<string, string>)[status] || status
}
function confidenceClass(value: number) {
  return value >= 0.9 ? 'confidence-high' : value >= 0.6 ? 'confidence-medium' : 'confidence-low'
}
function compactRecord(value: Record<string, unknown>) {
  return Object.entries(value).slice(0, 5).map(([key, item]) => `${key}: ${String(item ?? '')}`).join(' · ')
}
function ocrTableRow(row: EtlRunRow) {
  const table = row.provenance.table_position
  return table && typeof table === 'object' && 'row' in table
    ? String((table as Record<string, unknown>).row || row.source_row)
    : String(row.source_row)
}
function diffText(row: EtlRunRow) {
  return JSON.stringify({ 更新前: row.before, 更新后: row.after }, null, 2)
}
function formatTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

onMounted(bootstrap)
onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<style scoped>
.etl-center { padding: 24px; color: #172033; min-height: 100%; background: #f5f7fb; }
.etl-hero { display: flex; justify-content: space-between; gap: 24px; padding: 28px 30px; color: #fff; border-radius: 18px; background: linear-gradient(135deg, #16355f, #235d8c 58%, #168294); box-shadow: 0 16px 40px rgb(22 53 95 / 16%); }
.etl-eyebrow { font-size: 12px; letter-spacing: .12em; opacity: .78; }
.etl-hero h1 { margin: 6px 0 8px; font-size: 30px; }
.etl-hero p { margin: 0; max-width: 680px; opacity: .84; }
.etl-hero__limits { display: flex; flex-wrap: wrap; justify-content: flex-end; align-content: flex-start; gap: 8px; max-width: 340px; }
.etl-hero__limits span { padding: 7px 10px; border: 1px solid rgb(255 255 255 / 25%); border-radius: 999px; background: rgb(255 255 255 / 10%); font-size: 12px; }
.etl-tabs { display: grid; grid-template-columns: repeat(4, 1fr); margin: 20px 0 14px; padding: 4px; border: 1px solid #dde4ef; border-radius: 12px; background: #fff; }
.etl-tabs button { border: 0; padding: 11px 14px; color: #607086; background: transparent; cursor: pointer; border-radius: 9px; }
.etl-tabs button span { display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: 7px; border-radius: 50%; background: #edf2f8; }
.etl-tabs button.active { color: #174d79; background: #eaf5fb; font-weight: 700; }
.etl-tabs button.active span { color: #fff; background: #1d7090; }
.etl-panel { padding: 22px; border: 1px solid #dfe5ee; border-radius: 14px; background: #fff; box-shadow: 0 8px 24px rgb(31 51 79 / 5%); }
.etl-panel__title, .etl-receipt header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.etl-panel__title h2, .etl-receipt h3 { margin: 0 0 4px; }
.etl-panel__title p, .etl-receipt p { margin: 0; color: #718096; font-size: 13px; }
.etl-upload-grid { display: grid; grid-template-columns: minmax(320px, 1.2fr) minmax(280px, .8fr); gap: 16px; }
.etl-dropzone { display: grid; place-items: center; min-height: 240px; padding: 20px; text-align: center; border: 1.5px dashed #91adc5; border-radius: 14px; background: #f7fbfe; cursor: pointer; }
.etl-dropzone input { position: absolute; opacity: 0; pointer-events: none; }
.etl-dropzone i { font-size: 42px; color: #2b789b; }
.etl-dropzone strong { margin-top: 12px; }
.etl-dropzone span { color: #7b8796; font-size: 12px; }
.etl-form-card { display: flex; flex-direction: column; gap: 14px; padding: 18px; border: 1px solid #e2e7ef; border-radius: 14px; }
.etl-form-card label, .etl-webhook-form label { display: grid; gap: 7px; font-size: 13px; color: #4d5d72; }
.etl-compat-note { margin: 14px 2px 0; color: #65758a; font-size: 12px; }
select, input { min-height: 38px; padding: 7px 10px; border: 1px solid #ced7e3; border-radius: 8px; color: #26364a; background: #fff; }
.etl-mapping-table textarea { width: 100%; min-width: 180px; margin-top: 6px; padding: 7px; border: 1px solid #ced7e3; border-radius: 7px; font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; resize: vertical; }
button, a { font: inherit; }
.etl-primary, .etl-secondary, .etl-danger { display: inline-flex; align-items: center; justify-content: center; min-height: 38px; padding: 8px 14px; border-radius: 8px; cursor: pointer; text-decoration: none; }
.etl-primary { border: 1px solid #17627f; color: #fff; background: #17627f; }
.etl-secondary { border: 1px solid #cbd5e1; color: #334155; background: #fff; }
.etl-danger { border: 1px solid #d24a4a; color: #b4232d; background: #fff4f4; }
button:disabled { opacity: .48; cursor: not-allowed; }
.etl-link-button { align-self: flex-start; border: 0; color: #17627f; background: transparent; cursor: pointer; }
.etl-webhook-form { display: grid; grid-template-columns: 180px 1fr 240px auto; gap: 12px; margin-top: 16px; padding: 16px; border-radius: 10px; background: #f5f8fb; }
.etl-webhook-form textarea { min-height: 38px; padding: 7px 10px; border: 1px solid #ced7e3; border-radius: 8px; resize: vertical; }
.etl-webhook-test { color: #17627f; }
.etl-progress-card { margin-top: 16px; padding: 16px; border-radius: 12px; background: #f0f8fb; }
.etl-progress-card div { display: flex; justify-content: space-between; }
.etl-progress-card progress { width: 100%; margin-top: 10px; }
.etl-progress-card p { margin: 6px 0 0; color: #6b7788; font-size: 12px; }
.etl-mapping-table-wrap, .etl-table-wrap { overflow-x: auto; }
.etl-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.etl-table th { padding: 10px; text-align: left; color: #56667b; background: #f3f6f9; border-bottom: 1px solid #dfe5ed; }
.etl-table td { max-width: 360px; padding: 11px 10px; vertical-align: top; border-bottom: 1px solid #edf0f4; }
.etl-table td small { display: block; margin-top: 4px; color: #6b7788; overflow-wrap: anywhere; }
.etl-table td pre { max-height: 220px; overflow: auto; white-space: pre-wrap; }
.etl-row-error { background: #fff7f7; }
.etl-row-ocr-low { box-shadow: inset 3px 0 #d64550; }
.etl-table td small.etl-ocr-low-note { color: #b4232d; font-weight: 700; }
.confidence-high { color: #168159; }
.confidence-medium { color: #b26d00; }
.confidence-low { color: #c23a43; font-weight: 700; }
.etl-ocr-confirm, .etl-update-fields { margin-top: 16px; padding: 14px; border: 1px solid #efd095; border-radius: 10px; background: #fffaf0; }
.etl-ocr-confirm { display: flex; justify-content: space-between; gap: 12px; }
.etl-ocr-confirm span { color: #845d19; font-size: 12px; }
.etl-update-fields label { margin-right: 18px; }
.etl-summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.etl-summary-grid button { display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto auto; text-align: left; padding: 13px; border: 1px solid #e0e6ee; border-radius: 10px; background: #fff; cursor: pointer; }
.etl-summary-grid strong { font-size: 23px; }
.etl-summary-grid small { color: #728096; }
.etl-dot { grid-row: 1 / 3; width: 7px; margin-right: 10px; border-radius: 999px; background: #9aa6b2; }
.etl-dot--new { background: #2b8a68; }.etl-dot--update { background: #2d6ecf; }.etl-dot--skip { background: #9aa6b2; }.etl-dot--error { background: #c9484f; }
.etl-alert { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: 14px 0; padding: 12px 14px; border-radius: 9px; font-size: 13px; }
.etl-alert div { display: grid; gap: 3px; }
.etl-alert--warning { color: #725114; background: #fff5d9; border: 1px solid #ebd593; }
.etl-alert--error { color: #8c2630; background: #fff0f1; border: 1px solid #efbdc2; }
.etl-actions { display: flex; gap: 8px; }
.etl-table-toolbar { display: flex; justify-content: space-between; align-items: center; margin: 12px 0; }
.etl-bulk-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.etl-bulk-actions button { min-height: 38px; padding: 7px 10px; border: 1px solid #ced7e3; border-radius: 8px; background: #fff; }
.etl-table-toolbar a { color: #17627f; }
.etl-match-key { display: inline-block; margin-right: 8px; padding: 4px 8px; border-radius: 999px; background: #eaf2f8; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
.etl-ocr-evidence { margin-top: 6px; color: #56667b; }
.etl-ocr-evidence pre { max-width: 420px; max-height: 180px; overflow: auto; white-space: pre-wrap; }
.etl-issues { margin: 0; padding-left: 18px; color: #b32833; }
.etl-pagination { display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 14px; }
.etl-pagination button { padding: 6px 10px; border: 1px solid #d6dee8; border-radius: 7px; background: #fff; }
.etl-history { display: grid; gap: 8px; max-height: 330px; overflow: auto; }
.etl-history__item { display: flex; justify-content: space-between; gap: 14px; padding: 12px; text-align: left; border: 1px solid #e0e6ed; border-radius: 9px; background: #fff; cursor: pointer; }
.etl-history__item.active { border-color: #4b8cac; background: #f0f8fb; }
.etl-history__item div { display: grid; gap: 4px; }
.etl-history__item div:last-child { text-align: right; }
.etl-history__item span, .etl-history__item small { color: #728096; font-size: 12px; }
.etl-status { font-weight: 700; }.etl-status--completed { color: #168159 !important; }.etl-status--failed, .etl-status--interrupted { color: #b72d38 !important; }
.etl-receipt { margin-top: 18px; padding: 18px; border: 1px solid #e0e6ee; border-radius: 12px; background: #fafbfd; }
.etl-receipt dl { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.etl-receipt dl div { padding: 10px; border-radius: 8px; background: #fff; }
.etl-receipt dt { color: #778397; font-size: 12px; }.etl-receipt dd { margin: 4px 0 0; }
.etl-receipt pre { max-height: 300px; overflow: auto; padding: 12px; border-radius: 8px; color: #d9e7ef; background: #152431; }
.etl-empty { padding: 60px 20px; text-align: center; color: #8390a1; }
@media (max-width: 900px) {
  .etl-center { padding: 12px; }
  .etl-hero, .etl-panel__title, .etl-receipt header { flex-direction: column; }
  .etl-hero__limits { justify-content: flex-start; }
  .etl-upload-grid, .etl-webhook-form { grid-template-columns: 1fr; }
  .etl-summary-grid, .etl-receipt dl { grid-template-columns: repeat(2, 1fr); }
  .etl-tabs button { font-size: 0; }.etl-tabs button span { margin: 0; font-size: 13px; }
}
</style>
