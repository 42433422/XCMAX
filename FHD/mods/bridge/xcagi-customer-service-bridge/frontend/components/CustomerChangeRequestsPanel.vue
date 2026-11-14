<template>
  <section v-if="show" class="cs-block cs-change-requests">
    <p class="cs-block-title">客户变更工单（外部客服门户）</p>
    <p class="muted cs-block-hint">
      客户在「外部客服」提交的交付期变更/Bug 会出现在此，可在此更新状态。
    </p>
    <div v-if="loading" class="loading-hint">加载工单…</div>
    <ul v-else-if="changeRequests.length" class="cs-change-request-list">
      <li v-for="cr in changeRequests" :key="cr.id" class="cs-change-request-item">
        <div class="cs-change-request-head">
          <strong>{{ cr.ticket_no }}</strong>
          <span class="req-type-badge type-问题">{{ cr.change_type_label }}</span>
          <span class="req-status" :class="'st-' + cr.status">{{ cr.status_label }}</span>
        </div>
        <p class="cs-change-request-title">{{ cr.title }}</p>
        <p v-if="cr.description" class="muted cs-change-request-desc">{{ cr.description }}</p>
        <div class="cs-block-actions">
          <select
            class="input-xs"
            :value="cr.status"
            @change="$emit('change-status', cr, ($event.target as HTMLSelectElement).value)"
          >
            <option value="pending">待受理</option>
            <option value="acknowledged">已确认</option>
            <option value="in_progress">处理中</option>
            <option value="resolved">已解决</option>
            <option value="rejected">已驳回</option>
          </select>
          <button
            type="button"
            class="btn btn-xs btn-accent"
            :disabled="dispatchingId === cr.id"
            @click="$emit('dispatch-ops', cr)"
          >
            {{ dispatchingId === cr.id ? '派发中…' : '派发运维任务' }}
          </button>
          <span v-if="cr.ops_dispatch_job_id" class="muted cs-ops-job">
            job: {{ cr.ops_dispatch_job_id }}
            <router-link :to="{ name: 'xcmax-admin', query: { tab: 'dispatch' } }">管理员</router-link>
          </span>
          <span v-else-if="cr.ops_dispatch_error" class="cs-stage-warn-hint">{{ cr.ops_dispatch_error }}</span>
        </div>
      </li>
    </ul>
    <p v-else class="empty-hint">暂无客户变更工单</p>
  </section>
</template>

<script setup lang="ts">
export type ChangeRequestRow = {
  id: string
  ticket_no?: string
  change_type_label?: string
  title?: string
  description?: string
  status?: string
  status_label?: string
  ops_dispatch_job_id?: string
  ops_dispatched_at?: string
  ops_dispatch_error?: string
}

defineProps<{
  show: boolean
  changeRequests: ChangeRequestRow[]
  loading: boolean
  dispatchingId: string
}>()

defineEmits<{
  (e: 'change-status', cr: { id: string }, status: string): void
  (e: 'dispatch-ops', cr: { id: string; ticket_no?: string }): void
}>()
</script>