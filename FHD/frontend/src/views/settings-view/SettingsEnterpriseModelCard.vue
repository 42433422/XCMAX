<template>
  <div class="enterprise-model">
    <div class="enterprise-model__current">
      <h3 class="settings-model-service-empty__title">企业模型</h3>
      <p class="muted">当前生效模型 <strong>{{ activeModel || '待确认' }}</strong></p>
    </div>
    <div class="enterprise-model__controls">
      <ElSelect v-model="selected" aria-label="选择企业模型" filterable :loading="loading" :disabled="busy || !editable">
        <ElOption :value="defaultChoice" label="跟随账号默认模型" />
        <ElOption v-if="retired" :value="saved" :label="snapshot?.model || ''" disabled />
        <ElOption v-for="row in models" :key="row.key" :value="row.key" :label="row.label" :disabled="row.disabled" />
      </ElSelect>
      <button class="btn btn-sm btn-primary" type="button" data-testid="enterprise-model-save" :disabled="!canSave" @click="save">{{ saving ? '保存中…' : '保存模型' }}</button>
      <button class="btn btn-sm btn-secondary" type="button" :disabled="busy" @click="load(true)">刷新目录</button>
    </div>
    <p v-if="selectedModel?.summary" class="muted">{{ selectedModel.summary }}</p>
    <p v-if="loadError || saveError" class="muted" role="alert">{{ saveError || loadError }}</p>
    <p v-else-if="snapshot && !editable" class="muted">{{ deploymentManaged ? '当前模型由部署方管理。' : '仅企业管理员可修改。' }}</p>
    <p v-else-if="!loading && !models.length" class="muted" role="status">暂无可选的执行模型。</p>
    <p v-if="notice" class="muted" role="status">{{ notice }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElOption, ElSelect } from 'element-plus'
import { api } from '@/api/core'
import { fetchMarketLlmCatalog, type MarketLlmCatalogData } from '@/api/marketAccount'
import { notifyPlatformModelChanged } from '@/api/platformModel'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { resolveApiErrorMessage } from '@/utils/resolveApiError'

type Choice = { provider: string | null; model: string | null }
type Snapshot = Choice & { owner_id: string; editable: boolean; revision: number }
type Option = { provider: string; model: string; key: string; label: string; disabled: boolean; summary: string }
const props = defineProps<{ owner: string; activeModel?: string; deploymentManaged?: boolean; checking?: boolean }>()
const path = '/api/workspace/model'
const defaultChoice = 'account'
const snapshot = ref<Snapshot | null>(null), models = ref<Option[]>([]), selected = ref(defaultChoice)
const loading = ref(false), saving = ref(false), loadError = ref(''), saveError = ref(''), notice = ref('')
let request: AbortController | undefined

const modelKey = (row: Choice | null) => row?.provider && row.model ? JSON.stringify([row.provider, row.model]) : defaultChoice
const saved = computed(() => modelKey(snapshot.value))
const retired = computed(() => saved.value !== defaultChoice && !models.value.some(row => row.key === saved.value))
const editable = computed(() => !!snapshot.value?.editable && !props.deploymentManaged)
const busy = computed(() => loading.value || saving.value || !!props.checking)
const selectedModel = computed(() => models.value.find(row => row.key === selected.value))
const canSave = computed(() => editable.value && !busy.value && selected.value !== saved.value)

const asRecord = (value: unknown) => value && typeof value === 'object' ? value as Record<string, unknown> : undefined
const asLimit = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : undefined

function catalogOptions(catalog: MarketLlmCatalogData): Option[] {
  const choices = new Map<string, Option>()
  for (const { provider, label, runtime_models, models_detailed } of catalog.providers || []) {
    if (!provider) continue
    const ids = runtime_models ?? models_detailed?.filter(row => row.runtime_selectable === true).map(row => row.id) ?? []
    for (const model of ids) {
      if (typeof model !== 'string' || !model.trim()) continue
      const detail = models_detailed?.find(row => row.id === model)
      const execution = asRecord(detail?.execution)
      const disabled = execution?.selectable === false
      const reason = disabled && typeof execution?.message === 'string' ? execution.message : '兼容性待校验'
      const key = modelKey({ provider, model })
      const suffix = execution?.selectable === true ? '' : `（${reason}）`
      const limits = asRecord(detail?.model_capabilities)
      const context = asLimit(limits?.context_window)
      const output = asLimit(limits?.max_output_tokens)
      const protocol = execution?.protocol === 'responses' ? 'Responses' :
        execution?.protocol === 'chat_completions' ? 'Chat Completions → Responses' : undefined
      const summary = context && output && output < context
        ? [protocol, `可用输入 ${Math.min(asLimit(limits?.max_input_tokens) ?? context, context - output).toLocaleString()} tokens`,
            `最大输出 ${output.toLocaleString()} tokens`].filter(Boolean).join(' · ')
        : protocol || ''
      choices.set(key, { key, provider, model, disabled, summary, label: `${label || provider} · ${model}${suffix}` })
    }
  }
  return [...choices.values()]
}

function startRequest() {
  request?.abort()
  request = new AbortController()
  return request.signal
}

async function load(refresh = false) {
  const signal = startRequest()
  const owner = props.owner
  snapshot.value = null
  models.value = []
  selected.value = defaultChoice
  loadError.value = saveError.value = notice.value = ''
  loading.value = true
  saving.value = false
  const [preference, catalog] = await Promise.allSettled([
    api.get<Snapshot>(path, {}, { signal, cache: 'no-store', quiet: true }),
    fetchMarketLlmCatalog('', refresh, signal),
  ])
  if (signal.aborted) return
  if (preference.status === 'fulfilled' && preference.value?.owner_id === owner) {
    snapshot.value = preference.value
    selected.value = saved.value
  } else loadError.value = '无法读取当前企业模型配置。'
  if (catalog.status === 'fulfilled' && !catalog.value.degraded) models.value = catalogOptions(catalog.value)
  else loadError.value ||= '无法读取模型目录。'
  loading.value = false
}

async function save() {
  const current = snapshot.value, option = selectedModel.value
  if (!canSave.value || !current || current.owner_id !== props.owner || (selected.value !== defaultChoice && (!option || option.disabled))) return
  const signal = startRequest()
  const choice = { provider: option?.provider ?? null, model: option?.model ?? null }
  saving.value = true
  saveError.value = notice.value = ''
  try {
    let token = current
    let next: Snapshot | undefined
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        next = await api.put<Snapshot>(path, {
          ...choice, expected_owner_id: token.owner_id, expected_revision: token.revision,
        }, { signal, retry: false, quiet: true })
        break
      } catch (error) {
        if ((error as { status?: number })?.status !== 409 || attempt > 0 || signal.aborted) throw error
        const fresh = await api.get<Snapshot>(path, {}, { signal, cache: 'no-store', quiet: true })
        // A different account or model choice is a real conflict. Only an
        // unrelated preference update may be retried with a fresh CAS token.
        if (fresh.owner_id !== token.owner_id || !fresh.editable || modelKey(fresh) !== modelKey(token)) throw error
        token = fresh
      }
    }
    if (signal.aborted) return
    if (!next || next.owner_id !== token.owner_id || next.revision !== token.revision + 1 ||
      modelKey(next) !== modelKey(choice)) throw new Error('invalid receipt')
    snapshot.value = next
    notifyPlatformModelChanged()
    notice.value = '已保存，运行验收状态将随模型更新。'
  } catch (error) {
    if (signal.aborted) return
    const status = (error as { status?: number })?.status
    if (status === 409) {
      const refresh = load()
      const reload = request?.signal
      await refresh
      if (!reload?.aborted) saveError.value = '配置已更新，请重新选择。'
    } else if (status === 422 || status === 503) {
      const data: unknown = (error as { data?: unknown })?.data
      const root = data && typeof data === 'object' ? data as Record<string, unknown> : undefined
      const detail = root?.detail
      const payload = detail && typeof detail === 'object' ? detail as Record<string, unknown> : root
      const message = typeof detail === 'string' ? detail : typeof payload?.message === 'string' ? payload.message : undefined
      saveError.value = resolveApiErrorMessage((key: string) => key, { message }, '无法确认模型接入条件，请重新读取或联系管理员。')
    } else saveError.value = '保存未确认，请检查所选模型或重新读取。'
  } finally {
    if (!signal.aborted) saving.value = false
  }
}

watch(() => [props.owner, productReadAccountEpoch.value, getAuthSessionEpoch()], () => void load(), { immediate: true, flush: 'sync' })
onBeforeUnmount(() => request?.abort())
</script>

<style scoped>
.enterprise-model__current, .enterprise-model__controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.enterprise-model__current { justify-content: space-between; }
.enterprise-model p, .enterprise-model h3 { margin: 0; overflow-wrap: anywhere; }
.enterprise-model h3 { font-size: 15px; font-weight: 650; }
.enterprise-model__controls { margin: 8px 0; }
.enterprise-model__controls :deep(.el-select) { flex: 1 1 220px; min-width: 0; }
</style>
