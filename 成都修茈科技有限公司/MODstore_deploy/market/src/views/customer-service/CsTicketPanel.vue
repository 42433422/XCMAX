<script setup lang="ts">
/**
 * AI 客服 · 侧栏「我的工单」面板。
 *
 * 由 CustomerServiceView.vue 模板块机械切分而来（行为与视觉保持不变）：
 * 纯展示辅助函数直接复用 utils / customerServiceHelpers，交互经 emit 回到入口。
 */
import {
  issueDomainLabel,
  shortTicketRef,
  ticketLifecycleHint,
  ticketLifecycleLabel,
  ticketLifecycleSteps,
} from '../../utils/csTicketLifecycle'
import { friendlyTicketTitle, shortLifeLabel } from './customerServiceHelpers'
import type { CustomerTicket } from './customerServiceTypes'

defineProps<{
  tickets: CustomerTicket[]
  expandedIds: Set<number>
  allTicketsExpanded: boolean
}>()

defineEmits<{
  (e: 'toggle-all'): void
  (e: 'refresh'): void
  (e: 'open', ticket: CustomerTicket): void
  (e: 'toggle', id: number | string): void
}>()
</script>

<template>
  <aside class="cs-side">
    <section class="cs-side-card cs-side-card--tickets">
      <div class="cs-side-card__head">
        <h3>
          我的工单 <small v-if="tickets.length">{{ tickets.length }}</small>
        </h3>
        <div class="cs-side-card__actions">
          <button v-if="tickets.length" type="button" class="cs-link" @click="$emit('toggle-all')">
            {{ allTicketsExpanded ? '全部收起' : '全部展开' }}
          </button>
          <button type="button" class="cs-link" @click="$emit('refresh')">刷新</button>
        </div>
      </div>
      <p class="cs-side-lead">默认收起；点箭头看进度，点标题在对话里继续</p>
      <div v-if="tickets.length === 0" class="cs-side-empty">
        还没有工单。普通聊天不会建单；材料齐可自动受理，或点「提交工单」后会出现在这里。
      </div>
      <div v-else class="cs-side-list">
        <article v-for="ticket in tickets" :key="ticket.id" :class="['cs-ticket', { 'cs-ticket--open': expandedIds.has(Number(ticket.id)) }]">
          <div class="cs-ticket__row">
            <button type="button" class="cs-ticket__main" @click="$emit('open', ticket)">
              <b>{{ friendlyTicketTitle(ticket) }}</b>
              <span v-if="issueDomainLabel(ticket)" class="cs-ticket__domain">{{ issueDomainLabel(ticket) }}</span>
              <span class="cs-ticket__stage">{{ ticketLifecycleLabel(ticket) }}</span>
            </button>
            <button
              type="button"
              class="cs-ticket__toggle"
              :aria-expanded="expandedIds.has(Number(ticket.id))"
              :aria-label="expandedIds.has(Number(ticket.id)) ? '收起进度' : '展开进度'"
              @click.stop="$emit('toggle', ticket.id)"
            >
              {{ expandedIds.has(Number(ticket.id)) ? '▴' : '▾' }}
            </button>
          </div>
          <div v-if="expandedIds.has(Number(ticket.id))" class="cs-ticket__body">
            <span class="cs-ticket__meta">{{ shortTicketRef(ticket) }}</span>
            <p class="cs-ticket__hint">{{ ticketLifecycleHint(ticket) }}</p>
            <ol class="cs-life" aria-label="工单进度">
              <li
                v-for="step in ticketLifecycleSteps(ticket)"
                :key="step.stage"
                :class="['cs-life__item', `cs-life__item--${step.state}`]"
                :title="step.label"
              >
                <i class="cs-life__dot" />
                <em>{{ shortLifeLabel(step.label) }}</em>
              </li>
            </ol>
          </div>
        </article>
      </div>
    </section>
  </aside>
</template>

<style scoped src="./customer-service.css"></style>
