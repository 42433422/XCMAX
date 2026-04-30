<template>
  <Teleport to="body">
    <div
      v-if="modalVisible"
      class="global-lan-gate-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="global-lan-gate-title"
    >
      <div id="global-lan-gate-title" class="sr-only">局域网授权</div>
      <div class="global-lan-gate-backdrop" @click.self="dismissLanGateModal" />
      <div class="global-lan-gate-shell" @click.stop>
        <LanGatePanel variant="modal" :redirect-path="modalRedirect || '/'" />
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue';
import LanGatePanel from '@/components/lan/LanGatePanel.vue';
import { useLanGate } from '@/composables/useLanGate';
import { XCAGI_PROMPT_LAN_GATE_EVENT } from '@/api/core';

const { modalVisible, modalRedirect, dismissLanGateModal, openLanGateModal, refresh } = useLanGate();

/**
 * 任一业务请求拿到 401+license_* 时触发；直接打开授权框而不是把异常抛到各业务页。
 * 为避免反复弹，若已经可见就只刷新一次状态。
 */
async function handleLanGatePrompt() {
  try {
    await refresh(true);
  } catch {
    /* refresh 本身可能因未授权失败，这里无需处理 */
  }
  if (!modalVisible.value) {
    const currentPath =
      typeof window !== 'undefined' && window.location ? window.location.pathname + window.location.search : '/';
    openLanGateModal(currentPath || '/');
  }
}

onMounted(() => {
  if (typeof window === 'undefined') return;
  window.addEventListener(XCAGI_PROMPT_LAN_GATE_EVENT, handleLanGatePrompt as EventListener);
});

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return;
  window.removeEventListener(XCAGI_PROMPT_LAN_GATE_EVENT, handleLanGatePrompt as EventListener);
});
</script>

<style scoped>
.global-lan-gate-overlay {
  position: fixed;
  inset: 0;
  z-index: 10050;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.global-lan-gate-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(4px);
}

.global-lan-gate-shell {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 520px;
  max-height: min(92vh, 760px);
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
