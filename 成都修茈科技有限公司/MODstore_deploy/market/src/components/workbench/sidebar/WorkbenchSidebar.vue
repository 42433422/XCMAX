<template>
  <aside
    class="wb-sidebar"
    :class="{
      'wb-sidebar--collapsed': navStore.sidebarCollapsed,
      'wb-sidebar--mobile-open': navStore.sidebarMobileOpen,
    }"
    :aria-label="navStore.sidebarCollapsed ? '工作台侧边栏（已折叠）' : '工作台侧边栏'"
  >
    <div
      v-if="navStore.sidebarMobileOpen"
      class="wb-sidebar__backdrop"
      @click="navStore.toggleMobileSidebar"
    />

    <div class="wb-sidebar__inner">
      <div class="wb-sidebar__head">
        <button
          type="button"
          class="wb-sidebar__toggle"
          :aria-label="navStore.sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'"
          :title="navStore.sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'"
          @click="navStore.toggleSidebar"
        >
          <svg
            class="wb-sidebar__toggle-icon"
            :class="{ 'wb-sidebar__toggle-icon--open': !navStore.sidebarCollapsed }"
            width="18"
            height="18"
            viewBox="0 0 18 18"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <line x1="3" y1="5" x2="15" y2="5" />
            <line x1="3" y1="9" x2="15" y2="9" />
            <line x1="3" y1="13" x2="15" y2="13" />
          </svg>
        </button>
      </div>

      <button
        type="button"
        class="wb-sidebar__new-chat"
        aria-label="新建对话"
        @click="emit('new-chat')"
      >
        <svg
          class="wb-sidebar__new-chat-icon"
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          aria-hidden="true"
        >
          <line x1="8" y1="3" x2="8" y2="13" />
          <line x1="3" y1="8" x2="13" y2="8" />
        </svg>
        <span class="wb-sidebar__label">新建对话</span>
      </button>

      <div class="wb-sidebar__history" role="list" aria-label="对话历史">
        <slot name="history" />
        <p v-if="!$slots.history" class="wb-sidebar__history-empty">暂无对话</p>
      </div>

      <div class="wb-sidebar__bottom">
        <div class="wb-sidebar__separator" aria-hidden="true" />

        <button
          type="button"
          class="wb-sidebar__fn-btn"
          :class="{ 'wb-sidebar__fn-btn--active': activePanel === 'make' }"
          aria-label="制作"
          @click="handlePanelToggle('make')"
        >
          <svg
            class="wb-sidebar__fn-icon"
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <rect x="2" y="2" width="5" height="5" rx="1" />
            <rect x="9" y="2" width="5" height="5" rx="1" />
            <rect x="2" y="9" width="5" height="5" rx="1" />
            <line x1="9" y1="11.5" x2="14" y2="11.5" />
            <line x1="11.5" y1="9" x2="11.5" y2="14" />
          </svg>
          <span class="wb-sidebar__label">制作</span>
        </button>

        <button
          type="button"
          class="wb-sidebar__fn-btn"
          :class="{ 'wb-sidebar__fn-btn--active': activePanel === 'voice' }"
          aria-label="语音"
          @click="handlePanelToggle('voice')"
        >
          <svg
            class="wb-sidebar__fn-icon"
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <rect x="5.5" y="2" width="5" height="8" rx="2.5" />
            <path d="M3 7a5 5 0 0 0 10 0" />
            <line x1="8" y1="12" x2="8" y2="14.5" />
            <line x1="5.5" y1="14.5" x2="10.5" y2="14.5" />
          </svg>
          <span class="wb-sidebar__label">语音</span>
        </button>

        <button
          type="button"
          class="wb-sidebar__fn-btn"
          aria-label="设置"
          @click="emit('open-settings')"
        >
          <svg
            class="wb-sidebar__fn-icon"
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <circle cx="8" cy="8" r="2.5" />
            <path d="M8 1.5v1.2M8 13.3v1.2M1.5 8h1.2M13.3 8h1.2M3.4 3.4l.85.85M11.75 11.75l.85.85M3.4 12.6l.85-.85M11.75 4.25l.85-.85" />
          </svg>
          <span class="wb-sidebar__label">设置</span>
        </button>
      </div>

      <div class="wb-sidebar__user" aria-label="用户信息">
        <span class="wb-sidebar__avatar" aria-hidden="true">{{ displayName.charAt(0) }}</span>
        <span class="wb-sidebar__username">{{ displayName }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useWorkbenchNavStore } from '../../../stores/workbenchNav'

const navStore = useWorkbenchNavStore()

const props = withDefaults(defineProps<{
  displayName?: string
  activePanel?: string
}>(), {
  displayName: '用户',
  activePanel: '',
})

const emit = defineEmits<{
  (e: 'new-chat'): void
  (e: 'open-panel', type: string): void
  (e: 'close-panel'): void
  (e: 'open-settings'): void
}>()

function handlePanelToggle(type: string) {
  if (props.activePanel === type) {
    emit('close-panel')
  } else {
    emit('open-panel', type)
  }
}
</script>

<style scoped>
.wb-sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 240px;
  flex-shrink: 0;
  background: #0f0f0f;
  border-right: 1px solid var(--wb-sidebar-border, rgba(255, 255, 255, 0.06));
  transition: width 200ms cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  z-index: 10;
}

.wb-sidebar--collapsed {
  width: 56px;
}

.wb-sidebar__backdrop {
  display: none;
}

.wb-sidebar__inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 240px;
  overflow: hidden;
}

.wb-sidebar--collapsed .wb-sidebar__inner {
  min-width: 56px;
  align-items: center;
}

.wb-sidebar__head {
  display: flex;
  align-items: center;
  padding: 12px 12px 8px;
  flex-shrink: 0;
}

.wb-sidebar--collapsed .wb-sidebar__head {
  justify-content: center;
  padding: 12px 0 8px;
}

.wb-sidebar__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: background 150ms cubic-bezier(0.4, 0, 0.2, 1), color 150ms cubic-bezier(0.4, 0, 0.2, 1);
  padding: 0;
}

.wb-sidebar__toggle:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
}

.wb-sidebar__toggle:focus-visible {
  outline: 2px solid rgba(99, 102, 241, 0.6);
  outline-offset: 2px;
}

.wb-sidebar__toggle-icon {
  transition: transform 200ms cubic-bezier(0.4, 0, 0.2, 1);
}

.wb-sidebar--collapsed .wb-sidebar__toggle-icon {
  transform: rotate(180deg);
}

.wb-sidebar__new-chat {
  display: flex;
  align-items: center;
  gap: 8px;
  width: calc(100% - 24px);
  margin: 0 12px 8px;
  padding: 9px 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 150ms cubic-bezier(0.4, 0, 0.2, 1), border-color 150ms cubic-bezier(0.4, 0, 0.2, 1), color 150ms cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  overflow: hidden;
}

.wb-sidebar__new-chat:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.wb-sidebar__new-chat:focus-visible {
  outline: 2px solid rgba(99, 102, 241, 0.6);
  outline-offset: 2px;
}

.wb-sidebar--collapsed .wb-sidebar__new-chat {
  width: 36px;
  margin: 0 auto 8px;
  padding: 9px 0;
  justify-content: center;
}

.wb-sidebar__new-chat-icon {
  flex-shrink: 0;
}

.wb-sidebar__label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.wb-sidebar--collapsed .wb-sidebar__label {
  display: none;
}

.wb-sidebar__history {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
  display: flex;
  flex-direction: column;
  scrollbar-width: thin;
  scrollbar-color: rgba(99, 102, 241, 0.2) transparent;
}

.wb-sidebar--collapsed .wb-sidebar__history {
  padding: 4px 0;
}

.wb-sidebar__history-empty {
  margin: auto;
  padding: 24px 8px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.25);
  text-align: center;
  line-height: 1.6;
}

.wb-sidebar--collapsed .wb-sidebar__history-empty {
  display: none;
}

.wb-sidebar__bottom {
  flex-shrink: 0;
  padding: 0 8px;
}

.wb-sidebar--collapsed .wb-sidebar__bottom {
  padding: 0;
  width: 100%;
}

.wb-sidebar__separator {
  height: 1px;
  background: rgba(255, 255, 255, 0.06);
  margin: 4px 4px 4px;
}

.wb-sidebar--collapsed .wb-sidebar__separator {
  margin: 4px 10px;
}

.wb-sidebar__fn-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
  cursor: pointer;
  transition: background 150ms cubic-bezier(0.4, 0, 0.2, 1), color 150ms cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  overflow: hidden;
}

.wb-sidebar__fn-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.9);
}

.wb-sidebar__fn-btn--active {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.95);
}

.wb-sidebar__fn-btn:focus-visible {
  outline: 2px solid rgba(99, 102, 241, 0.6);
  outline-offset: 2px;
}

.wb-sidebar--collapsed .wb-sidebar__fn-btn {
  justify-content: center;
  padding: 8px 0;
}

.wb-sidebar__fn-icon {
  flex-shrink: 0;
}

.wb-sidebar__user {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  flex-shrink: 0;
  min-width: 0;
}

.wb-sidebar--collapsed .wb-sidebar__user {
  justify-content: center;
  padding: 10px 0;
}

.wb-sidebar__avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.wb-sidebar__username {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.wb-sidebar--collapsed .wb-sidebar__username {
  display: none;
}

@media (max-width: 768px) {
  .wb-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 240px;
    transform: translateX(-100%);
    transition: transform 200ms cubic-bezier(0.4, 0, 0.2, 1);
    z-index: 100;
  }

  .wb-sidebar--collapsed {
    width: 240px;
  }

  .wb-sidebar--mobile-open {
    transform: translateX(0);
  }

  .wb-sidebar__backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: -1;
  }
}

html[data-workbench-theme='light'] .wb-sidebar {
  background: #f5f5f7;
  border-right-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .wb-sidebar__toggle {
  background: rgba(0, 0, 0, 0.04);
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-sidebar__toggle:hover {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar__toggle:focus-visible {
  outline-color: rgba(0, 113, 227, 0.6);
}

html[data-workbench-theme='light'] .wb-sidebar__new-chat {
  border-color: rgba(0, 0, 0, 0.1);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar__new-chat:hover {
  background: rgba(0, 0, 0, 0.04);
  border-color: rgba(0, 0, 0, 0.12);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar__new-chat:focus-visible {
  outline-color: rgba(0, 113, 227, 0.6);
}

html[data-workbench-theme='light'] .wb-sidebar__history {
  scrollbar-color: rgba(0, 113, 227, 0.2) transparent;
}

html[data-workbench-theme='light'] .wb-sidebar__history-empty {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-sidebar__separator {
  background: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .wb-sidebar__fn-btn {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-sidebar__fn-btn:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar__fn-btn--active {
  background: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-sidebar__fn-btn:focus-visible {
  outline-color: rgba(0, 113, 227, 0.6);
}

html[data-workbench-theme='light'] .wb-sidebar__avatar {
  background: rgba(0, 113, 227, 0.15);
  color: #0071e3;
}

html[data-workbench-theme='light'] .wb-sidebar__username {
  color: #86868b;
}

@media (max-width: 768px) {
  html[data-workbench-theme='light'] .wb-sidebar__backdrop {
    background: rgba(0, 0, 0, 0.25);
  }
}
</style>
