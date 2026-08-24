<template>
  <div class="decision-options" role="group" aria-label="选择处理方式">
    <div class="decision-options__eyebrow">
      <span class="decision-options__spark" aria-hidden="true">✦</span>
      <span>选择下一步</span>
    </div>
    <div class="decision-options__grid">
      <button
        v-for="option in options"
        :key="option.id"
        type="button"
        class="decision-option"
        :class="{ 'is-recommended': option.recommended }"
        :disabled="disabled"
        @click="$emit('select', option)"
      >
        <span class="decision-option__topline">
          <span class="decision-option__label">{{ option.label }}</span>
          <span v-if="option.recommended" class="decision-option__badge">推荐</span>
        </span>
        <span v-if="option.description" class="decision-option__description">{{ option.description }}</span>
        <span class="decision-option__arrow" aria-hidden="true">→</span>
      </button>
    </div>
    <p v-if="disabled" class="decision-options__resolved">这组选择已结束，可继续在输入框中对话。</p>
  </div>
</template>

<script setup lang="ts">
import type { ChatDecisionOption } from '@/types/chat-ui'

defineProps<{
  options: ChatDecisionOption[]
  disabled?: boolean
}>()

defineEmits<{
  select: [option: ChatDecisionOption]
}>()
</script>

<style scoped>
.decision-options {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(40, 103, 190, 0.14);
}

.decision-options__eyebrow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 9px;
  color: #4d6f9f;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.04em;
}

.decision-options__spark {
  color: #2867be;
  font-size: 13px;
}

.decision-options__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.decision-option {
  position: relative;
  min-height: 94px;
  padding: 12px 30px 12px 12px;
  overflow: hidden;
  border: 1px solid rgba(65, 106, 163, 0.2);
  border-radius: 13px;
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(243, 247, 253, 0.94));
  color: #263b58;
  cursor: pointer;
  text-align: left;
  box-shadow: 0 5px 16px rgba(35, 79, 139, 0.06);
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease, background 160ms ease;
}

.decision-option:hover:not(:disabled) {
  border-color: rgba(40, 103, 190, 0.5);
  background: linear-gradient(145deg, #ffffff, #eef5ff);
  box-shadow: 0 9px 22px rgba(35, 79, 139, 0.12);
  transform: translateY(-1px);
}

.decision-option:focus-visible {
  outline: 3px solid rgba(40, 103, 190, 0.2);
  outline-offset: 2px;
}

.decision-option.is-recommended {
  border-color: rgba(40, 103, 190, 0.48);
  background: linear-gradient(145deg, #f7fbff, #eaf3ff);
}

.decision-option:disabled {
  cursor: default;
  opacity: 0.58;
  box-shadow: none;
}

.decision-option__topline {
  display: flex;
  align-items: center;
  gap: 6px;
}

.decision-option__label {
  color: #1f3d65;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}

.decision-option__badge {
  flex: 0 0 auto;
  padding: 2px 6px;
  border-radius: 999px;
  background: #2867be;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}

.decision-option__description {
  display: block;
  margin-top: 7px;
  color: #687b94;
  font-size: 11px;
  line-height: 1.5;
}

.decision-option__arrow {
  position: absolute;
  right: 11px;
  bottom: 10px;
  color: #2867be;
  font-size: 16px;
  transition: transform 160ms ease;
}

.decision-option:hover:not(:disabled) .decision-option__arrow {
  transform: translateX(2px);
}

.decision-options__resolved {
  margin: 8px 0 0;
  color: #8290a3;
  font-size: 11px;
}

@media (max-width: 920px) {
  .decision-options__grid {
    grid-template-columns: 1fr;
  }

  .decision-option {
    min-height: 76px;
  }
}
</style>
