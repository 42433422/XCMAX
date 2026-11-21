<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import './xiaocLife.css'
import { xiaocLifeApi, xiaocStateLabel, type XiaoCPortfolioTemplate } from '../../application/xiaocLifeApi'
import { ApiError } from '../../infrastructure/http/client'

const props = defineProps<{ decisionId: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed'): void }>()
const open = ref(true)
const proposal = ref<XiaoCPortfolioTemplate | null>(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const reviewed = ref(false)
const hasFrozenContract = computed(
  () =>
    !!proposal.value?.opportunities.length &&
    proposal.value.opportunities.every(
      (task) =>
        task.input_data !== undefined &&
        !!task.execution_binding?.pack_id &&
        !!task.execution_binding.config_sha256 &&
        !!task.execution_binding.input_sha256,
    ),
)
const canApprove = computed(
  () => hasFrozenContract.value && proposal.value?.status === 'proposed' && Date.parse(proposal.value.limits.expires_at) > Date.now(),
)

function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN')
}

async function refresh() {
  busy.value = true
  error.value = ''
  reviewed.value = false
  try {
    proposal.value = await xiaocLifeApi.portfolio(props.decisionId)
  } catch (failure) {
    proposal.value = null
    error.value =
      failure instanceof ApiError && [403, 404].includes(failure.status)
        ? '当前管理员无法查看这个提案，请由提案所属的管理员审核。'
        : '暂时无法读取提案，请重试。'
  } finally {
    busy.value = false
  }
}

async function approve() {
  if (!proposal.value || !reviewed.value || !canApprove.value || busy.value) return
  const reviewedHash = proposal.value.proposal_sha256
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await xiaocLifeApi.approvePortfolio(props.decisionId, reviewedHash)
    if (result.decision_id !== props.decisionId || result.status !== 'approved') throw new Error('审批回执待核实')
    await refresh()
    notice.value = '审批已记录；任务是否完成以真实执行与验证回执为准。'
    emit('changed')
  } catch (failure) {
    await refresh()
    error.value =
      failure instanceof ApiError && failure.status === 409
        ? '提案或有效期已变化。请重新查看最新内容，不会自动批准新版本。'
        : '审批结果暂时无法确认，已尝试读取最新状态。'
  } finally {
    busy.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <ElDialog
    v-model="open"
    title="企业提案审核"
    width="min(680px, calc(100vw - 24px))"
    :z-index="12120"
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="!busy"
    :show-close="!busy"
    @closed="emit('close')"
  >
    <section v-bind="{ 'data-xiaoc-control-plane': '' }" class="life-proposal" :aria-busy="busy">
      <p v-if="error" role="alert" class="life-proposal__error">{{ error }}</p>
      <p v-if="notice" role="status">{{ notice }}</p>
      <template v-if="proposal">
        <h3>{{ proposal.goal }}</h3>
        <p>{{ xiaocStateLabel(proposal.status) }} · {{ proposal.decision_id }}</p>
        <dl>
          <dt>计提费用上限 / 止损</dt>
          <dd>¥{{ (proposal.limits.cost_cents / 100).toFixed(2) }} / ¥{{ (proposal.limits.stop_loss_cents / 100).toFixed(2) }}</dd>
          <dt>token 上限</dt>
          <dd>{{ proposal.limits.tokens }}</dd>
          <dt>时间与并发</dt>
          <dd>{{ proposal.limits.compute_seconds }} 秒 · {{ proposal.limits.max_parallel }} 个并发</dd>
          <dt>失败与观察窗</dt>
          <dd>{{ proposal.limits.max_failures }} 次 · {{ proposal.limits.observation_hours }} 小时</dd>
          <dt>授权到期</dt>
          <dd>{{ formatTime(proposal.limits.expires_at) }}</dd>
        </dl>
        <h4>拟执行内容与来源</h4>
        <article v-for="(task, index) in proposal.opportunities" :key="index">
          <strong>{{ task.title }}</strong>
          <p>员工：{{ task.employee_id }}</p>
          <p class="life-proposal__task">{{ task.task }}</p>
          <details v-if="task.input_data !== undefined" open>
            <summary>已冻结的员工任务参数</summary>
            <pre>{{ JSON.stringify(task.input_data ?? {}, null, 2) }}</pre>
          </details>
          <details v-if="task.execution_binding">
            <summary>已冻结的员工版本与配置摘要</summary>
            <dl class="life-proposal__binding">
              <dt>员工包 / 版本</dt>
              <dd>{{ task.execution_binding.pack_id }} / {{ task.execution_binding.version }}</dd>
              <dt>配置摘要</dt>
              <dd>
                <code>{{ task.execution_binding.config_sha256 }}</code>
              </dd>
              <dt>参数摘要</dt>
              <dd>
                <code>{{ task.execution_binding.input_sha256 }}</code>
              </dd>
              <dt>清单摘要</dt>
              <dd>
                <code>{{ task.execution_binding.manifest_sha256 }}</code>
              </dd>
              <dt>归档摘要</dt>
              <dd>
                <code>{{ task.execution_binding.archive_sha256 || '无独立归档' }}</code>
              </dd>
            </dl>
          </details>
          <p v-else class="life-proposal__error">尚未读取员工的冻结版本与配置摘要，请刷新核对。</p>
          <ul>
            <li v-for="source in task.source_refs || []" :key="source">{{ source }}</li>
          </ul>
        </article>
        <p v-if="!hasFrozenContract" class="life-proposal__error">
          提案缺少已冻结的实际输入或员工摘要，暂不能批准。请读取最新提案；旧提案可复制模板后重新提出。
        </p>
        <h4>允许使用的模型与计提费率</h4>
        <ul>
          <li v-for="tariff in proposal.limits.tariffs" :key="`${tariff.provider}/${tariff.model}`">
            {{ tariff.provider }} / {{ tariff.model }}：输入 ¥{{ tariff.input_cents_per_million / 100 }}、输出 ¥{{
              tariff.output_cents_per_million / 100
            }}
            / 百万 tokens。{{ tariff.source }}
          </li>
        </ul>
        <details>
          <summary>本次审核的提案摘要</summary>
          <code>{{ proposal.proposal_sha256 }}</code>
        </details>
        <label v-if="canApprove" class="life-proposal__confirm"
          ><input
            v-model="reviewed"
            type="checkbox"
            :disabled="busy"
          />我已核对任务内容、员工版本、实际参数、来源与预算，同意批准这个提案。</label
        >
        <div class="life-proposal__actions">
          <button v-if="canApprove" type="button" :disabled="!reviewed || busy" @click="approve">批准这个提案</button>
          <button type="button" :disabled="busy" @click="refresh">读取最新提案</button>
        </div>
      </template>
      <button v-else type="button" :disabled="busy" @click="refresh">{{ busy ? '正在读取…' : '重试读取' }}</button>
    </section>
  </ElDialog>
</template>

<style scoped>
.life-proposal {
  color: #18283d;
  max-height: 70vh;
  overflow: auto;
  overflow-wrap: anywhere;
  font-size: 14px;
}
.life-proposal dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px 16px;
}
.life-proposal dd {
  margin: 0;
}
.life-proposal article {
  padding: 10px;
  border: 1px solid #d7e0ec;
  border-radius: 7px;
  margin: 8px 0;
}
.life-proposal__task {
  white-space: pre-wrap;
}
.life-proposal pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
  background: #f2f6fc;
  padding: 10px;
  border-radius: 6px;
}
.life-proposal__binding {
  grid-template-columns: auto minmax(0, 1fr) !important;
}
.life-proposal__confirm {
  display: block;
  padding: 14px 0;
}
.life-proposal code {
  font-size: 11px;
  overflow-wrap: anywhere;
}
.life-proposal__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0;
}
.life-proposal button {
  padding: 6px 10px;
  border: 1px solid #c5d1e3;
  border-radius: 6px;
  background: #f5f8fc;
  color: #184994;
  font: inherit;
  cursor: pointer;
}
.life-proposal button:disabled {
  opacity: 0.5;
  cursor: default;
}
.life-proposal__error {
  color: #a4381c;
}
</style>
