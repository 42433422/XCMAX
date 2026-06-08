<template>
  <aside class="chat-sidebar" :class="{ 'chat-sidebar--open': open }">
    <div class="chat-sidebar__inner">
      <div class="chat-sidebar__head">
        <button type="button" class="chat-sidebar__new" @click="$emit('new')">
          <span class="chat-sidebar__new-plus" aria-hidden="true">+</span>
          <span>新对话</span>
        </button>
        <button type="button" class="chat-sidebar__close" aria-label="收起会话列表" @click="$emit('toggle')">‹</button>
      </div>

      <div class="chat-sidebar__search">
        <input
          v-model="searchKw"
          type="search"
          class="chat-sidebar__search-input"
          placeholder="搜索对话…"
          aria-label="搜索对话"
        />
      </div>

      <div class="chat-sidebar__list" role="list">
        <button
          v-for="c in filtered"
          :key="c.id"
          type="button"
          class="chat-sidebar__item"
          :class="{ 'chat-sidebar__item--active': c.id === activeId }"
          role="listitem"
          @click="$emit('pick', c.id)"
        >
          <div class="chat-sidebar__item-main">
            <div class="chat-sidebar__item-title">
              <span v-if="c.pinned" class="chat-sidebar__pin" aria-label="已置顶">📌</span>
              <span class="chat-sidebar__item-name">{{ c.title || '新对话' }}</span>
            </div>
            <div class="chat-sidebar__item-meta">
              <span>{{ formatTs(c.updatedAt) }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ c.messages.length }} 条</span>
              <span v-if="c.agentLabel" class="chat-sidebar__agent">@{{ c.agentLabel }}</span>
            </div>
          </div>
          <div class="chat-sidebar__item-ops" @click.stop>
            <button
              type="button"
              class="chat-sidebar__op"
              :aria-label="c.pinned ? '取消置顶' : '置顶'"
              :title="c.pinned ? '取消置顶' : '置顶'"
              @click.stop="$emit('pin', c.id)"
            >📌</button>
            <button
              type="button"
              class="chat-sidebar__op"
              aria-label="重命名"
              title="重命名"
              @click.stop="renameItem(c)"
            >✎</button>
            <button
              type="button"
              class="chat-sidebar__op"
              aria-label="导出"
              title="导出 Markdown"
              @click.stop="$emit('export', c.id)"
            >⬇</button>
            <button
              type="button"
              class="chat-sidebar__op chat-sidebar__op--danger"
              aria-label="删除"
              title="删除"
              @click.stop="$emit('remove', c.id)"
            >×</button>
          </div>
        </button>
        <p v-if="!filtered.length" class="chat-sidebar__empty">
          {{ searchKw.trim() ? '没有命中关键词。' : '还没有对话，点上方「新对话」开始。' }}
        </p>
      </div>

      <footer class="chat-sidebar__foot">
        <span class="chat-sidebar__foot-meta">本地保存 · {{ list.length }}/{{ maxConvs }}</span>
        <button
          type="button"
          class="chat-sidebar__foot-clear"
          :disabled="!list.length"
          @click="$emit('clear-all')"
        >清空全部</button>
      </footer>
    </div>
    <button
      v-if="!open"
      type="button"
      class="chat-sidebar__handle"
      aria-label="展开会话列表"
      @click="$emit('toggle')"
    >›</button>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Conversation } from '../../utils/conversationStore'
import { searchConversations } from '../../utils/conversationStore'

const props = defineProps<{
  list: Conversation[]
  activeId: string
  open: boolean
  maxConvs?: number
}>()

const emit = defineEmits<{
  (e: 'new'): void
  (e: 'pick', id: string): void
  (e: 'pin', id: string): void
  (e: 'rename', id: string, title: string): void
  (e: 'export', id: string): void
  (e: 'remove', id: string): void
  (e: 'toggle'): void
  (e: 'clear-all'): void
}>()

const searchKw = ref('')

const filtered = computed(() => searchConversations(props.list, searchKw.value))

function formatTs(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts)
  const today = new Date()
  if (d.toDateString() === today.toDateString()) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function renameItem(c: Conversation) {
  const next = window.prompt('重命名对话', c.title) || ''
  const t = next.trim()
  if (!t || t === c.title) return
  emit('rename', c.id, t)
}
</script>

<style scoped>
.chat-sidebar {
  position: relative;
  flex: 0 0 auto;
  width: 1.6rem;
  transition: width 220ms ease;
  z-index: 5;
  pointer-events: auto;
}

.chat-sidebar--open {
  width: 16rem;
}

.chat-sidebar__inner {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  width: 16rem;
  background: rgba(15, 23, 42, 0.86);
  border-right: 1px solid rgba(255, 255, 255, 0.07);
  backdrop-filter: blur(8px);
  overflow: hidden;
  transition: transform 220ms ease, opacity 200ms ease;
  transform: translateX(-100%);
  opacity: 0;
  z-index: 4;
}

.chat-sidebar--open .chat-sidebar__inner {
  transform: translateX(0);
  opacity: 1;
}

.chat-sidebar__head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.chat-sidebar__new {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 0.7rem;
  background: linear-gradient(135deg, rgba(129, 140, 248, 0.32), rgba(99, 102, 241, 0.45));
  color: #fff;
  border: 1px solid rgba(165, 180, 252, 0.4);
  border-radius: 0.5rem;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.88rem;
}

.chat-sidebar__new:hover {
  background: linear-gradient(135deg, rgba(129, 140, 248, 0.48), rgba(99, 102, 241, 0.62));
}

.chat-sidebar__new-plus {
  font-size: 1.1rem;
  line-height: 1;
}

.chat-sidebar__close {
  width: 1.9rem;
  height: 1.9rem;
  border-radius: 0.45rem;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(226, 232, 240, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  font-size: 1rem;
}

.chat-sidebar__close:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.chat-sidebar__search {
  padding: 0.55rem 0.75rem;
}

.chat-sidebar__search-input {
  width: 100%;
  padding: 0.45rem 0.6rem;
  border-radius: 0.5rem;
  background: rgba(15, 23, 42, 0.6);
  color: #e2e8f0;
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 0.85rem;
}

.chat-sidebar__search-input:focus {
  outline: none;
  border-color: rgba(129, 140, 248, 0.55);
}

.chat-sidebar__list {
  flex: 1;
  overflow-y: auto;
  padding: 0.25rem 0.4rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.chat-sidebar__item {
  position: relative;
  display: flex;
  align-items: stretch;
  text-align: left;
  width: 100%;
  padding: 0.45rem 0.55rem;
  border-radius: 0.5rem;
  background: transparent;
  color: rgba(226, 232, 240, 0.86);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease;
}

.chat-sidebar__item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.chat-sidebar__item--active {
  background: rgba(99, 102, 241, 0.22);
  border-color: rgba(165, 180, 252, 0.42);
  color: #fff;
}

.chat-sidebar__item-main {
  flex: 1;
  min-width: 0;
}

.chat-sidebar__item-title {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.88rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-sidebar__item-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-sidebar__pin {
  font-size: 0.75rem;
}

.chat-sidebar__item-meta {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.18rem;
  font-size: 0.7rem;
  color: rgba(203, 213, 225, 0.6);
}

.chat-sidebar__agent {
  color: rgba(165, 180, 252, 0.85);
}

.chat-sidebar__item-ops {
  display: none;
  flex-direction: column;
  gap: 0.18rem;
  margin-left: 0.3rem;
}

.chat-sidebar__item:hover .chat-sidebar__item-ops,
.chat-sidebar__item--active .chat-sidebar__item-ops {
  display: flex;
}

.chat-sidebar__op {
  width: 1.55rem;
  height: 1.45rem;
  display: grid;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 23, 42, 0.6);
  color: rgba(226, 232, 240, 0.78);
  border-radius: 0.32rem;
  cursor: pointer;
  font-size: 0.7rem;
  line-height: 1;
  padding: 0;
}

.chat-sidebar__op:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.chat-sidebar__op--danger:hover {
  background: rgba(248, 113, 113, 0.32);
  border-color: rgba(248, 113, 113, 0.45);
}

.chat-sidebar__empty {
  padding: 1rem 0.6rem;
  font-size: 0.78rem;
  color: rgba(203, 213, 225, 0.6);
  text-align: center;
}

.chat-sidebar__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 0.72rem;
  color: rgba(203, 213, 225, 0.6);
}

.chat-sidebar__foot-clear {
  background: transparent;
  border: 1px solid rgba(248, 113, 113, 0.32);
  color: rgba(252, 165, 165, 0.92);
  padding: 0.18rem 0.55rem;
  border-radius: 0.35rem;
  cursor: pointer;
  font-size: 0.7rem;
}

.chat-sidebar__foot-clear:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}

.chat-sidebar__foot-clear:not(:disabled):hover {
  background: rgba(248, 113, 113, 0.18);
}

.chat-sidebar__handle {
  position: absolute;
  top: 50%;
  left: 0.1rem;
  transform: translateY(-50%);
  width: 1.4rem;
  height: 3rem;
  border-radius: 0 0.4rem 0.4rem 0;
  background: rgba(15, 23, 42, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-left: none;
  color: rgba(226, 232, 240, 0.85);
  cursor: pointer;
  z-index: 6;
  font-size: 0.95rem;
  padding: 0;
}

.chat-sidebar__handle:hover {
  background: rgba(99, 102, 241, 0.22);
  color: #fff;
}

html[data-workbench-theme='light'] .chat-sidebar__inner {
  background: #f5f5f7;
  border-right-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .chat-sidebar__head {
  border-bottom-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .chat-sidebar__new {
  background: #0071e3;
  color: #fff;
  border-color: rgba(0, 113, 227, 0.35);
}

html[data-workbench-theme='light'] .chat-sidebar__new:hover {
  background: #0062cc;
}

html[data-workbench-theme='light'] .chat-sidebar__close {
  background: rgba(0, 0, 0, 0.04);
  color: #86868b;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .chat-sidebar__close:hover {
  background: rgba(0, 0, 0, 0.08);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .chat-sidebar__search-input {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .chat-sidebar__search-input::placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .chat-sidebar__search-input:focus {
  border-color: rgba(0, 113, 227, 0.5);
}

html[data-workbench-theme='light'] .chat-sidebar__item {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .chat-sidebar__item:hover {
  background: rgba(0, 0, 0, 0.04);
}

html[data-workbench-theme='light'] .chat-sidebar__item--active {
  background: rgba(0, 113, 227, 0.1);
  border-color: rgba(0, 113, 227, 0.35);
  color: #0071e3;
}

html[data-workbench-theme='light'] .chat-sidebar__item-meta {
  color: #86868b;
}

html[data-workbench-theme='light'] .chat-sidebar__agent {
  color: #0071e3;
}

html[data-workbench-theme='light'] .chat-sidebar__op {
  background: rgba(0, 0, 0, 0.04);
  color: #86868b;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .chat-sidebar__op:hover {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .chat-sidebar__op--danger:hover {
  background: rgba(248, 113, 113, 0.12);
  border-color: rgba(248, 113, 113, 0.3);
}

html[data-workbench-theme='light'] .chat-sidebar__empty {
  color: #86868b;
}

html[data-workbench-theme='light'] .chat-sidebar__foot {
  border-top-color: rgba(0, 0, 0, 0.06);
  color: #86868b;
}

html[data-workbench-theme='light'] .chat-sidebar__foot-clear {
  border-color: rgba(248, 113, 113, 0.25);
  color: #e53e3e;
}

html[data-workbench-theme='light'] .chat-sidebar__foot-clear:not(:disabled):hover {
  background: rgba(248, 113, 113, 0.08);
}

html[data-workbench-theme='light'] .chat-sidebar__handle {
  background: #f5f5f7;
  border-color: rgba(0, 0, 0, 0.08);
  color: #86868b;
}

html[data-workbench-theme='light'] .chat-sidebar__handle:hover {
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
}
</style>
