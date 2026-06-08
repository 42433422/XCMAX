<script setup lang="ts">
import EmployeeSixDimPanel from './EmployeeSixDimPanel.vue'
import type { SixDimensionReport } from '../../types/sixDimension'

export type { SixDimensionReport } from '../../types/sixDimension'
export type { SixDimEntry } from '../../types/sixDimension'

const props = defineProps<{
  open: boolean
  report: SixDimensionReport | null
}>()

const emit = defineEmits<{
  close: []
}>()
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open && report"
      class="wb-six-dim-backdrop"
      role="presentation"
      @click.self="emit('close')"
    >
      <div
        class="wb-six-dim-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="wb-six-dim-title"
      >
        <header class="wb-six-dim-head">
          <h2 id="wb-six-dim-title" class="wb-six-dim-title">六维质量评估</h2>
          <button type="button" class="wb-six-dim-close" aria-label="关闭" @click="emit('close')">
            ×
          </button>
        </header>
        <div class="wb-six-dim-dialog-body">
          <EmployeeSixDimPanel :report="report" title="" :show-grade-scale="true" />
        </div>
        <footer class="wb-six-dim-foot">
          <button type="button" class="wb-six-dim-btn" @click="emit('close')">知道了</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.wb-six-dim-backdrop {
  position: fixed;
  inset: 0;
  z-index: 12000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
}

.wb-six-dim-dialog {
  width: min(920px, 100%);
  max-height: min(90vh, 820px);
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: var(--wb-panel-bg, #1a1d24);
  color: var(--wb-text, #e8eaed);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
}

.wb-six-dim-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.wb-six-dim-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 600;
}

.wb-six-dim-close {
  border: none;
  background: transparent;
  color: inherit;
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
  opacity: 0.7;
}

.wb-six-dim-dialog-body {
  padding: 8px 16px 0;
  overflow: auto;
  flex: 1;
}

.wb-six-dim-foot {
  padding: 12px 20px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  justify-content: flex-end;
}

.wb-six-dim-btn {
  padding: 8px 18px;
  border-radius: 8px;
  border: none;
  background: #7c3aed;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}
</style>
