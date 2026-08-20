<template>
  <div v-if="open" class="im-modal" @click.self="$emit('close')">
    <div class="im-modal-card">
      <header class="im-modal-head">
        <span>选择联系人</span>
        <button type="button" class="im-icon-btn" @click="$emit('close')">
          <i class="fa fa-times" aria-hidden="true"></i>
        </button>
      </header>
      <input :value="keyword" type="text" class="im-compose-input" placeholder="搜索姓名或账号" @input="onInput" />
      <ul v-if="filteredContacts.length" class="im-contact-list">
        <li v-for="ct in filteredContacts" :key="ct.id" class="im-contact-item" @click="$emit('select', ct)">
          <span class="im-avatar im-avatar--sm" aria-hidden="true">{{ avatarText(ct.display_name) }}</span>
          <div class="im-contact-main">
            <div class="im-contact-name">{{ ct.display_name }}</div>
            <div class="im-contact-sub">@{{ ct.username }}</div>
          </div>
        </li>
      </ul>
      <div v-else class="im-empty">
        <p>{{ contactsLoading ? '加载中…' : '未找到联系人' }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ImContact } from '@/api/im'
import { avatarText } from '@/composables/messenger/useMessengerEntries'

defineProps<{
  open: boolean
  keyword: string
  filteredContacts: ImContact[]
  contactsLoading: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:keyword', value: string): void
  (e: 'select', contact: ImContact): void
}>()

function onInput(ev: Event): void {
  const target = ev.target as HTMLInputElement
  emit('update:keyword', target.value)
}
</script>

<style scoped>
.im-icon-btn {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--xc-color-muted, #86909c);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  transition:
    background 150ms ease,
    color 150ms ease;
}
.im-icon-btn:hover {
  background: rgba(0, 82, 217, 0.08);
  color: var(--xc-color-primary, #0052d9);
}
.im-compose-input {
  flex: 1;
  padding: 9px 12px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 8px;
  font: inherit;
  font-size: 14px;
  outline: none;
  transition: border-color 150ms ease;
}
.im-compose-input:focus {
  border-color: var(--xc-color-primary, #0052d9);
}
.im-avatar {
  flex: none;
  flex-basis: 38px;
  width: 38px;
  height: 38px;
  min-width: 38px;
  min-height: 38px;
  aspect-ratio: 1;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, #5b8def, #0052d9);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
.im-avatar--sm {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  font-size: 13px;
}
.im-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex: 1;
  padding: 24px;
  color: var(--xc-color-muted, #86909c);
  text-align: center;
}
.im-empty p {
  margin: 0;
  font-size: 13px;
}
.im-modal {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}
.im-modal-card {
  width: min(380px, 92vw);
  max-height: 70vh;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  padding: 16px;
  gap: 12px;
}
.im-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 15px;
  font-weight: 600;
  color: var(--xc-color-text, #1f2329);
}
.im-contact-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
}
.im-contact-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 150ms ease;
}
.im-contact-item:hover {
  background: rgba(0, 82, 217, 0.07);
}
.im-contact-main {
  min-width: 0;
}
.im-contact-name {
  font-size: 14px;
  color: var(--xc-color-text, #1f2329);
}
.im-contact-sub {
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
}
</style>
