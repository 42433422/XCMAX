<script setup lang="ts">
/**
 * 管家面板顶栏内容（logo + 操作按钮组）。
 *
 * 由 FloatingAgentPanel.vue 模板块机械切分而来（行为与视觉保持不变）：
 * header 元素与拖拽事件留在入口，交互经 emit 回到入口。
 */
defineProps<{
  corpMode: boolean
  brandLogoUrl: string
  proactiveIntroOn: boolean
}>()

defineEmits<{
  (e: 'toggle-proactive-intro'): void
  (e: 'toggle-log'): void
  (e: 'clear-messages'): void
  (e: 'close'): void
}>()
</script>

<template>
  <div class="panel-head__left">
    <img
      class="panel-head__logo"
      :src="brandLogoUrl"
      alt=""
      width="28"
      height="28"
      decoding="async"
    />
    <div class="panel-head__titles">
      <span class="panel-head__title">小C助理</span>
    </div>
  </div>
  <div class="panel-head__actions" @pointerdown.stop>
    <button
      v-if="corpMode"
      type="button"
      class="panel-icon-btn"
      :class="{ 'panel-icon-btn--active': proactiveIntroOn }"
      :aria-label="proactiveIntroOn ? '关闭主动介绍' : '开启主动介绍'"
      :title="proactiveIntroOn ? '主动介绍：开（点击关闭）' : '主动介绍：关（点击开启）'"
      @click.stop="$emit('toggle-proactive-intro')"
    >
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M11 5L6 9H3v6h3l5 4V5z"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linejoin="round"
        />
        <path
          v-if="proactiveIntroOn"
          d="M16 9a4 4 0 010 6M18.5 7a7 7 0 010 10"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
        <path
          v-else
          d="M16 10l4 4M20 10l-4 4"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
      </svg>
    </button>
    <button
      v-if="!corpMode"
      type="button"
      class="panel-icon-btn"
      aria-label="查看操作日志"
      title="操作日志"
      @click.stop="$emit('toggle-log')"
    >
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 12h6M9 8h6M9 16h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.6"/></svg>
    </button>
    <button
      type="button"
      class="panel-icon-btn"
      aria-label="清空对话"
      title="清空对话"
      @click.stop="$emit('clear-messages')"
    >
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <button
      type="button"
      class="panel-icon-btn"
      aria-label="关闭管家"
      title="关闭"
      @click.stop="$emit('close')"
    >
      <span aria-hidden="true">×</span>
    </button>
  </div>
</template>

<style scoped src="./floatingAgentPanel.css"></style>
