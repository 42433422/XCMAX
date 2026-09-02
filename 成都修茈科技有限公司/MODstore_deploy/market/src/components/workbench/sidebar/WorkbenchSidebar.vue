<template>
  <aside
    class="wb-sidebar"
    :class="{
      'wb-sidebar--collapsed': navStore.sidebarCollapsed,
      'wb-sidebar--mobile-open': navStore.sidebarMobileOpen,
    }"
    :aria-label="navStore.sidebarCollapsed ? '工作台侧边栏（已折叠）' : '工作台侧边栏'"
  >
    <div v-if="navStore.sidebarMobileOpen" class="wb-sidebar__backdrop" @click="navStore.toggleMobileSidebar" />

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

      <button type="button" class="wb-sidebar__new-chat" aria-label="新建对话" @click="emit('new-chat')">
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

        <button type="button" class="wb-sidebar__fn-btn" aria-label="设置" @click="emit('open-settings')">
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

const props = withDefaults(
  defineProps<{
    displayName?: string
    activePanel?: string
  }>(),
  {
    displayName: '用户',
    activePanel: '',
  },
)

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

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./WorkbenchSidebar.css，模板与逻辑保持原样。 -->
<style scoped src="./WorkbenchSidebar.css"></style>
