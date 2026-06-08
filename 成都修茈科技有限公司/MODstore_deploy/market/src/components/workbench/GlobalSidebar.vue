<template>
  <aside class="wb-sidebar" :class="{ 'wb-sidebar--collapsed': collapsed }">
    <div class="wb-sidebar-top">
      <button type="button" class="wb-sidebar-toggle" @click="$emit('toggle')" :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="0.5" y="2" width="15" height="12" rx="1.5" fill="none"/><rect x="2" y="4" width="3.5" height="8" rx="0.5" fill="currentColor"/></svg>
      </button>
    </div>

    <div class="wb-sidebar-bottom">
      <div class="wb-sidebar-nav-links">
        <a href="/market/workbench/home" class="wb-sidebar-mode-btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><rect x="1" y="2" width="14" height="10" rx="1.5"/><line x1="5" y1="14" x2="11" y2="14"/><line x1="8" y1="12" x2="8" y2="14"/></svg>
          <span>工作台</span>
        </a>
        <a href="/market/plans" class="wb-sidebar-mode-btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M8 1.5l1.8 3.6 4 .6-2.9 2.8.7 4L8 10.4 4.4 12.5l.7-4L2.2 5.7l4-.6z"/></svg>
          <span>会员</span>
        </a>
        <a href="/market/ai-store" class="wb-sidebar-mode-btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 4h12l-1 9H3L2 4z"/><path d="M5 4V2.5a3 3 0 016 0V4"/></svg>
          <span>AI 市场</span>
        </a>
        <a href="/market/customer-service" class="wb-sidebar-mode-btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M3 8a5 5 0 0110 0v2a1 1 0 01-1 1H4a1 1 0 01-1-1V8z"/><path d="M6 13h4"/><path d="M8 11v2"/></svg>
          <span>AI 客服</span>
        </a>
        <a href="/market/ai-test" class="wb-sidebar-mode-btn">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 5l6-3 6 3v6l-6 3-6-3V5z"/><line x1="8" y1="2" x2="8" y2="14"/><line x1="2" y1="5" x2="14" y2="11"/><line x1="14" y1="5" x2="2" y2="11"/></svg>
          <span>AI 测试</span>
        </a>
      </div>
      <div class="wb-sidebar-divider"></div>
      <button type="button" class="wb-sidebar-mode-btn" @click="$emit('open-settings')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="8" cy="8" r="2.5"/><path d="M8 1.5v1.2M8 13.3v1.2M1.5 8h1.2M13.3 8h1.2M3.4 3.4l.85.85M11.75 11.75l.85.85M3.4 12.6l.85-.85M11.75 4.25l.85-.85"/></svg>
        <span>设置</span>
      </button>
      <a href="/market/notifications" class="wb-sidebar-mode-btn" title="通知">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M8 2a4 4 0 0 0-4 4v2.07l-.56 1.12A1.6 1.6 0 0 0 4.87 11.8h6.26a1.6 1.6 0 0 0 1.43-2.61L12 8.07V6a4 4 0 0 0-4-4z"/><path d="M6.5 13a1.5 1.5 0 0 0 3 0"/></svg>
        <span>通知</span>
      </a>
      <a href="/market/wallet" class="wb-sidebar-mode-btn" title="钱包">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="1.5" y="4" width="13" height="9" rx="1.5"/><path d="M1.5 7h13"/><path d="M11 9.5h1.5"/></svg>
        <span>钱包</span>
      </a>
      <div class="wb-sidebar-user-row">
        <a href="/market/account" class="wb-sidebar-user-link">{{ username }}</a>
        <a v-if="level" href="/market/account" class="wb-sidebar-level-badge" :title="levelTitle">Lv.{{ level }}</a>
        <span v-if="balance !== null" class="wb-sidebar-balance">¥{{ balance.toFixed(2) }}</span>
        <span v-else class="wb-sidebar-balance wb-sidebar-balance--loading">...</span>
        <button type="button" class="wb-sidebar-logout-btn" @click="$emit('logout')">退出</button>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
defineProps<{
  collapsed: boolean
  username: string
  level: number | null
  levelTitle: string
  balance: number | null
}>()

defineEmits<{
  toggle: []
  'open-settings': []
  logout: []
}>()
</script>

<style scoped>
.wb-sidebar {
  display: flex;
  flex-direction: column;
  flex: none;
  width: 240px;
  height: 100%;
  overflow: hidden;
  background: var(--color-bg-body);
  border-right: 1px solid rgba(240, 240, 245, 0.05);
  transition: width 200ms cubic-bezier(0.4, 0, 0.2, 1);
  box-sizing: border-box;
}

.wb-sidebar--collapsed {
  width: 56px;
}

.wb-sidebar--collapsed .wb-sidebar-new-chat span,
.wb-sidebar--collapsed .wb-sidebar-conv-title,
.wb-sidebar--collapsed .wb-sidebar-conv-time,
.wb-sidebar--collapsed .wb-sidebar-mode-btn span,
.wb-sidebar--collapsed .wb-sidebar-user-link,
.wb-sidebar--collapsed .wb-sidebar-level-badge,
.wb-sidebar--collapsed .wb-sidebar-balance,
.wb-sidebar--collapsed .wb-sidebar-conv-list {
  display: none;
}

.wb-sidebar--collapsed .wb-sidebar-new-chat {
  display: none;
}

.wb-sidebar--collapsed .wb-sidebar-mode-btn {
  justify-content: center;
  padding: 8px;
}

.wb-sidebar--collapsed .wb-sidebar-user-row {
  justify-content: center;
}

.wb-sidebar-top {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 12px 8px;
  flex-shrink: 0;
}

.wb-sidebar-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(240, 240, 245, 0.45);
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
  transition: background 180ms ease, color 180ms ease;
}

.wb-sidebar-toggle:hover {
  background: rgba(129, 140, 248, 0.08);
  color: rgba(240, 240, 245, 0.85);
}

.wb-sidebar-new-chat {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  padding: 8px 12px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: rgba(240, 240, 245, 0.55);
  font-size: 13px;
  font-weight: 400;
  cursor: pointer;
  transition: background 180ms ease, color 180ms ease;
}

.wb-sidebar-new-chat:hover {
  background: rgba(129, 140, 248, 0.08);
  color: rgba(240, 240, 245, 0.9);
}

.wb-sidebar-conv-list {
  flex: 1 1 0%;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 8px;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.15) transparent;
  overscroll-behavior: contain;
}

.wb-sidebar-divider {
  height: 1px;
  background: rgba(240, 240, 245, 0.05);
  margin: 8px 12px;
  flex-shrink: 0;
}

.wb-sidebar-modes {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 8px;
  flex-shrink: 0;
}

.wb-sidebar-mode-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: rgba(240, 240, 245, 0.45);
  font-size: 13px;
  font-weight: 400;
  cursor: pointer;
  text-align: left;
  text-decoration: none;
  transition: background 180ms ease, color 180ms ease;
}

.wb-sidebar-mode-btn:hover {
  background: rgba(129, 140, 248, 0.06);
  color: rgba(240, 240, 245, 0.8);
}

.wb-sidebar-mode-btn--active {
  background: rgba(129, 140, 248, 0.1);
  color: rgba(240, 240, 245, 0.95);
}

.wb-sidebar-nav-links .wb-sidebar-mode-btn span {
  color: inherit;
}

.wb-sidebar-nav-links {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.wb-sidebar-bottom {
  flex-shrink: 0;
  padding: 8px;
  border-top: 1px solid rgba(240, 240, 245, 0.05);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.wb-sidebar-user-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 10px;
  flex-wrap: wrap;
}

.wb-sidebar-user-link {
  font-size: 13px;
  font-weight: 600;
  color: rgba(240, 240, 245, 0.7);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100px;
  transition: color 150ms ease;
}

.wb-sidebar-user-link:hover {
  color: rgba(240, 240, 245, 0.95);
}

.wb-sidebar-level-badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  background: rgba(129, 140, 248, 0.12);
  color: rgba(129, 140, 248, 0.9);
  font-size: 11px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
  transition: background 150ms ease;
}

.wb-sidebar-level-badge:hover {
  background: rgba(129, 140, 248, 0.22);
}

.wb-sidebar-balance {
  font-size: 12px;
  color: rgba(240, 240, 245, 0.4);
  white-space: nowrap;
  margin-left: auto;
}

.wb-sidebar-balance--loading {
  animation: wb-sidebar-balance-pulse 1.5s ease-in-out infinite;
}

@keyframes wb-sidebar-balance-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.8; }
}

.wb-sidebar-logout-btn {
  margin-left: auto;
  border: none;
  background: none;
  color: rgba(240, 240, 245, 0.3);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: color 150ms ease, background 150ms ease;
}

.wb-sidebar-logout-btn:hover {
  color: rgba(239, 68, 68, 0.85);
  background: rgba(239, 68, 68, 0.08);
}

html[data-workbench-theme='light'] .wb-sidebar {
  border-right: 1px solid rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .wb-sidebar-toggle {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-sidebar-toggle:hover {
  background: rgba(0, 113, 227, 0.08);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar-new-chat {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-sidebar-new-chat:hover {
  background: rgba(0, 113, 227, 0.08);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar-conv-list {
  scrollbar-color: rgba(0, 113, 227, 0.15) transparent;
}

html[data-workbench-theme='light'] .wb-sidebar-divider {
  background: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .wb-sidebar-mode-btn {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-sidebar-mode-btn:hover {
  background: rgba(0, 113, 227, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar-mode-btn--active {
  background: rgba(0, 113, 227, 0.1);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar-bottom {
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .wb-sidebar-user-link {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar-user-link:hover {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar-level-badge {
  background: rgba(0, 113, 227, 0.12);
  color: rgba(0, 113, 227, 0.9);
}

html[data-workbench-theme='light'] .wb-sidebar-level-badge:hover {
  background: rgba(0, 113, 227, 0.22);
}

html[data-workbench-theme='light'] .wb-sidebar-balance {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-sidebar-logout-btn {
  color: #86868b;
}
</style>
