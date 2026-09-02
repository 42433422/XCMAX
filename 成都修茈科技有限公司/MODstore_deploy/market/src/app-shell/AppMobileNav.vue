<script setup lang="ts">
// 拆分自 App.vue 模板（原第 24–39 行）；模板逐字迁移，事件改为 emits，行为不变。
import { useWorkbenchSidebarStore } from '../stores/workbenchSidebar'

defineProps<{
  isAndroidEmbeddedShell: boolean
}>()

defineEmits<{
  (e: 'toggle-mobile'): void
}>()

const wbSidebar = useWorkbenchSidebarStore()
</script>

<template>
  <!-- 移动端遮罩层 -->
  <div v-if="!isAndroidEmbeddedShell && wbSidebar.mobileOpen" class="wb-mobile-overlay" @click="wbSidebar.closeMobile()"></div>
  <!-- 移动端汉堡菜单按钮 -->
  <button
    v-if="!isAndroidEmbeddedShell"
    type="button"
    class="wb-mobile-hamburger"
    :class="{ 'wb-mobile-hamburger--open': wbSidebar.mobileOpen }"
    :aria-label="wbSidebar.mobileOpen ? '关闭菜单' : '打开菜单'"
    :aria-expanded="wbSidebar.mobileOpen"
    aria-controls="wb-sidebar"
    @click="$emit('toggle-mobile')"
  >
    <svg v-if="!wbSidebar.mobileOpen" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><line x1="3" y1="5" x2="17" y2="5"/><line x1="3" y1="10" x2="17" y2="10"/><line x1="3" y1="15" x2="17" y2="15"/></svg>
    <svg v-else width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><line x1="4" y1="4" x2="16" y2="16"/><line x1="16" y1="4" x2="4" y2="16"/></svg>
  </button>
</template>
