<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElTimeline, ElTimelineItem } from 'element-plus/es/components/timeline/index'
import 'element-plus/theme-chalk/el-timeline.css'
import 'element-plus/theme-chalk/el-timeline-item.css'
import {
  xiaocAdminApi,
  type DeliveryFollowup,
  type DeliveryFollowupDetail,
  type DeliveryFollowupEvent,
} from '../../application/xiaocAdminApi'
import { errorMessage } from '../../utils/typeNarrowing'

const props = defineProps<{ ticketId?: number }>()
const items = ref<DeliveryFollowup[]>([])
const detail = ref<DeliveryFollowupDetail | null>(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const dateTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' })

function formatDate(value: string | null) {
  const time = value ? Date.parse(value) : NaN
  return Number.isFinite(time) ? dateTime.format(time) : ''
}

const actionStates: Readonly<Record<string, string>> = {
  pending: '待处理',
  waiting_approval: '待审批',
  pending_execution: '待执行',
  running: '执行中',
  completed: '操作已完成',
  failed: '操作失败',
  rejected: '审批未通过',
  skipped: '已跳过',
}

function eventState(event: DeliveryFollowupEvent) {
  if (event.kind === 'receipt') {
    if (event.status === 'verified') return '已核验'
    return event.status === 'verification_failed' ? '验证失败' : '待核验'
  }
  return event.kind === 'action' ? actionStates[event.status ?? ''] ?? '状态待核实' : ''
}

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await action()
  } catch (failure) {
    error.value = errorMessage(failure, '暂时无法读取交付跟进，请重试。')
  } finally {
    busy.value = false
  }
}

function loadList() {
  detail.value = null
  return run(async () => {
    items.value = (await xiaocAdminApi.listFollowups()).items
  })
}

function applyDetail(next: DeliveryFollowupDetail) {
  detail.value = next
  items.value = items.value.map((item) => item.ticket_id === next.item.ticket_id ? next.item : item)
}

function openDetail(id: number) {
  return run(async () => applyDetail(await xiaocAdminApi.followupDetail(id)))
}

function toggleFollow(item: DeliveryFollowup) {
  return run(async () => applyDetail(await xiaocAdminApi.follow(item.ticket_id, !item.following)))
}

function resume(item: DeliveryFollowup) {
  return run(async () => applyDetail(await xiaocAdminApi.resume(item.ticket_id)))
}

function approve(item: DeliveryFollowup) {
  const { approval_id, approval_title, approval_reason } = item
  if (!approval_id || !approval_title || !approval_reason) return
  if (!window.confirm(`确认通过工单 ${item.ticket_no} 的审批？\n\n${approval_title}\n${approval_reason}`)) return
  return run(async () => {
    applyDetail(await xiaocAdminApi.approve(item.ticket_id, approval_id))
    notice.value = '已记录审批。实际执行进展以工单记录为准。'
  })
}

onMounted(() => props.ticketId === undefined ? loadList() : openDetail(props.ticketId))
</script>

<template>
  <section aria-label="交付跟进" :aria-busy="busy">
    <div class="xiaoc-toolbar">
      <button v-if="detail" type="button" :disabled="busy" @click="loadList">返回列表</button>
      <button type="button" :disabled="busy" @click="detail ? openDetail(detail.item.ticket_id) : loadList()">刷新</button>
      <span v-if="busy" class="xiaoc-muted" role="status">正在处理…</span>
    </div>
    <p v-if="error" class="xiaoc-error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>

    <template v-if="detail">
      <h3 class="followup-title">{{ detail.item.title }}</h3>
      <p class="xiaoc-muted">{{ detail.item.ticket_no }} · {{ detail.item.stage_label }}</p>
      <p v-if="formatDate(detail.item.expected_completion_at)">
        预计完成 {{ formatDate(detail.item.expected_completion_at) }}
      </p>
      <p v-if="detail.item.attention_reason" class="xiaoc-error">{{ detail.item.attention_reason }}</p>
      <div class="xiaoc-toolbar">
        <button v-if="detail.item.can_follow" type="button" :disabled="busy" @click="toggleFollow(detail.item)">
          {{ detail.item.following ? '停止跟进' : '开始跟进' }}
        </button>
        <button
          v-if="detail.item.can_resume"
          type="button"
          :disabled="busy"
          @click="resume(detail.item)"
        >
          继续派发
        </button>
      </div>
      <aside
        v-if="detail.item.approval_id && detail.item.approval_title && detail.item.approval_reason"
        class="followup-approval"
        aria-label="待审批事项"
      >
        <strong>{{ detail.item.approval_title }}</strong>
        <p>{{ detail.item.approval_reason }}</p>
        <button type="button" :disabled="busy" @click="approve(detail.item)">确认审批</button>
      </aside>
      <h4>工单记录</h4>
      <ElTimeline v-if="detail.events.length" class="followup-timeline">
        <ElTimelineItem
          v-for="event in detail.events"
          :key="event.id"
          :timestamp="formatDate(event.at)"
          :hide-timestamp="!formatDate(event.at)"
        >
          {{ event.label }}
          <span v-if="eventState(event)" class="xiaoc-muted"> · {{ eventState(event) }}</span>
        </ElTimelineItem>
      </ElTimeline>
      <p v-else class="xiaoc-muted">还没有工单记录。</p>
    </template>

    <ul v-else-if="items.length" class="followup-list">
      <li v-for="item in items" :key="item.ticket_id">
        <button type="button" :disabled="busy" @click="openDetail(item.ticket_id)">
          <strong>{{ item.title }}</strong>
          <span class="xiaoc-muted">{{ item.ticket_no }} · {{ item.stage_label }}{{ item.following ? ' · 跟进中' : '' }}</span>
          <span v-if="item.needs_attention" class="xiaoc-error">{{ item.attention_reason || '需要处理' }}</span>
        </button>
      </li>
    </ul>
    <p v-else-if="!busy && !error" class="xiaoc-muted">暂无可以跟进的交付工单。</p>
  </section>
</template>

<style scoped>
.followup-title { margin: 10px 0 2px; font-size: .96rem; }
.followup-approval {
  padding: 10px;
  margin: 10px 0;
  border: 1px solid var(--xiaoc-border);
  border-radius: 8px;
}
.followup-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.followup-list button { width: 100%; display: grid; gap: 3px; text-align: left; }
.followup-timeline {
  --el-border-color-light: var(--xiaoc-border);
  --el-text-color-primary: inherit;
  --el-text-color-secondary: var(--xiaoc-muted);
  --el-font-size-small: .75rem;
  --el-font-size-base: .84rem;
}
.followup-timeline.is-start { padding-left: 5px; }
</style>
