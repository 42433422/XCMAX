<template>
  <section class="kellai-inbox" aria-labelledby="kellai-inbox-title">
    <header class="kellai-inbox__head">
      <span class="kellai-inbox__avatar" aria-hidden="true">客</span>
      <div class="kellai-inbox__heading">
        <h2 id="kellai-inbox-title">客户消息 · 客来来</h2>
        <p>客户档案和会话只在本机读取；当前阶段不会自动发送消息。</p>
      </div>
      <span :class="['kellai-inbox__status', `is-${binding.state}`]">{{ statusLabel }}</span>
      <button type="button" class="kellai-inbox__button is-quiet" :disabled="busy" @click="refreshAll">
        刷新
      </button>
    </header>

    <div v-if="error" class="kellai-inbox__error" role="alert">{{ error }}</div>

    <div v-if="binding.state !== 'connected'" class="kellai-inbox__connect">
      <div class="kellai-inbox__connect-copy">
        <h3>{{ binding.state === 'pending' ? '等待客来来确认授权' : '连接客来来客户 IM' }}</h3>
        <p>
          授权只包含客户档案和会话的只读范围。XCMAX 不接收企微服务商密钥，也不会把客户原始消息上传到平台管理端。
        </p>
        <ul v-if="binding.available_scopes?.length">
          <li v-for="scope in binding.available_scopes" :key="scope.id">
            <strong>{{ scope.label }}</strong>
            <span>{{ scope.description }}</span>
          </li>
        </ul>
      </div>
      <div class="kellai-inbox__connect-actions">
        <button type="button" class="kellai-inbox__button is-primary" :disabled="busy" @click="startBinding">
          {{ busy ? '正在处理…' : binding.state === 'pending' ? '重新打开授权页' : '绑定客来来' }}
        </button>
        <button type="button" class="kellai-inbox__button" :disabled="busy" @click="handleOpenKellai">
          打开客来来
        </button>
      </div>
    </div>

    <template v-else>
      <div class="kellai-inbox__summary">
        <span>{{ dataStatus?.customer_count || customers.length }} 位客户</span>
        <span>{{ dataStatus?.unread_message_count || 0 }} 条未读</span>
        <span>{{ binding.connection?.authorized_scopes?.length || 0 }} 项只读权限</span>
        <span v-if="binding.connection?.authorized_by?.display_name">
          由 {{ binding.connection.authorized_by.display_name }} 授权
        </span>
        <button type="button" class="kellai-inbox__link" :disabled="busy" @click="disconnect">
          解除绑定
        </button>
      </div>

      <div class="kellai-inbox__workspace">
        <aside class="kellai-inbox__customers" aria-label="客来来客户列表">
          <div v-if="customersLoading" class="kellai-inbox__empty">正在读取客户…</div>
          <template v-else>
            <button
              v-for="customer in customers"
              :key="customer.customer_id"
              type="button"
              :class="['kellai-inbox__customer', { active: customer.customer_id === activeCustomerId }]"
              @click="selectCustomer(customer)"
            >
              <span class="kellai-inbox__customer-avatar" aria-hidden="true">{{ avatarText(customer.display_name) }}</span>
              <span class="kellai-inbox__customer-main">
                <strong>{{ customer.display_name }}</strong>
                <small>{{ customer.stage_label || customer.stage || channelLabel(customer.channel_sources) }}</small>
                <em>{{ customer.last_message_preview || '暂无消息摘要' }}</em>
              </span>
            </button>
          </template>
          <div v-if="!customersLoading && !customers.length" class="kellai-inbox__empty">
            暂无已授权的真实客户会话
          </div>
        </aside>

        <main class="kellai-inbox__conversation">
          <header v-if="activeCustomer" class="kellai-inbox__conversation-head">
            <div>
              <h3>{{ activeCustomer.display_name }}</h3>
              <p>
                {{ activeCustomer.stage_label || activeCustomer.stage || '未分阶段' }}
                <template v-if="activeCustomer.channel_sources?.length">
                  · {{ channelLabel(activeCustomer.channel_sources) }}
                </template>
              </p>
            </div>
            <span class="kellai-inbox__readonly">只读</span>
          </header>

          <div v-if="messagesLoading" class="kellai-inbox__empty is-center">正在读取会话…</div>
          <div v-else-if="activeCustomer && orderedMessages.length" class="kellai-inbox__messages">
            <article
              v-for="message in orderedMessages"
              :key="message.id"
              :class="['kellai-inbox__message-row', message.direction === 'outbound' ? 'mine' : 'theirs']"
            >
              <div class="kellai-inbox__message">
                <span>{{ message.direction === 'outbound' ? '我方' : message.contact_name || activeCustomer.display_name }}</span>
                <img
                  v-if="messageImageSrc(message)"
                  class="kellai-inbox__message-image"
                  :src="messageImageSrc(message)"
                  :alt="message.content || '客户图片'"
                  loading="lazy"
                  referrerpolicy="no-referrer"
                />
                <p v-else-if="isImagePlaceholder(message.content)" class="kellai-inbox__image-fallback">
                  [图片]（暂无预览地址）
                </p>
                <p v-else>{{ message.content }}</p>
                <footer>
                  <small>{{ message.channel_type || '客户渠道' }}</small>
                  <time>{{ formatTime(message.created_at) }}</time>
                </footer>
                <div v-if="message.ai_intent || message.next_action" class="kellai-inbox__ai-note">
                  <span v-if="message.ai_intent">意图：{{ message.ai_intent }}</span>
                  <span v-if="message.next_action">建议：{{ message.next_action }}</span>
                </div>
              </div>
            </article>
          </div>
          <div v-else class="kellai-inbox__empty is-center">
            {{ activeCustomer ? '该客户暂无可读取的会话' : '从左侧选择客户查看会话' }}
          </div>

          <section v-if="activeCustomer" class="kellai-inbox__copilot" aria-label="客户沟通 AI 副驾驶">
            <header class="kellai-inbox__copilot-head">
              <div>
                <strong>AI 沟通副驾驶</strong>
                <span>生成时会把最近会话交给当前已配置的 AI 模型；结果必须人工批准。</span>
              </div>
              <button
                type="button"
                class="kellai-inbox__button is-primary"
                :disabled="copilotBusy || !orderedMessages.length"
                @click="generateCopilotDraft"
              >
                {{ copilotBusy ? 'AI 分析中…' : copilotDraft ? '重新生成' : '生成摘要与草稿' }}
              </button>
            </header>

            <div v-if="copilotDraft" class="kellai-inbox__copilot-result">
              <div class="kellai-inbox__copilot-meta">
                <span :class="['is-risk', `is-${copilotDraft.risk_level}`]">
                  {{ riskLabel(copilotDraft.risk_level) }}
                </span>
                <span>{{ draftStatusLabel(copilotDraft.status) }}</span>
                <span v-if="copilotDraft.intent">意图：{{ copilotDraft.intent }}</span>
              </div>
              <p><strong>摘要：</strong>{{ copilotDraft.summary }}</p>
              <p v-if="copilotDraft.next_action"><strong>建议：</strong>{{ copilotDraft.next_action }}</p>
              <div v-if="copilotDraft.next_action && copilotDraft.status !== 'rejected'" class="kellai-inbox__task-proposal">
                <div>
                  <strong>低风险内部动作</strong>
                  <span>创建本地跟进任务，不会写回客来来，也不会联系客户。</span>
                </div>
                <span v-if="currentDraftTask" class="kellai-inbox__task-created">
                  已创建 · {{ taskStatusLabel(currentDraftTask.status) }}
                </span>
                <button
                  v-else
                  type="button"
                  class="kellai-inbox__button"
                  :disabled="taskBusy"
                  @click="createFollowUpTask"
                >
                  {{ taskBusy ? '创建中…' : '批准并创建跟进任务' }}
                </button>
              </div>
              <div class="kellai-inbox__draft-copy">
                <strong>回复草稿</strong>
                <p>{{ copilotDraft.reply_draft }}</p>
              </div>
              <div v-if="copilotDraft.status === 'pending_approval'" class="kellai-inbox__copilot-actions">
                <button type="button" class="kellai-inbox__button is-primary" :disabled="copilotBusy" @click="decideCopilotDraft('approve')">
                  批准为手动发送草稿
                </button>
                <button type="button" class="kellai-inbox__button" :disabled="copilotBusy" @click="decideCopilotDraft('reject')">
                  拒绝草稿
                </button>
              </div>
              <div v-else-if="copilotDraft.status === 'approved_for_manual_send'" class="kellai-inbox__copilot-actions">
                <span class="kellai-inbox__approved">已人工批准；系统仍不会自动发送。</span>
                <button type="button" class="kellai-inbox__button" @click="copyApprovedDraft">
                  {{ copiedDraft ? '已复制' : '复制草稿' }}
                </button>
              </div>
              <div v-else-if="copilotDraft.status === 'rejected'" class="kellai-inbox__rejected">
                此草稿已拒绝，不可用于发送。
              </div>
            </div>
            <p v-else-if="!orderedMessages.length" class="kellai-inbox__copilot-placeholder">
              有真实会话后才能生成 AI 摘要与回复草稿。
            </p>

            <div v-if="followUpTasks.length" class="kellai-inbox__task-list" aria-label="客户跟进任务">
              <div class="kellai-inbox__task-list-head">
                <strong>客户跟进任务</strong>
                <span v-if="followUpMetrics">
                  待跟进 {{ followUpMetrics.open }} · 有效 {{ followUpMetrics.outcomes.success }} ·
                  成功率 {{ formatRate(followUpMetrics.success_rate) }}
                </span>
              </div>
              <article v-for="task in followUpTasks" :key="task.task_id" class="kellai-inbox__task-item">
                <div>
                  <span :class="['is-priority', `is-${task.priority}`]">{{ priorityLabel(task.priority) }}</span>
                  <strong>{{ task.title }}</strong>
                  <span>{{ taskStatusLabel(task.status) }}</span>
                  <span v-if="task.outcome_result">结果：{{ outcomeLabel(task.outcome_result) }}</span>
                </div>
                <p>{{ task.description }}</p>
                <footer>
                  <time>截止：{{ formatTime(task.due_at) }}</time>
                  <div v-if="task.status === 'open'" class="kellai-inbox__task-actions">
                    <button type="button" class="kellai-inbox__button is-primary" :disabled="taskBusy" @click="decideFollowUpTask(task, 'complete', 'success')">
                      完成 · 有效
                    </button>
                    <button type="button" class="kellai-inbox__button" :disabled="taskBusy" @click="decideFollowUpTask(task, 'complete', 'no_result')">
                      完成 · 暂无结果
                    </button>
                    <button type="button" class="kellai-inbox__button" :disabled="taskBusy" @click="decideFollowUpTask(task, 'complete', 'failed')">
                      执行失败
                    </button>
                    <button type="button" class="kellai-inbox__button" :disabled="taskBusy" @click="decideFollowUpTask(task, 'cancel', '')">
                      取消任务
                    </button>
                  </div>
                </footer>
              </article>
            </div>
          </section>

          <footer class="kellai-inbox__guardrail">
            <i class="fa fa-shield" aria-hidden="true"></i>
            AI 仅能在人工批准后创建本地跟进任务；不能自动向客户发送消息或写回外部系统。
          </footer>
        </main>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import kellaiBindingApi, {
  type KellaiBindingStatus,
  type KellaiCopilotDraft,
  type KellaiConversationMessage,
  type KellaiCustomer,
  type KellaiDataStatus,
  type KellaiFollowUpTask,
  type KellaiFollowUpMetrics,
} from '@/api/kellaiBinding'
import {
  isKellaiImagePlaceholder,
  resolveKellaiMessageImageSrc,
} from '@/utils/kellaiMessageMedia'

const binding = ref<KellaiBindingStatus>({ state: 'not_connected' })
const dataStatus = ref<KellaiDataStatus | null>(null)
const customers = ref<KellaiCustomer[]>([])
const messages = ref<KellaiConversationMessage[]>([])
const activeCustomerId = ref<number | null>(null)
const copilotDraft = ref<KellaiCopilotDraft | null>(null)
const followUpTasks = ref<KellaiFollowUpTask[]>([])
const followUpMetrics = ref<KellaiFollowUpMetrics | null>(null)
const busy = ref(false)
const copilotBusy = ref(false)
const taskBusy = ref(false)
const copiedDraft = ref(false)
const customersLoading = ref(false)
const messagesLoading = ref(false)
const error = ref('')
let statusTimer: ReturnType<typeof setInterval> | null = null

const statusLabel = computed(() => {
  if (binding.value.state === 'connected') return '已连接'
  if (binding.value.state === 'pending') return '等待授权'
  if (binding.value.state === 'offline') return '客来来未运行'
  return '未连接'
})

const activeCustomer = computed(() =>
  customers.value.find((customer) => customer.customer_id === activeCustomerId.value) || null,
)

const orderedMessages = computed(() =>
  [...messages.value].sort((left, right) =>
    String(left.created_at || '').localeCompare(String(right.created_at || '')),
  ),
)

const currentDraftTask = computed(() => {
  const draftId = copilotDraft.value?.draft_id
  if (!draftId) return null
  return followUpTasks.value.find((task) => task.source_draft_id === draftId) || null
})

function avatarText(name: string): string {
  const value = String(name || '').trim()
  return value ? value.slice(0, 1).toUpperCase() : '客'
}

function channelLabel(channels?: string[]): string {
  if (!channels?.length) return '客户渠道'
  const labels: Record<string, string> = {
    wecom: '企业微信',
    wechat: '微信',
    douyin: '抖音',
    pdd: '拼多多',
    jd: '京东',
    whatsapp: 'WhatsApp',
  }
  return channels.map((channel) => labels[channel] || channel).join('、')
}

function formatTime(value?: string): string {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function messageImageSrc(message: KellaiConversationMessage): string {
  return resolveKellaiMessageImageSrc(message)
}

function isImagePlaceholder(content?: string): boolean {
  return isKellaiImagePlaceholder(String(content || ''))
}

function riskLabel(value: string): string {
  const labels: Record<string, string> = {
    low: '低风险',
    medium: '中风险',
    high: '高风险',
    critical: '关键风险',
  }
  return labels[value] || '待核验风险'
}

function draftStatusLabel(value: string): string {
  if (value === 'approved_for_manual_send') return '已批准 · 仅手动发送'
  if (value === 'rejected') return '已拒绝'
  return '等待人工批准'
}

function taskStatusLabel(value: string): string {
  if (value === 'completed') return '已完成'
  if (value === 'failed') return '执行失败'
  if (value === 'cancelled') return '已取消'
  return '待跟进'
}

function outcomeLabel(value: string): string {
  if (value === 'success') return '有效'
  if (value === 'no_result') return '暂无结果'
  if (value === 'failed') return '失败'
  return '未记录'
}

function formatRate(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return `${Math.round(value * 100)}%`
}

function priorityLabel(value: string): string {
  if (value === 'urgent') return '紧急'
  if (value === 'high') return '高优先级'
  return '普通'
}

async function openKellai(): Promise<void> {
  const desktop = (window as Window & {
    xcagiDesktop?: { openKellaiDesktop?: () => Promise<{ ok?: boolean; reason?: string }> }
  }).xcagiDesktop
  if (desktop?.openKellaiDesktop) {
    const result = await desktop.openKellaiDesktop()
    if (!result?.ok) throw new Error(result?.reason || '无法打开客来来桌面端')
    return
  }
  const opened = window.open('kellai://settings?tab=xcmax', '_blank', 'noopener,noreferrer')
  if (!opened) throw new Error('请使用 XCMAX 桌面端打开客来来')
}

async function handleOpenKellai(): Promise<void> {
  error.value = ''
  try {
    await openKellai()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法打开客来来桌面端'
  }
}

async function loadCustomers(): Promise<void> {
  customersLoading.value = true
  try {
    customers.value = await kellaiBindingApi.customers(50)
    const stillExists = customers.value.some((customer) => customer.customer_id === activeCustomerId.value)
    if (!stillExists) activeCustomerId.value = customers.value[0]?.customer_id || null
    if (activeCustomerId.value) await loadMessages(activeCustomerId.value)
    else {
      messages.value = []
      copilotDraft.value = null
      followUpTasks.value = []
      followUpMetrics.value = null
    }
  } finally {
    customersLoading.value = false
  }
}

async function loadMessages(customerId: number): Promise<void> {
  messagesLoading.value = true
  try {
    const [nextMessages, nextDraft, nextTaskOverview] = await Promise.all([
      kellaiBindingApi.conversations(customerId, 100),
      kellaiBindingApi.latestDraft(customerId),
      kellaiBindingApi.followUpOverview(customerId),
    ])
    messages.value = nextMessages
    copilotDraft.value = nextDraft
    followUpTasks.value = nextTaskOverview.tasks || []
    followUpMetrics.value = nextTaskOverview.metrics
    copiedDraft.value = false
  } finally {
    messagesLoading.value = false
  }
}

function upsertFollowUpTask(task: KellaiFollowUpTask): void {
  const index = followUpTasks.value.findIndex((item) => item.task_id === task.task_id)
  if (index >= 0) followUpTasks.value.splice(index, 1, task)
  else followUpTasks.value.unshift(task)
  followUpMetrics.value = calculateFollowUpMetrics(followUpTasks.value)
}

function calculateFollowUpMetrics(tasks: KellaiFollowUpTask[]): KellaiFollowUpMetrics {
  const success = tasks.filter((task) => task.outcome_result === 'success').length
  const noResult = tasks.filter((task) => task.outcome_result === 'no_result').length
  const failedOutcomes = tasks.filter((task) => task.outcome_result === 'failed').length
  const evaluated = success + noResult + failedOutcomes
  return {
    total: tasks.length,
    open: tasks.filter((task) => task.status === 'open').length,
    completed: tasks.filter((task) => task.status === 'completed').length,
    failed: tasks.filter((task) => task.status === 'failed').length,
    cancelled: tasks.filter((task) => task.status === 'cancelled').length,
    outcomes: { success, no_result: noResult, failed: failedOutcomes },
    success_rate: evaluated ? success / evaluated : null,
  }
}

async function createFollowUpTask(): Promise<void> {
  if (!copilotDraft.value?.draft_id || currentDraftTask.value) return
  taskBusy.value = true
  error.value = ''
  try {
    const task = await kellaiBindingApi.createFollowUpTask(copilotDraft.value.draft_id)
    upsertFollowUpTask(task)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '跟进任务创建失败'
  } finally {
    taskBusy.value = false
  }
}

async function decideFollowUpTask(
  task: KellaiFollowUpTask,
  decision: 'complete' | 'cancel',
  outcomeResult: 'success' | 'no_result' | 'failed' | '',
): Promise<void> {
  taskBusy.value = true
  error.value = ''
  try {
    const updated = await kellaiBindingApi.decideFollowUpTask(
      task.task_id,
      decision,
      outcomeResult,
    )
    upsertFollowUpTask(updated)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '跟进任务更新失败'
  } finally {
    taskBusy.value = false
  }
}

async function generateCopilotDraft(): Promise<void> {
  if (!activeCustomerId.value || !messages.value.length) return
  copilotBusy.value = true
  copiedDraft.value = false
  error.value = ''
  try {
    copilotDraft.value = await kellaiBindingApi.generateDraft(activeCustomerId.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'AI 摘要与回复草稿生成失败'
  } finally {
    copilotBusy.value = false
  }
}

async function decideCopilotDraft(decision: 'approve' | 'reject'): Promise<void> {
  if (!copilotDraft.value?.draft_id) return
  copilotBusy.value = true
  error.value = ''
  try {
    copilotDraft.value = await kellaiBindingApi.decideDraft(copilotDraft.value.draft_id, decision)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '草稿审批失败'
  } finally {
    copilotBusy.value = false
  }
}

async function copyApprovedDraft(): Promise<void> {
  if (!copilotDraft.value?.reply_draft || copilotDraft.value.status !== 'approved_for_manual_send') return
  try {
    await navigator.clipboard.writeText(copilotDraft.value.reply_draft)
    copiedDraft.value = true
  } catch {
    error.value = '无法复制草稿，请手动选择文本复制'
  }
}

async function refreshAll(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    binding.value = await kellaiBindingApi.status()
    if (binding.value.state === 'connected') {
      const [nextStatus] = await Promise.all([
        kellaiBindingApi.dataStatus(),
        loadCustomers(),
      ])
      dataStatus.value = nextStatus
    } else {
      dataStatus.value = null
      customers.value = []
      messages.value = []
      copilotDraft.value = null
      followUpTasks.value = []
      followUpMetrics.value = null
      activeCustomerId.value = null
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取客来来客户会话'
  } finally {
    busy.value = false
  }
}

async function selectCustomer(customer: KellaiCustomer): Promise<void> {
  if (activeCustomerId.value === customer.customer_id && messages.value.length) return
  activeCustomerId.value = customer.customer_id
  error.value = ''
  try {
    await loadMessages(customer.customer_id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取客户会话'
  }
}

async function startBinding(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await kellaiBindingApi.start()
    await openKellai()
    binding.value = await kellaiBindingApi.status()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法发起客来来授权'
  } finally {
    busy.value = false
  }
}

async function disconnect(): Promise<void> {
  if (!window.confirm('解除后，XCMAX 将立即停止读取客来来，并清除本地生成的客户摘要与跟进任务。')) return
  busy.value = true
  error.value = ''
  try {
    await kellaiBindingApi.disconnect()
    await refreshAll()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '解除绑定失败'
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  void refreshAll()
  statusTimer = setInterval(() => {
    if (binding.value.state === 'pending') void refreshAll()
  }, 4000)
})

onBeforeUnmount(() => {
  if (statusTimer) clearInterval(statusTimer)
  statusTimer = null
})
</script>

<style scoped>
.kellai-inbox { display: flex; flex: 1; min-height: 0; flex-direction: column; background: #f7f9fc; }
.kellai-inbox__head { display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-bottom: 1px solid #e6e9ef; background: #fff; }
.kellai-inbox__avatar, .kellai-inbox__customer-avatar { display: inline-flex; flex: none; align-items: center; justify-content: center; border-radius: 10px; background: #e6f6f2; color: #0f766e; font-weight: 700; }
.kellai-inbox__avatar { width: 32px; height: 32px; }
.kellai-inbox__heading { min-width: 0; flex: 1; }
.kellai-inbox__heading h2, .kellai-inbox__conversation-head h3 { margin: 0; color: #1f2329; font-size: 15px; }
.kellai-inbox__heading p, .kellai-inbox__conversation-head p { margin: 3px 0 0; color: #86909c; font-size: 12px; }
.kellai-inbox__status, .kellai-inbox__readonly { padding: 3px 8px; border-radius: 999px; background: #f2f3f5; color: #667085; font-size: 12px; }
.kellai-inbox__status.is-connected { background: #e8f7ee; color: #14823d; }
.kellai-inbox__status.is-pending { background: #fff7e8; color: #ad6800; }
.kellai-inbox__button { padding: 7px 12px; border: 1px solid #d9dfe8; border-radius: 7px; background: #fff; color: #344054; cursor: pointer; }
.kellai-inbox__button.is-primary { border-color: #0052d9; background: #0052d9; color: #fff; }
.kellai-inbox__button.is-quiet { padding: 5px 10px; }
.kellai-inbox__button:disabled, .kellai-inbox__link:disabled { cursor: not-allowed; opacity: .55; }
.kellai-inbox__error { margin: 12px 18px 0; padding: 10px 12px; border-radius: 7px; background: #fff1f0; color: #b42318; font-size: 13px; }
.kellai-inbox__connect { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; margin: auto; width: min(760px, calc(100% - 36px)); padding: 28px; border: 1px solid #e6e9ef; border-radius: 12px; background: #fff; }
.kellai-inbox__connect h3 { margin: 0 0 8px; color: #1f2329; }
.kellai-inbox__connect p { margin: 0; color: #667085; line-height: 1.65; }
.kellai-inbox__connect ul { display: grid; gap: 8px; margin: 18px 0 0; padding: 0; list-style: none; }
.kellai-inbox__connect li { display: grid; gap: 2px; padding: 10px 12px; border-radius: 8px; background: #f7f9fc; }
.kellai-inbox__connect li span { color: #667085; font-size: 12px; }
.kellai-inbox__connect-actions { display: flex; align-items: flex-start; gap: 8px; flex-direction: column; }
.kellai-inbox__summary { display: flex; flex-wrap: wrap; gap: 8px; padding: 9px 18px; border-bottom: 1px solid #e6e9ef; background: #fff; color: #667085; font-size: 12px; }
.kellai-inbox__summary > span { padding: 3px 8px; border-radius: 999px; background: #f2f4f7; }
.kellai-inbox__link { margin-left: auto; border: 0; background: none; color: #b42318; cursor: pointer; }
.kellai-inbox__workspace { display: grid; grid-template-columns: minmax(220px, 30%) minmax(0, 1fr); flex: 1; min-height: 0; }
.kellai-inbox__customers { min-height: 0; overflow-y: auto; border-right: 1px solid #e6e9ef; background: #fff; }
.kellai-inbox__customer { display: flex; width: 100%; gap: 10px; padding: 12px 14px; border: 0; border-bottom: 1px solid #f0f2f5; background: #fff; text-align: left; cursor: pointer; }
.kellai-inbox__customer:hover, .kellai-inbox__customer.active { background: #eef5ff; }
.kellai-inbox__customer-avatar { width: 36px; height: 36px; }
.kellai-inbox__customer-main { display: grid; min-width: 0; flex: 1; gap: 2px; }
.kellai-inbox__customer-main strong { color: #1f2329; font-size: 14px; }
.kellai-inbox__customer-main small { color: #667085; }
.kellai-inbox__customer-main em { overflow: hidden; color: #86909c; font-size: 12px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.kellai-inbox__conversation { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
.kellai-inbox__conversation-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid #e6e9ef; background: #fff; }
.kellai-inbox__readonly { background: #e8f7ee; color: #14823d; }
.kellai-inbox__messages { flex: 1; min-height: 0; overflow-y: auto; padding: 18px; }
.kellai-inbox__message-row { display: flex; margin-bottom: 12px; }
.kellai-inbox__message-row.mine { justify-content: flex-end; }
.kellai-inbox__message { max-width: min(72%, 620px); padding: 10px 12px; border: 1px solid #e6e9ef; border-radius: 10px; background: #fff; }
.kellai-inbox__message-row.mine .kellai-inbox__message { border-color: #cfe1ff; background: #eaf2ff; }
.kellai-inbox__message > span { color: #667085; font-size: 11px; }
.kellai-inbox__message-image { display: block; margin: 6px 0; max-width: min(100%, 320px); max-height: 360px; border-radius: 8px; object-fit: contain; background: #f2f4f7; }
.kellai-inbox__image-fallback { margin: 5px 0; color: #667085; font-size: 13px; }
.kellai-inbox__message p { margin: 5px 0; color: #1f2329; line-height: 1.55; white-space: pre-wrap; }
.kellai-inbox__message footer { display: flex; justify-content: space-between; gap: 16px; color: #98a2b3; font-size: 11px; }
.kellai-inbox__ai-note { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding-top: 7px; border-top: 1px dashed #d9dfe8; color: #475467; font-size: 11px; }
.kellai-inbox__copilot { max-height: 44%; overflow-y: auto; padding: 12px 18px; border-top: 1px solid #dce6f5; background: #f8fbff; }
.kellai-inbox__copilot-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.kellai-inbox__copilot-head > div { display: grid; gap: 3px; }
.kellai-inbox__copilot-head strong { color: #1f2329; font-size: 13px; }
.kellai-inbox__copilot-head span, .kellai-inbox__copilot-placeholder { color: #667085; font-size: 12px; }
.kellai-inbox__copilot-result { display: grid; gap: 8px; margin-top: 10px; }
.kellai-inbox__copilot-result > p { margin: 0; color: #344054; font-size: 12px; line-height: 1.6; }
.kellai-inbox__copilot-meta { display: flex; flex-wrap: wrap; gap: 6px; color: #667085; font-size: 11px; }
.kellai-inbox__copilot-meta > span { padding: 3px 7px; border-radius: 999px; background: #eef2f7; }
.kellai-inbox__copilot-meta .is-risk.is-low { background: #e8f7ee; color: #14823d; }
.kellai-inbox__copilot-meta .is-risk.is-medium { background: #fff7e8; color: #ad6800; }
.kellai-inbox__copilot-meta .is-risk.is-high,
.kellai-inbox__copilot-meta .is-risk.is-critical { background: #fff1f0; color: #b42318; }
.kellai-inbox__task-proposal { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 11px; border: 1px solid #cfe1ff; border-radius: 8px; background: #eef5ff; }
.kellai-inbox__task-proposal > div { display: grid; gap: 2px; }
.kellai-inbox__task-proposal strong { color: #1f2329; font-size: 12px; }
.kellai-inbox__task-proposal span { color: #667085; font-size: 11px; }
.kellai-inbox__task-created { color: #14823d !important; white-space: nowrap; }
.kellai-inbox__draft-copy { padding: 10px 12px; border: 1px solid #dce6f5; border-radius: 8px; background: #fff; }
.kellai-inbox__draft-copy > strong { color: #344054; font-size: 12px; }
.kellai-inbox__draft-copy > p { margin: 6px 0 0; color: #1f2329; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.kellai-inbox__copilot-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.kellai-inbox__approved { color: #14823d; font-size: 12px; }
.kellai-inbox__rejected { color: #b42318; font-size: 12px; }
.kellai-inbox__copilot-placeholder { margin: 10px 0 0; }
.kellai-inbox__task-list { display: grid; gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px solid #dce6f5; }
.kellai-inbox__task-list-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.kellai-inbox__task-list-head strong { color: #1f2329; font-size: 13px; }
.kellai-inbox__task-list-head span { color: #667085; font-size: 11px; }
.kellai-inbox__task-item { display: grid; gap: 7px; padding: 10px 12px; border: 1px solid #dce6f5; border-radius: 8px; background: #fff; }
.kellai-inbox__task-item > div { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; color: #667085; font-size: 11px; }
.kellai-inbox__task-item > div strong { color: #1f2329; font-size: 12px; }
.kellai-inbox__task-item > p { margin: 0; color: #475467; font-size: 12px; line-height: 1.55; }
.kellai-inbox__task-item > footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #86909c; font-size: 11px; }
.kellai-inbox__task-actions { display: flex; gap: 6px; }
.kellai-inbox__task-actions .kellai-inbox__button { padding: 4px 8px; font-size: 11px; }
.kellai-inbox__task-item .is-priority { padding: 2px 6px; border-radius: 999px; background: #f2f4f7; }
.kellai-inbox__task-item .is-priority.is-high { background: #fff7e8; color: #ad6800; }
.kellai-inbox__task-item .is-priority.is-urgent { background: #fff1f0; color: #b42318; }
.kellai-inbox__guardrail { display: flex; align-items: center; gap: 8px; padding: 10px 18px; border-top: 1px solid #e6e9ef; background: #fff; color: #667085; font-size: 12px; }
.kellai-inbox__guardrail .fa { color: #14823d; }
.kellai-inbox__empty { padding: 24px 14px; color: #86909c; font-size: 13px; text-align: center; }
.kellai-inbox__empty.is-center { display: grid; flex: 1; place-items: center; }

@media (max-width: 760px) {
  .kellai-inbox__head { align-items: flex-start; flex-wrap: wrap; }
  .kellai-inbox__status { margin-left: 42px; }
  .kellai-inbox__connect { grid-template-columns: 1fr; }
  .kellai-inbox__connect-actions { align-items: stretch; }
  .kellai-inbox__workspace { grid-template-columns: 1fr; }
  .kellai-inbox__customers { max-height: 230px; border-right: 0; border-bottom: 1px solid #e6e9ef; }
  .kellai-inbox__message { max-width: 88%; }
  .kellai-inbox__task-proposal, .kellai-inbox__task-item > footer { align-items: stretch; flex-direction: column; }
}
</style>
