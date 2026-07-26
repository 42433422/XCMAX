<template src="./EtlCenterView.template.html"></template>
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
import { tabForRunStatus, type EtlRunTab } from '@/utils/etlRunView'

type TabId = EtlRunTab

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
const targetType = ref('customer_products')
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
const linkedCustomerNames = computed(() => {
  const names = runRows.value
    .map((row) => String(row.normalized.customer_name || '').trim())
    .filter(Boolean)
  return [...new Set(names)]
})
const plannedBusinessRows = computed(() => {
  if (!currentRun.value) return 0
  return currentRun.value.summary.new
    + currentRun.value.summary.update
    + currentRun.value.summary.skip
})
const runOutcomeText = computed(() => {
  if (!currentRun.value) return ''
  const summary = currentRun.value.summary
  if (currentRun.value.status === 'completed') {
    return `已写入 ${summary.executed} 行；新增 ${summary.new}、更新 ${summary.update}、跳过 ${summary.skip}`
  }
  return `计划处理 ${plannedBusinessRows.value} 行；新增 ${summary.new}、更新 ${summary.update}、跳过 ${summary.skip}`
})

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
      targetType.value = caps.targets[0]?.type || 'customer_products'
    }
    const requestedRun = String(route.query.run_id || '')
    if (requestedRun) {
      currentRun.value = await etlApi.run(requestedRun)
      syncDraft()
      activeTab.value = tabForRunStatus(currentRun.value.status)
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
  activeTab.value = 'history'
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

<style scoped src="./EtlCenterView.css"></style>
