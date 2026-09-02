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
        <input v-model="searchKw" type="search" class="chat-sidebar__search-input" placeholder="搜索对话…" aria-label="搜索对话" />
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
            >
              📌
            </button>
            <button type="button" class="chat-sidebar__op" aria-label="重命名" title="重命名" @click.stop="renameItem(c)">✎</button>
            <button type="button" class="chat-sidebar__op" aria-label="导出" title="导出 Markdown" @click.stop="$emit('export', c.id)">
              ⬇
            </button>
            <button
              type="button"
              class="chat-sidebar__op chat-sidebar__op--danger"
              aria-label="删除"
              title="删除"
              @click.stop="$emit('remove', c.id)"
            >
              ×
            </button>
          </div>
        </button>
        <p v-if="!filtered.length" class="chat-sidebar__empty">
          {{ searchKw.trim() ? '没有命中关键词。' : '还没有对话，点上方「新对话」开始。' }}
        </p>
      </div>

      <footer class="chat-sidebar__foot">
        <span class="chat-sidebar__foot-meta">本地保存 · {{ list.length }}/{{ maxConvs }}</span>
        <button type="button" class="chat-sidebar__foot-clear" :disabled="!list.length" @click="$emit('clear-all')">清空全部</button>
      </footer>
    </div>
    <button v-if="!open" type="button" class="chat-sidebar__handle" aria-label="展开会话列表" @click="$emit('toggle')">›</button>
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

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./ChatSidebar.css，模板与逻辑保持原样。 -->
<style scoped src="./ChatSidebar.css"></style>
