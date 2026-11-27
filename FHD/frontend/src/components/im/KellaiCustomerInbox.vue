<template>
  <section
    class="kellai-inbox"
    :class="{ 'kellai-inbox--embedded': embedded }"
    :aria-label="embedded ? '客户消息' : undefined"
    :aria-labelledby="embedded ? undefined : 'kellai-inbox-title'"
  >
    <header v-if="!embedded" class="kellai-inbox__head">
      <span class="kellai-inbox__avatar" aria-hidden="true">客</span>
      <div class="kellai-inbox__heading">
        <h2 id="kellai-inbox-title">客户消息 · 客来来</h2>
        <p>客户档案和会话从本机客来来读取；发送需单独授权并人工确认。</p>
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
          <li v-for="scope in binding.available_scopes.filter(item => KELLAI_READ_SCOPES.includes(item.id))" :key="scope.id">
            <strong>{{ scope.label }}</strong>
            <span>{{ scope.description }}</span>
          </li>
        </ul>
      </div>
      <div class="kellai-inbox__connect-actions">
        <button type="button" class="kellai-inbox__button is-primary" :disabled="busy" @click="startBinding()">
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
        <span>{{ binding.connection?.authorized_scopes?.length || 0 }} 项授权权限</span>
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

        <section class="kellai-inbox__conversation" aria-label="客户会话">
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
            <span class="kellai-inbox__readonly">{{ canSend ? '人工确认发送' : '只读' }}</span>
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

          <KellaiMessageComposer v-if="activeCustomer && canSend" />

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
        </section>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { KELLAI_READ_SCOPES, useKellaiStore } from '@/stores/kellai'
import KellaiMessageComposer from './kellaiInbox/KellaiMessageComposer.vue'
import {
  avatarText,
  channelLabel,
  draftStatusLabel,
  formatRate,
  formatTime,
  isImagePlaceholder,
  messageImageSrc,
  outcomeLabel,
  priorityLabel,
  riskLabel,
  taskStatusLabel,
} from './kellaiInbox/kellaiInboxShared'

defineProps<{ embedded?: boolean }>()
const store = useKellaiStore()
const {
  binding, dataStatus, customers, activeCustomerId, busy, customersLoading, messagesLoading,
  error, copilotDraft, followUpTasks, followUpMetrics, copilotBusy, taskBusy, copiedDraft,
  currentDraftTask, statusLabel, activeCustomer, orderedMessages, canSend,
} = storeToRefs(store)
const {
  refreshAll, selectCustomer, startBinding, disconnect, handleOpenKellai,
  createFollowUpTask, decideFollowUpTask, generateCopilotDraft, decideCopilotDraft, copyApprovedDraft,
} = store
onMounted(store.attach)
onBeforeUnmount(store.detach)
</script>

<style scoped src="./KellaiCustomerInbox.css"></style>

<style scoped>
.kellai-inbox--embedded {
  background: transparent;
}

.kellai-inbox--embedded .kellai-inbox__connect {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  width: auto;
  margin: 0;
  padding: 20px clamp(16px, 3vw, 28px);
  border: 0;
  background: transparent;
}

.kellai-inbox--embedded .kellai-inbox__connect-copy {
  flex: 1 1 20rem;
  min-width: 0;
}

.kellai-inbox--embedded .kellai-inbox__connect-actions {
  flex-flow: row wrap;
  align-self: center;
}

.kellai-inbox--embedded .kellai-inbox__connect li {
  padding: 8px 0;
  border-top: 1px solid var(--xc-color-border);
  border-radius: 0;
  background: transparent;
}

.kellai-inbox--embedded :is(.kellai-inbox__button, .kellai-inbox__link, .kellai-inbox__customer):focus-visible {
  outline: 2px solid var(--xc-color-primary);
  outline-offset: -2px;
}
</style>
