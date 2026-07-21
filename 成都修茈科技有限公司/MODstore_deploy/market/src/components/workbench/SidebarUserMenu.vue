<template>
  <div class="wb-user-menu" ref="rootRef">
    <button
      type="button"
      class="wb-user-menu__trigger"
      :aria-expanded="open"
      :aria-label="`${username || '账户'} 菜单`"
      aria-haspopup="menu"
      @click="open = !open"
    >
      <span class="wb-user-menu__avatar" aria-hidden="true">{{ avatarLetter }}</span>
      <span class="wb-user-menu__name">{{ username || '账户' }}</span>
      <svg class="wb-user-menu__chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" />
      </svg>
    </button>
    <div v-if="open" class="wb-user-menu__panel" role="menu" @click.stop>
      <div v-if="balance !== null" class="wb-user-menu__balance" role="presentation">
        余额 ¥{{ balance.toFixed(2) }}
      </div>
      <router-link v-if="levelProfile" :to="{ name: 'account' }" class="wb-user-menu__item" role="menuitem" @click="close">
        Lv.{{ levelProfile.level }} · {{ levelProfile.title || '新手' }}
      </router-link>
      <router-link :to="{ name: 'account' }" class="wb-user-menu__item" role="menuitem" @click="close">账户设置</router-link>
      <router-link :to="{ name: 'wallet' }" class="wb-user-menu__item" role="menuitem" @click="close">钱包</router-link>
      <router-link :to="{ name: 'plans' }" class="wb-user-menu__item" role="menuitem" @click="close">会员</router-link>
      <button type="button" class="wb-user-menu__item" role="menuitem" @click="onSettings">设置</button>
      <router-link :to="{ name: 'notifications' }" class="wb-user-menu__item" role="menuitem" @click="close">通知</router-link>
      <router-link :to="{ name: 'customer-service' }" class="wb-user-menu__item" role="menuitem" @click="close">AI 客服</router-link>
      <router-link :to="{ name: 'ai-test' }" class="wb-user-menu__item" role="menuitem" @click="close">AI 测试</router-link>
      <a href="/index.html" class="wb-user-menu__item" target="_blank" rel="noopener" role="menuitem" @click="close">官网首页</a>
      <button v-if="isAdmin" type="button" class="wb-user-menu__item" role="menuitem" @click="onAdmin">管理端</button>
      <button v-if="isAdmin" type="button" class="wb-user-menu__item" role="menuitem" @click="onOpsTerminal">运维终端</button>
      <div class="wb-user-menu__divider" role="separator" />
      <button type="button" class="wb-user-menu__item wb-user-menu__item--danger" role="menuitem" @click="onLogout">退出登录</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps<{
  username: string
  balance: number | null
  levelProfile: { level: number; title?: string; experience?: number } | null
  isAdmin: boolean
}>()

const emit = defineEmits<{
  settings: []
  admin: []
  opsTerminal: []
  logout: []
}>()

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)

const avatarLetter = computed(() => (props.username || '?').trim().charAt(0).toUpperCase() || '?')

function close() {
  open.value = false
}

function onSettings() {
  close()
  emit('settings')
}

function onAdmin() {
  close()
  emit('admin')
}

function onOpsTerminal() {
  close()
  emit('opsTerminal')
}

function onLogout() {
  close()
  emit('logout')
}

function onDocClick(e: MouseEvent) {
  const el = e.target as Node | null
  if (!open.value || !rootRef.value || !el) return
  if (!rootRef.value.contains(el)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick, true))
onUnmounted(() => document.removeEventListener('click', onDocClick, true))
</script>

<style scoped>
.wb-user-menu {
  position: relative;
  width: 100%;
}

.wb-user-menu__trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 44px;
  padding: 8px 10px;
  border: none;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--wb-sidebar-text, #e5e5e5);
  cursor: pointer;
  text-align: left;
  box-sizing: border-box;
  transition: background 180ms ease;
}

.wb-user-menu__trigger:hover {
  background: rgba(255, 255, 255, 0.08);
}

.wb-user-menu__chevron {
  flex-shrink: 0;
}

.wb-user-menu__avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.82rem;
  font-weight: 600;
  background: rgba(99, 102, 241, 0.35);
  flex-shrink: 0;
}

.wb-user-menu__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.88rem;
}

.wb-user-menu__panel {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 6px);
  z-index: 20;
  padding: 6px;
  border-radius: 12px;
  background: var(--wb-sidebar-bg, #111);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.45);
  max-height: min(70vh, 420px);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--wb-accent-soft, rgba(129, 140, 248, 0.22)) transparent;
}

.wb-user-menu__panel::-webkit-scrollbar {
  width: 6px;
}

.wb-user-menu__panel::-webkit-scrollbar-track {
  background: transparent;
  margin: 6px 0;
}

.wb-user-menu__panel::-webkit-scrollbar-thumb {
  background: var(--wb-accent-soft, rgba(129, 140, 248, 0.22));
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: padding-box;
}

.wb-user-menu__panel::-webkit-scrollbar-thumb:hover {
  background: rgba(129, 140, 248, 0.38);
  background-clip: padding-box;
}

html[data-workbench-theme='light'] .wb-user-menu__panel {
  scrollbar-color: rgba(0, 0, 0, 0.12) transparent;
}

html[data-workbench-theme='light'] .wb-user-menu__panel::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.14);
  background-clip: padding-box;
}

html[data-workbench-theme='light'] .wb-user-menu__panel::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.22);
  background-clip: padding-box;
}

.wb-user-menu__balance {
  padding: 8px 10px;
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.55);
}

.wb-user-menu__item {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font-size: 0.86rem;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.wb-user-menu__item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.wb-user-menu__item--danger {
  color: #fca5a5;
}

.wb-user-menu__divider {
  height: 1px;
  margin: 4px 6px;
  background: rgba(255, 255, 255, 0.1);
}
</style>
