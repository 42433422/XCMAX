<template>
  <section class="list-view" aria-label="长期记忆">
    <div class="list-view__head">
      <div>
        <span class="section-kicker">Governed Memory</span>
        <h3>长期记忆</h3>
      </div>
      <div class="memory-summary" aria-label="记忆状态">
        <span
          ><strong>{{ activeCount }}</strong> 已确认</span
        >
        <span :class="{ attention: pendingCount }">
          <strong>{{ pendingCount }}</strong> 待确认
        </span>
      </div>
    </div>
    <div v-if="loading" class="view-loading" role="status">
      <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
      正在读取记忆
    </div>
    <div v-else-if="memories.length" class="memory-list">
      <article
        v-for="memory in memories"
        :key="memory.memory_id"
        class="memory-row"
        :class="[`memory-row--${memory.status}`, { active: selectedMemoryId === memory.memory_id }]"
      >
        <button type="button" class="memory-row__main" @click="emit('select', memory)">
          <span class="memory-row__type">
            <i :class="`fa ${memoryIcon(memory.memory_type)}`" aria-hidden="true"></i>
            {{ memoryTypeLabel(memory.memory_type) }}
          </span>
          <strong>{{ memory.statement }}</strong>
          <span class="memory-row__meta"> {{ memoryScopeLabel(memory.scope) }} · {{ formatDate(memory.updated_at) }} </span>
        </button>
        <div class="memory-strength" :title="`记忆强度 ${strengthText(memory.strength)}`">
          <span><i :style="{ width: strengthText(memory.strength) }"></i></span>
          <strong>{{ strengthText(memory.strength) }}</strong>
        </div>
        <span class="memory-status" :class="`memory-status--${memory.status}`">
          {{ memoryStatusLabel(memory.status) }}
        </span>
        <div v-if="memory.status === 'pending'" class="memory-row__actions">
          <button
            type="button"
            class="memory-action memory-action--confirm"
            title="确认记忆"
            aria-label="确认记忆"
            :disabled="mutating"
            @click="emit('confirm', memory)"
          >
            <i class="fa fa-check" aria-hidden="true"></i>
          </button>
          <button
            type="button"
            class="memory-action"
            title="忽略记忆"
            aria-label="忽略记忆"
            :disabled="mutating"
            @click="emit('reject', memory)"
          >
            <i class="fa fa-times" aria-hidden="true"></i>
          </button>
        </div>
        <i v-else class="fa fa-angle-right memory-row__arrow" aria-hidden="true"></i>
      </article>
    </div>
    <div v-else class="view-empty">
      <i class="fa fa-history" aria-hidden="true"></i>
      <strong>还没有可治理的记忆</strong>
      <span>对话中明确表达的人物、地点、偏好和事实会在这里等待确认</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { PersyMemoryRecord } from '@/api/knowledgeBase'
import {
  formatDate,
  memoryIcon,
  memoryScopeLabel,
  memoryStatusLabel,
  memoryTypeLabel,
  strengthText,
} from '@/composables/persyKnowledgeFormatters'

defineProps<{
  memories: PersyMemoryRecord[]
  loading: boolean
  activeCount: number
  pendingCount: number
  selectedMemoryId: string
  mutating: boolean
}>()

const emit = defineEmits<{
  select: [memory: PersyMemoryRecord]
  confirm: [memory: PersyMemoryRecord]
  reject: [memory: PersyMemoryRecord]
}>()
</script>

<style scoped>
.section-kicker {
  color: #738179;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.list-view {
  height: 100%;
  overflow: auto;
  padding: 24px 24px 96px;
  background: #f7f9f8;
}

.list-view__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.list-view__head h3 {
  margin: 2px 0 0;
  color: #17211d;
  font-size: 17px;
  line-height: 1.25;
}

.memory-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  color: #718078;
  font-size: 11px;
}

.memory-summary span {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}

.memory-summary strong {
  color: #27352f;
  font-size: 15px;
}

.memory-summary .attention,
.memory-summary .attention strong {
  color: #8e3f51;
}

.view-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  color: #718078;
  font-size: 12px;
}

.memory-list {
  border-top: 1px solid #dce4e0;
}

.memory-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 116px 64px 72px;
  align-items: center;
  gap: 14px;
  min-width: 0;
  border-bottom: 1px solid #dce4e0;
  background: transparent;
}

.memory-row:hover,
.memory-row.active {
  background: #eef3f0;
}

.memory-row--pending {
  box-shadow: inset 3px 0 #b45e71;
}

.memory-row__main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 14px 8px 14px 12px;
  border: 0;
  color: #27352f;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.memory-row__main strong {
  max-width: 100%;
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.memory-row__type,
.memory-row__meta {
  color: #748179;
  font-size: 10px;
}

.memory-row__type {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #895063;
  font-weight: 700;
}

.memory-strength {
  display: grid;
  grid-template-columns: minmax(52px, 1fr) 34px;
  align-items: center;
  gap: 8px;
}

.memory-strength > span {
  height: 5px;
  overflow: hidden;
  border-radius: 3px;
  background: #dce4e0;
}

.memory-strength i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #a85667;
}

.memory-strength strong {
  color: #637169;
  font-size: 10px;
}

.memory-status {
  justify-self: start;
  padding: 4px 7px;
  border-radius: 5px;
  color: #28675d;
  background: #e3f2ec;
  font-size: 10px;
  font-weight: 700;
}

.memory-status--pending {
  color: #8e3f51;
  background: #f8e8ec;
}

.memory-row__actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding-right: 8px;
}

.memory-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid #d2dcd7;
  border-radius: 6px;
  color: #68766f;
  background: #ffffff;
  cursor: pointer;
}

.memory-action--confirm {
  border-color: #8db7a5;
  color: #1d6259;
}

.memory-action:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.memory-row__arrow {
  justify-self: center;
  color: #a0aea7;
}

.view-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  color: #718078;
  text-align: center;
}

.view-empty > i {
  color: #9aaba2;
  font-size: 28px;
}

.view-empty strong {
  color: #27352f;
  font-size: 14px;
}

.view-empty span {
  font-size: 11px;
}

@media (max-width: 767px) {
  .list-view {
    padding: 60px 12px 82px;
  }

  .list-view__head {
    align-items: flex-start;
    flex-direction: column;
  }

  .memory-summary {
    width: 100%;
    justify-content: space-between;
  }

  .memory-row {
    grid-template-columns: minmax(0, 1fr) 62px 64px;
    gap: 7px;
  }

  .memory-strength {
    grid-template-columns: 1fr;
  }

  .memory-strength > strong {
    text-align: right;
  }

  .memory-strength > span {
    display: none;
  }

  .memory-row__actions,
  .memory-row__arrow {
    display: none;
  }
}
</style>
