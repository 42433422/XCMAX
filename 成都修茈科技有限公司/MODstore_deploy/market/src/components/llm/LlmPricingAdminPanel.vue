<template>
  <details class="llm-details llm-details--pricing-admin">
    <summary class="llm-details__summary">
      <span class="llm-details__chevron" aria-hidden="true" />
      <span class="llm-details__summary-text">定价管理（管理员）</span>
      <span class="llm-byok-summary-badge">运营改价</span>
    </summary>

    <p v-if="err" class="flash flash-err">{{ err }}</p>
    <p v-if="note" class="flash flash-ok">{{ note }}</p>

    <section class="llm-pricing-admin__section llm-pricing-admin__section--official">
      <h4 class="llm-pricing-admin__title">官网价同步</h4>
      <p class="llm-pricing-admin__hint">
        从 OpenRouter 公开价表 + 内置各厂商定价页数据拉取<strong>官网价</strong>（元/1K tokens），写入「官网 in/out」列。
        <template v-if="officialSourceUrl">
          参考：<a :href="officialSourceUrl" class="inline-link" target="_blank" rel="noopener noreferrer">定价页</a>
        </template>
      </p>
      <div class="llm-pricing-admin__grid">
        <label class="llm-pricing-admin__field">
          <span>官网价倍率（售价 = 官网 × 倍率）</span>
          <input v-model.number="settingsForm.official_markup_multiplier" class="input" type="number" min="1" max="10" step="0.01" />
        </label>
      </div>
      <div class="llm-pricing-admin__actions">
        <button type="button" class="btn btn-primary-solid" :disabled="syncBusy" @click="syncOfficial(false)">
          {{ syncBusy ? '同步中…' : '从官网同步' }}
        </button>
        <button type="button" class="btn btn-ghost" :disabled="syncBusy" @click="syncOfficial(true)">
          同步并应用倍率
        </button>
        <button type="button" class="btn btn-primary-solid" :disabled="applyBusy" @click="applyMarkup">
          {{ applyBusy ? '应用中…' : '按倍率写入平台售价' }}
        </button>
      </div>
      <p class="llm-pricing-admin__hint llm-pricing-admin__hint--tip">
        应用官网倍率后，建议将下方「服务费倍率」设为 1，避免结算时重复加价。
      </p>
    </section>

    <section class="llm-pricing-admin__section">
      <h4 class="llm-pricing-admin__title">全局计费参数</h4>
      <p class="llm-pricing-admin__hint">未单独登记的模型使用默认价；实际扣费 = token 用量 × 单价 × 服务费倍率。</p>
      <div class="llm-pricing-admin__grid">
        <label class="llm-pricing-admin__field">
          <span>服务费倍率（结算时乘）</span>
          <input v-model.number="settingsForm.service_fee_multiplier" class="input" type="number" min="1" max="10" step="0.01" />
        </label>
        <label class="llm-pricing-admin__field">
          <span>默认 input /1k（元）</span>
          <input v-model.number="settingsForm.default_input_price_per_1k" class="input" type="number" min="0" step="0.0001" />
        </label>
        <label class="llm-pricing-admin__field">
          <span>默认 output /1k（元）</span>
          <input v-model.number="settingsForm.default_output_price_per_1k" class="input" type="number" min="0" step="0.0001" />
        </label>
        <label class="llm-pricing-admin__field">
          <span>默认最低扣费（元）</span>
          <input v-model.number="settingsForm.default_min_charge" class="input" type="number" min="0" step="0.01" />
        </label>
      </div>
      <button type="button" class="btn btn-primary-solid" :disabled="settingsSaving" @click="saveSettings">
        {{ settingsSaving ? '保存中…' : '保存全局设置' }}
      </button>
    </section>

    <section class="llm-pricing-admin__section">
      <h4 class="llm-pricing-admin__title">按厂商批量登记 · {{ providerLabel }}</h4>
      <div class="llm-pricing-admin__grid">
        <label class="llm-pricing-admin__field">
          <span>input /1k</span>
          <input v-model.number="batchForm.input_price_per_1k" class="input" type="number" min="0" step="0.0001" />
        </label>
        <label class="llm-pricing-admin__field">
          <span>output /1k</span>
          <input v-model.number="batchForm.output_price_per_1k" class="input" type="number" min="0" step="0.0001" />
        </label>
        <label class="llm-pricing-admin__field">
          <span>最低扣费</span>
          <input v-model.number="batchForm.min_charge" class="input" type="number" min="0" step="0.01" />
        </label>
      </div>
      <div class="llm-pricing-admin__actions">
        <button type="button" class="btn btn-primary-solid" :disabled="batchBusy" @click="runBatch('unpriced_only')">
          {{ batchBusy ? '处理中…' : '应用到未定价模型' }}
        </button>
        <button type="button" class="btn btn-ghost" :disabled="batchBusy" @click="runBatch('all_catalog')">
          覆盖本厂商全部目录模型
        </button>
      </div>
    </section>

    <section class="llm-pricing-admin__section">
      <div class="llm-pricing-admin__head">
        <h4 class="llm-pricing-admin__title">模型定价表</h4>
        <button type="button" class="btn btn-ghost" :disabled="listLoading" @click="loadPrices">
          {{ listLoading ? '加载中…' : '刷新列表' }}
        </button>
      </div>
      <div v-if="listLoading" class="loading">加载定价…</div>
      <div v-else-if="priceRows.length" class="llm-pricing-admin__table-wrap">
        <table class="llm-pricing-admin__table">
          <thead>
            <tr>
              <th>模型</th>
              <th>官网 in</th>
              <th>官网 out</th>
              <th>售价 in</th>
              <th>售价 out</th>
              <th>最低</th>
              <th>启用</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in priceRows" :key="row.provider + ':' + row.model">
              <td>
                <code class="llm-code">{{ row.model }}</code>
              </td>
              <td class="llm-pricing-admin__official">
                {{ fmtOfficial(row.official_input_price_per_1k) }}
              </td>
              <td class="llm-pricing-admin__official">
                {{ fmtOfficial(row.official_output_price_per_1k) }}
              </td>
              <td>
                <input v-model.number="row._edit.input_price_per_1k" class="input input--compact" type="number" min="0" step="0.0001" />
              </td>
              <td>
                <input v-model.number="row._edit.output_price_per_1k" class="input input--compact" type="number" min="0" step="0.0001" />
              </td>
              <td>
                <input v-model.number="row._edit.min_charge" class="input input--compact" type="number" min="0" step="0.01" />
              </td>
              <td>
                <input v-model="row._edit.enabled" type="checkbox" />
              </td>
              <td>
                <button
                  type="button"
                  class="btn btn-ghost btn--compact"
                  :disabled="rowSaving === row.model"
                  @click="saveRow(row)"
                >
                  {{ rowSaving === row.model ? '…' : '保存' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted small">当前厂商暂无登记定价，可用批量按钮从目录写入。</p>

      <div class="llm-pricing-admin__new">
        <h5>新增 / 覆盖单条</h5>
        <input v-model="newRow.model" class="input" placeholder="模型 id（与目录一致）" />
        <div class="llm-pricing-admin__grid">
          <input v-model.number="newRow.input_price_per_1k" class="input" type="number" min="0" step="0.0001" placeholder="in/1k" />
          <input v-model.number="newRow.output_price_per_1k" class="input" type="number" min="0" step="0.0001" placeholder="out/1k" />
          <input v-model.number="newRow.min_charge" class="input" type="number" min="0" step="0.01" placeholder="最低" />
        </div>
        <button type="button" class="btn btn-primary-solid" :disabled="newSaving || !newRow.model.trim()" @click="saveNewRow">
          {{ newSaving ? '保存中…' : '保存定价' }}
        </button>
      </div>
    </section>
  </details>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { api } from '../../api'

const props = defineProps({
  provider: { type: String, required: true },
  providerLabel: { type: String, default: '' },
})

const emit = defineEmits(['saved'])

const err = ref('')
const note = ref('')
const settingsSaving = ref(false)
const batchBusy = ref(false)
const listLoading = ref(false)
const rowSaving = ref('')
const newSaving = ref(false)

const settingsForm = reactive({
  service_fee_multiplier: 1.5,
  official_markup_multiplier: 1.5,
  default_input_price_per_1k: 0.006,
  default_output_price_per_1k: 0.018,
  default_min_charge: 0.02,
})

const officialSourceUrl = ref('')
const syncBusy = ref(false)
const applyBusy = ref(false)

const batchForm = reactive({
  input_price_per_1k: 0.006,
  output_price_per_1k: 0.018,
  min_charge: 0.02,
})

interface PriceRow {
  provider: string
  model: string
  label?: string
  official_input_price_per_1k: number | null
  official_output_price_per_1k: number | null
  official_source?: string
  input_price_per_1k: number
  output_price_per_1k: number
  min_charge: number
  enabled: boolean
  _edit: {
    input_price_per_1k: number
    output_price_per_1k: number
    min_charge: number
    enabled: boolean
  }
}

const priceRows = ref<PriceRow[]>([])

const newRow = reactive({
  model: '',
  input_price_per_1k: 0.006,
  output_price_per_1k: 0.018,
  min_charge: 0.02,
})

function applySettingsFromApi(s: Record<string, unknown> | undefined) {
  if (!s) return
  if (s.service_fee_multiplier != null) settingsForm.service_fee_multiplier = Number(s.service_fee_multiplier)
  if (s.official_markup_multiplier != null) settingsForm.official_markup_multiplier = Number(s.official_markup_multiplier)
  else if (s.service_fee_multiplier != null) settingsForm.official_markup_multiplier = Number(s.service_fee_multiplier)
  if (s.default_input_price_per_1k != null) settingsForm.default_input_price_per_1k = Number(s.default_input_price_per_1k)
  if (s.default_output_price_per_1k != null) settingsForm.default_output_price_per_1k = Number(s.default_output_price_per_1k)
  if (s.default_min_charge != null) settingsForm.default_min_charge = Number(s.default_min_charge)
}

function fmtOfficial(v: number | null | undefined) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toFixed(4)
}

async function loadOfficialSource() {
  if (!props.provider) return
  try {
    const res = (await api.llmAdminOfficialSources(props.provider)) as { source_url?: string }
    officialSourceUrl.value = String(res.source_url || '')
  } catch {
    officialSourceUrl.value = ''
  }
}

async function syncOfficial(applyAfter: boolean) {
  syncBusy.value = true
  err.value = ''
  note.value = ''
  try {
    await api.llmAdminPricingSettings({
      official_markup_multiplier: settingsForm.official_markup_multiplier,
    })
    const res = (await api.llmAdminSyncOfficialPrices({
      provider: props.provider,
      sources: ['curated', 'openrouter'],
      apply_markup: applyAfter,
    })) as { updated?: number; skipped?: number; apply_markup?: { applied?: number } }
    let msg = `已同步官网价 ${res.updated ?? 0} 条，未匹配 ${res.skipped ?? 0} 条`
    if (applyAfter && res.apply_markup) {
      msg += `；已应用倍率 ${res.apply_markup.applied ?? 0} 条`
    }
    note.value = msg
    await loadPrices()
    emit('saved')
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    syncBusy.value = false
  }
}

async function applyMarkup() {
  applyBusy.value = true
  err.value = ''
  note.value = ''
  try {
    await api.llmAdminPricingSettings({
      official_markup_multiplier: settingsForm.official_markup_multiplier,
      service_fee_multiplier: settingsForm.service_fee_multiplier,
    })
    const res = (await api.llmAdminApplyOfficialMarkup({
      provider: props.provider,
      multiplier: settingsForm.official_markup_multiplier,
    })) as { applied?: number; skipped?: number }
    note.value = `已按倍率 ${settingsForm.official_markup_multiplier} 写入售价 ${res.applied ?? 0} 条，跳过 ${res.skipped ?? 0} 条`
    await loadPrices()
    emit('saved')
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    applyBusy.value = false
  }
}

async function loadPrices() {
  if (!props.provider) return
  listLoading.value = true
  err.value = ''
  try {
    const res = (await api.llmAdminListPricing({ provider: props.provider, limit: 500 })) as {
      settings?: Record<string, unknown>
      items?: Array<Record<string, unknown>>
    }
    applySettingsFromApi(res.settings)
    priceRows.value = (res.items || []).map((it) => {
      const enabled = Boolean(it.enabled !== false)
      return {
        provider: String(it.provider || props.provider),
        model: String(it.model || ''),
        label: String(it.label || ''),
        official_input_price_per_1k:
          it.official_input_price_per_1k != null ? Number(it.official_input_price_per_1k) : null,
        official_output_price_per_1k:
          it.official_output_price_per_1k != null ? Number(it.official_output_price_per_1k) : null,
        official_source: String(it.official_source || ''),
        input_price_per_1k: Number(it.input_price_per_1k) || 0,
        output_price_per_1k: Number(it.output_price_per_1k) || 0,
        min_charge: Number(it.min_charge) || 0,
        enabled,
        _edit: {
          input_price_per_1k: Number(it.input_price_per_1k) || 0,
          output_price_per_1k: Number(it.output_price_per_1k) || 0,
          min_charge: Number(it.min_charge) || 0,
          enabled,
        },
      }
    })
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    listLoading.value = false
  }
}

async function saveSettings() {
  settingsSaving.value = true
  err.value = ''
  note.value = ''
  try {
    const res = (await api.llmAdminPricingSettings({
      service_fee_multiplier: settingsForm.service_fee_multiplier,
      official_markup_multiplier: settingsForm.official_markup_multiplier,
      default_input_price_per_1k: settingsForm.default_input_price_per_1k,
      default_output_price_per_1k: settingsForm.default_output_price_per_1k,
      default_min_charge: settingsForm.default_min_charge,
    })) as { settings?: Record<string, unknown> }
    applySettingsFromApi(res.settings)
    note.value = '全局计费参数已保存'
    emit('saved')
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    settingsSaving.value = false
  }
}

async function runBatch(mode: 'unpriced_only' | 'all_catalog') {
  batchBusy.value = true
  err.value = ''
  note.value = ''
  try {
    const res = (await api.llmAdminBatchPricing({
      provider: props.provider,
      mode,
      template: { ...batchForm },
    })) as { written?: number }
    note.value = `已写入 ${res.written ?? 0} 条定价`
    await loadPrices()
    emit('saved')
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    batchBusy.value = false
  }
}

async function saveRow(row: PriceRow) {
  rowSaving.value = row.model
  err.value = ''
  try {
    await api.llmAdminSavePrice({
      provider: props.provider,
      model: row.model,
      label: row.label || row.model,
      input_price_per_1k: row._edit.input_price_per_1k,
      output_price_per_1k: row._edit.output_price_per_1k,
      min_charge: row._edit.min_charge,
      enabled: row._edit.enabled,
    })
    note.value = `已保存 ${row.model}`
    emit('saved')
    await loadPrices()
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    rowSaving.value = ''
  }
}

async function saveNewRow() {
  const mid = newRow.model.trim()
  if (!mid) return
  newSaving.value = true
  err.value = ''
  try {
    await api.llmAdminSavePrice({
      provider: props.provider,
      model: mid,
      label: mid,
      input_price_per_1k: newRow.input_price_per_1k,
      output_price_per_1k: newRow.output_price_per_1k,
      min_charge: newRow.min_charge,
      enabled: true,
    })
    newRow.model = ''
    note.value = '新定价已保存'
    emit('saved')
    await loadPrices()
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    newSaving.value = false
  }
}

watch(
  () => props.provider,
  () => {
    void loadPrices()
    void loadOfficialSource()
  },
  { immediate: true },
)
</script>

<style scoped>
.llm-details--pricing-admin {
  margin-top: 1rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 0.75rem;
}
.llm-pricing-admin__section {
  margin: 1rem 0;
}
.llm-pricing-admin__title {
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
  color: rgba(255, 255, 255, 0.88);
}
.llm-pricing-admin__hint {
  margin: 0 0 0.75rem;
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.5);
}
.llm-pricing-admin__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.llm-pricing-admin__field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.55);
}
.llm-pricing-admin__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.llm-pricing-admin__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.llm-pricing-admin__table-wrap {
  overflow-x: auto;
  margin: 0.5rem 0;
}
.llm-pricing-admin__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.llm-pricing-admin__table th,
.llm-pricing-admin__table td {
  padding: 0.35rem 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  text-align: left;
}
.input--compact {
  max-width: 5.5rem;
  padding: 0.25rem 0.4rem;
  font-size: 0.8rem;
}
.btn--compact {
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
}
.llm-pricing-admin__new {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px dashed rgba(255, 255, 255, 0.1);
}
.llm-pricing-admin__new h5 {
  margin: 0 0 0.5rem;
  font-size: 0.85rem;
}
.llm-pricing-admin__section--official {
  padding: 0.75rem;
  border-radius: 10px;
  background: rgba(129, 140, 248, 0.06);
  border: 1px solid rgba(129, 140, 248, 0.15);
}
.llm-pricing-admin__hint--tip {
  margin-top: 0.5rem;
  color: rgba(255, 200, 100, 0.75);
}
.llm-pricing-admin__official {
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.75rem;
  white-space: nowrap;
}
</style>
