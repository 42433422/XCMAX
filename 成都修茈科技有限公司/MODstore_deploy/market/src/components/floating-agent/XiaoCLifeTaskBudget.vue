<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElInput } from 'element-plus/es/components/input/index'
import { ElSelect, ElOption } from 'element-plus/es/components/select/index'
import './xiaocLife.css'
import { employees, type EmployeeRow } from '../../api/employees'
import { llm, type LlmCatalogModelRow } from '../../api/llm'
import { xiaocLifeApi, type XiaoCLifePolicy, type XiaoCPortfolioLimits, type XiaoCPortfolioTemplate } from '../../application/xiaocLifeApi'

const props = defineProps<{ policy: XiaoCLifePolicy; busy: boolean; error?: string }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', value: { employee_id: string; portfolio_limits: XiaoCPortfolioLimits; task_input: Record<string, unknown> }): void
}>()
const open = ref(true)
const loading = ref(true)
const loadError = ref('')
const formError = ref('')
const employeeRows = ref<EmployeeRow[]>([])
const templates = ref<XiaoCPortfolioTemplate[]>([])
const selectedTemplate = ref('')
const employeeId = ref(props.policy.employee_id || '')
const taskInputJson = ref(JSON.stringify(props.policy.task_input ?? {}, null, 2))
const initial = props.policy.portfolio_limits
const costYuan = ref<number | undefined>(initial ? initial.cost_cents / 100 : undefined)
const tokens = ref<number | undefined>(initial?.tokens)
const seconds = ref<number | undefined>(initial?.compute_seconds ?? 300)
const expiry = ref(localDate(initial?.expires_at))
type TariffDraft = { provider: string; model: string; input: number | undefined; output: number | undefined; source: string }
const manualSource = '管理员配置的计提费率，非供应商账单'
const emptyTariff = (): TariffDraft => ({ provider: '', model: '', input: undefined, output: undefined, source: manualSource })
const tariffs = ref<TariffDraft[]>(
  initial?.tariffs.map((row) => ({
    provider: row.provider,
    model: row.model,
    input: row.input_cents_per_million / 100,
    output: row.output_cents_per_million / 100,
    source: row.source,
  })) || [emptyTariff()],
)
const advanced = ref({
  max_parallel: initial?.max_parallel ?? 1,
  max_failures: initial?.max_failures ?? 2,
  min_roi_bps: initial?.min_roi_bps ?? 0,
  observation_hours: initial?.observation_hours ?? 168,
})
type ModelOption = { key: string; provider: string; model: string; pricing?: LlmCatalogModelRow['pricing'] }
const models = ref<ModelOption[]>([])
const validEmployees = computed(() =>
  employeeRows.value.filter((row): row is EmployeeRow & { id: string } => typeof row.id === 'string' && !!row.id),
)

function localDate(value?: string) {
  const date = value ? new Date(value) : null
  return date && Number.isFinite(date.getTime())
    ? new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
    : ''
}

async function loadOptions() {
  loading.value = true
  loadError.value = ''
  const results = await Promise.allSettled([employees.listEmployees(), llm.llmCatalog(), llm.llmStatus(), xiaocLifeApi.templates()])
  const [staff, catalog, status, existing] = results
  employeeRows.value = staff.status === 'fulfilled' ? staff.value : []
  templates.value = existing.status === 'fulfilled' ? existing.value.items : []
  models.value = []
  if (catalog.status === 'fulfilled' && status.status === 'fulfilled') {
    const configured = new Set((status.value.providers || []).filter((row) => row.has_platform_key === true).map((row) => row.provider))
    models.value = catalog.value.providers
      .filter((provider) => configured.has(provider.provider))
      .flatMap((provider) =>
        provider.models
          .filter((model) => {
            const detail = provider.models_detailed?.find((row) => row.id === model)
            return detail?.capability?.platform_billing_ok !== false && (!detail?.category || ['llm', 'vlm'].includes(detail.category))
          })
          .map((model) => ({
            key: JSON.stringify([provider.provider, model]),
            provider: provider.provider,
            model,
            pricing: provider.models_detailed?.find((row) => row.id === model)?.pricing,
          })),
      )
  }
  if (staff.status === 'rejected' || catalog.status === 'rejected' || status.status === 'rejected')
    loadError.value = '员工或平台模型目录读取失败，请重试。未核实的项目不能保存。'
  else if (!validEmployees.value.length || !models.value.length)
    loadError.value = '还没有可选择的员工或已配置的平台模型，请先在员工和模型管理中完成配置。'
  else if (existing.status === 'rejected') loadError.value = '旧提案模板暂时无法读取，仍可填写新的任务预算。'
  loading.value = false
}

function copyTemplate(id: unknown) {
  const selected = templates.value.find((row) => row.decision_id === id)
  if (!selected) return
  const limits = selected.limits
  employeeId.value = selected.opportunities[0]?.employee_id || ''
  taskInputJson.value = JSON.stringify(selected.opportunities[0]?.input_data ?? {}, null, 2)
  costYuan.value = limits.cost_cents / 100
  tokens.value = limits.tokens
  seconds.value = limits.compute_seconds
  expiry.value = localDate(limits.expires_at)
  advanced.value = {
    max_parallel: limits.max_parallel,
    max_failures: limits.max_failures,
    min_roi_bps: limits.min_roi_bps,
    observation_hours: limits.observation_hours,
  }
  tariffs.value = limits.tariffs.map((row) => ({
    provider: row.provider,
    model: row.model,
    input: row.input_cents_per_million / 100,
    output: row.output_cents_per_million / 100,
    source: row.source,
  }))
  formError.value = Date.parse(limits.expires_at) <= Date.now() ? '这个模板已到期，请明确设置新的有效期后再保存。' : ''
}

function selectModel(tariff: TariffDraft, value: unknown) {
  const model = models.value.find((row) => row.key === value)
  if (!model) return
  tariff.provider = model.provider
  tariff.model = model.model
  const pricing = model.pricing
  if (
    pricing?.source === 'db' &&
    typeof pricing.effective_input_per_1k === 'number' &&
    typeof pricing.effective_output_per_1k === 'number' &&
    Number.isFinite(pricing.effective_input_per_1k) &&
    Number.isFinite(pricing.effective_output_per_1k)
  ) {
    tariff.input = Math.ceil(pricing.effective_input_per_1k * 100_000) / 100
    tariff.output = Math.ceil(pricing.effective_output_per_1k * 100_000) / 100
    tariff.source = '管理员确认的平台目录计提费率（按分向上取整），非供应商账单'
  } else {
    tariff.input = undefined
    tariff.output = undefined
    tariff.source = manualSource
  }
}

function setRate(tariff: TariffDraft, field: 'input' | 'output', value: number | undefined) {
  tariff[field] = value
  tariff.source = manualSource
}

function parseTaskInput(): Record<string, unknown> {
  let value: unknown
  try {
    value = JSON.parse(taskInputJson.value.trim() || '{}')
  } catch {
    throw new Error('员工任务参数不是有效的 JSON，请检查括号、引号和逗号。')
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('员工任务参数必须是 JSON 对象。')
  // Friendly validation follows the existing strategic execution contract; the server revalidates before freezing.
  const reserved = new Set([
    'employee_id',
    'user_id',
    'owner_user_id',
    'idempotency_key',
    'deadline_epoch',
    'handler',
    'handler_mode',
    'delegate',
    'multi_step',
    'fallback_cursor',
    'burn_in',
    'work_contract',
    'bench_llm_override',
    'customer_goal_ids',
    'provider',
    'model',
    'api_key',
    'authorization',
    'token',
    'password',
  ])
  if (Object.keys(value).some((key) => reserved.has(key) || /^(?:_|strategic_|suppress_|allow_)/.test(key)))
    throw new Error('任务参数只能填写业务数据，不能包含密钥、身份、模型或执行权限控制字段。')
  if (new TextEncoder().encode(JSON.stringify(value)).length > 64_000) throw new Error('员工任务参数不能超过 64000 字节。')
  return value as Record<string, unknown>
}

function save() {
  formError.value = ''
  if (loading.value || props.busy) return
  let inputData: Record<string, unknown>
  try {
    inputData = parseTaskInput()
  } catch (failure) {
    formError.value = failure instanceof Error ? failure.message : '员工任务参数校验失败。'
    return
  }
  if (!validEmployees.value.some((row) => row.id === employeeId.value)) {
    formError.value = '请选择当前员工目录里的员工。'
    return
  }
  if (
    costYuan.value === undefined ||
    !Number.isFinite(costYuan.value) ||
    costYuan.value <= 0 ||
    costYuan.value > 1_000_000 ||
    !Number.isInteger(tokens.value) ||
    !tokens.value ||
    tokens.value <= 0 ||
    tokens.value > 1_000_000_000 ||
    !Number.isInteger(seconds.value) ||
    !seconds.value ||
    seconds.value <= 0 ||
    seconds.value > 7_776_000
  ) {
    formError.value = '请填写正数费用上限、token 上限和时长。'
    return
  }
  const expires = Date.parse(expiry.value)
  if (!Number.isFinite(expires) || expires <= Date.now()) {
    formError.value = '请设置未来的任务有效期。'
    return
  }
  if (
    !tariffs.value.length ||
    tariffs.value.some(
      (tariff) =>
        !models.value.some((row) => row.provider === tariff.provider && row.model === tariff.model) ||
        tariff.input === undefined ||
        tariff.output === undefined ||
        !Number.isFinite(tariff.input) ||
        !Number.isFinite(tariff.output) ||
        tariff.input < 0 ||
        tariff.output < 0,
    )
  ) {
    formError.value = '请选择已配置的平台模型，并明确填写输入、输出计提费率。'
    return
  }
  const keys = tariffs.value.map((row) => JSON.stringify([row.provider, row.model]))
  if (new Set(keys).size !== keys.length) {
    formError.value = '同一个模型只需登记一组费率。'
    return
  }
  const cents = Math.round(costYuan.value * 100)
  emit('save', {
    employee_id: employeeId.value,
    task_input: inputData,
    portfolio_limits: {
      ...advanced.value,
      cost_cents: cents,
      stop_loss_cents: cents,
      tokens: tokens.value,
      compute_seconds: seconds.value,
      expires_at: new Date(expires).toISOString(),
      tariffs: tariffs.value.map((row) => ({
        provider: row.provider,
        model: row.model,
        input_cents_per_million: Math.round(row.input! * 100),
        output_cents_per_million: Math.round(row.output! * 100),
        source: row.source,
      })),
    },
  })
}

onMounted(loadOptions)
</script>

<template>
  <ElDialog
    v-model="open"
    title="企业任务预算模板"
    width="min(680px, calc(100vw - 24px))"
    :z-index="12120"
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="!busy"
    :show-close="!busy"
    @closed="emit('close')"
  >
    <div v-bind="{ 'data-xiaoc-control-plane': '' }" class="task-budget" @submit.prevent="save">
      <p>用于把发现转成待审批的企业任务。保存模板不批准任务，也不继承旧提案审批。</p>
      <p v-if="loadError" role="status">
        {{ loadError }} <button type="button" :disabled="loading" @click="loadOptions">重新读取目录</button>
      </p>
      <p v-if="error || formError" class="task-budget__error" role="alert">{{ error || formError }}</p>
      <ElForm label-position="top">
        <ElFormItem v-if="templates.length" label="复制已有提案的任务边界（可选）">
          <ElSelect v-model="selectedTemplate" filterable :teleported="false" :disabled="busy || loading" @change="copyTemplate"
            ><ElOption
              v-for="item in templates"
              :key="item.decision_id"
              :value="item.decision_id"
              :label="`${item.goal}${Date.parse(item.limits.expires_at) <= Date.now() ? '（已到期）' : ''}`"
          /></ElSelect>
        </ElFormItem>
        <ElFormItem label="执行员工"
          ><ElSelect v-model="employeeId" filterable :teleported="false" :disabled="busy || loading" placeholder="从现有员工中选择"
            ><ElOption
              v-for="employee in validEmployees"
              :key="employee.id"
              :value="employee.id"
              :label="`${employee.name || employee.id} · ${employee.id}`" /></ElSelect
        ></ElFormItem>
        <details class="task-budget__advanced">
          <summary>员工任务参数（可选）</summary>
          <p class="task-budget__note">
            填写员工需要的业务参数，默认为 {}，最多 64000 字节。请勿填写密钥、账号凭据或执行权限字段。审批时会展示实际冻结的参数。
          </p>
          <ElFormItem label="业务参数（JSON 对象）">
            <ElInput
              v-model="taskInputJson"
              type="textarea"
              :rows="5"
              :disabled="busy"
              v-bind="{ ariaLabel: '员工任务业务参数 JSON' }"
              placeholder='{"date":"2026-11-21","scope":"daily"}'
            />
          </ElFormItem>
        </details>
        <div class="task-budget__grid">
          <ElFormItem label="每个提案计提费用上限（元）"
            ><ElInputNumber
              v-model="costYuan"
              :min="0.01"
              :max="1000000"
              :precision="2"
              :disabled="busy"
              v-bind="{ ariaLabel: '任务费用上限元' }"
          /></ElFormItem>
          <ElFormItem label="每个提案 token 上限"
            ><ElInputNumber
              v-model="tokens"
              :min="1"
              :max="1000000000"
              :precision="0"
              :disabled="busy"
              v-bind="{ ariaLabel: '任务 token 上限' }"
          /></ElFormItem>
          <ElFormItem label="每个提案最长执行时间（秒）"
            ><ElInputNumber
              v-model="seconds"
              :min="1"
              :max="7776000"
              :precision="0"
              :disabled="busy"
              v-bind="{ ariaLabel: '任务最长执行秒数' }"
          /></ElFormItem>
          <ElFormItem label="任务有效期（本地时间）"
            ><input v-model="expiry" type="datetime-local" aria-label="任务有效期" :disabled="busy"
          /></ElFormItem>
        </div>
        <h4>允许使用的模型与计提费率</h4>
        <p class="task-budget__note">
          显示已配置的平台目录。登记价可预填；没有可信登记价时必须手动填写，空白不代表免费。计提用于预算控制，不代表供应商最终账单。
        </p>
        <fieldset v-for="(tariff, index) in tariffs" :key="index" class="task-budget__tariff">
          <legend>模型 {{ index + 1 }}</legend>
          <ElFormItem label="平台模型"
            ><ElSelect
              :model-value="tariff.provider && tariff.model ? JSON.stringify([tariff.provider, tariff.model]) : ''"
              @change="selectModel(tariff, $event)"
              filterable
              :teleported="false"
              :disabled="busy || loading"
              placeholder="选择模型"
              ><ElOption
                v-for="model in models"
                :key="model.key"
                :value="model.key"
                :label="`${model.provider} / ${model.model}`" /></ElSelect
          ></ElFormItem>
          <div class="task-budget__grid">
            <ElFormItem label="输入（元 / 百万 tokens）"
              ><ElInputNumber
                :model-value="tariff.input"
                @update:model-value="setRate(tariff, 'input', $event)"
                :min="0"
                :max="1000000"
                :precision="2"
                :disabled="busy"
                v-bind="{ ariaLabel: '模型输入计提费率' }"
            /></ElFormItem>
            <ElFormItem label="输出（元 / 百万 tokens）"
              ><ElInputNumber
                :model-value="tariff.output"
                @update:model-value="setRate(tariff, 'output', $event)"
                :min="0"
                :max="1000000"
                :precision="2"
                :disabled="busy"
                v-bind="{ ariaLabel: '模型输出计提费率' }"
            /></ElFormItem>
          </div>
          <p class="task-budget__note">{{ tariff.source }}</p>
          <button type="button" :disabled="busy" @click="tariffs.splice(index, 1)">删除此模型</button>
        </fieldset>
        <button type="button" :disabled="busy || tariffs.length >= 32" @click="tariffs.push(emptyTariff())">添加模型费率</button>
        <details class="task-budget__advanced">
          <summary>其他执行边界</summary>
          <p>
            并发 {{ advanced.max_parallel }}，允许失败 {{ advanced.max_failures }} 次，效果观察
            {{ advanced.observation_hours }} 小时，最低回报
            {{ advanced.min_roi_bps / 100 }}%。止损额度等于本次费用上限。复制旧模板时保留其边界。
          </p>
        </details>
        <div class="task-budget__actions">
          <button type="submit" :disabled="busy || loading">保存任务模板</button
          ><button type="button" :disabled="busy" @click="open = false">取消</button>
        </div>
      </ElForm>
    </div>
  </ElDialog>
</template>

<style scoped>
.task-budget {
  max-height: 70vh;
  overflow: auto;
  color: #18283d;
  font-size: 14px;
}
.task-budget__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}
.task-budget__grid :deep(.el-input-number),
.task-budget__grid input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.task-budget input[type='datetime-local'] {
  padding: 7px;
  border: 1px solid #cdd6e2;
  border-radius: 5px;
  font: inherit;
}
.task-budget__note {
  color: #58667a;
  font-size: 12px;
}
.task-budget__tariff {
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  margin: 10px 0;
  padding: 12px;
}
.task-budget__advanced {
  margin: 14px 0;
}
.task-budget__actions {
  display: flex;
  gap: 8px;
  margin: 18px 0 6px;
}
.task-budget button {
  border: 1px solid #c5d1e3;
  border-radius: 6px;
  background: #f5f8fc;
  color: #184994;
  padding: 6px 10px;
  font: inherit;
  cursor: pointer;
}
.task-budget button:disabled {
  opacity: 0.5;
  cursor: default;
}
.task-budget__error {
  color: #a4381c;
}
@media (max-width: 460px) {
  .task-budget__grid {
    grid-template-columns: 1fr;
  }
}
</style>
