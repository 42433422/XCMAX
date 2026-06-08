<template>
  <div class="corp-welcome" role="region" aria-label="管家欢迎">
    <h2 class="corp-welcome__title">{{ title }}</h2>
    <p class="corp-welcome__subtitle">{{ subtitle }}</p>

    <button
      v-if="isMobileContact"
      type="button"
      class="corp-welcome__cta btn btn-primary"
      @click="onIntakeCtaClick"
    >
      {{ intakeTriggerLabel }}
    </button>

    <ul v-else class="corp-welcome__tasks" role="list">
      <li v-for="(item, i) in tasks" :key="i">
        <button type="button" class="corp-task-card" @click="$emit('task', item)">
          <span class="corp-task-card__icon" aria-hidden="true">✦</span>
          <span class="corp-task-card__label">{{ item.label }}</span>
          <span class="corp-task-card__arrow" aria-hidden="true">›</span>
        </button>
      </li>
    </ul>
    <p v-if="!isMobileContact && tasks.length" class="corp-welcome__hint">{{ hintText }}</p>
    <p v-else-if="isMobileContact && intakeCtaUsed" class="corp-welcome__hint">
      也可在下方输入框用文字描述场景
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { QuickAction } from '../../content/siteKnowledge'
import {
  contactIntakeFillCompleted,
  openContactIntakeModal,
} from '../../corp-butler/useContactIntakeModal'

const props = withDefaults(
  defineProps<{
    title?: string
    subtitle: string
    tasks: QuickAction[]
    isContactPage?: boolean
    isMobileContact?: boolean
  }>(),
  {
    title: 'Hi，我是修茈科技 AI 管家',
    isContactPage: false,
    isMobileContact: false,
  },
)

defineEmits<{ (e: 'task', action: QuickAction): void }>()

const intakeCtaUsed = ref(false)

const intakeTriggerLabel = computed(() => {
  if (contactIntakeFillCompleted.value) return '已预填 · 点此可再填'
  return 'AI 一键填表'
})

const hintText = computed(() =>
  props.isContactPage
    ? '也可在下方输入框直接描述您的场景'
    : '选择上方任务，或在下方输入您的问题',
)

function onIntakeCtaClick() {
  intakeCtaUsed.value = true
  openContactIntakeModal()
}
</script>

<style scoped>
.corp-welcome {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 2px 6px;
  min-height: 0;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.corp-welcome__title {
  margin: 0;
  flex-shrink: 0;
  font-size: 1.05rem;
  font-weight: 800;
  line-height: 1.35;
  color: rgba(15, 23, 42, 0.92);
}

.corp-welcome__subtitle {
  margin: 0;
  flex-shrink: 0;
  font-size: 0.8rem;
  line-height: 1.55;
  color: rgba(51, 65, 85, 0.88);
}

.corp-welcome__cta {
  width: 100%;
  margin-top: 4px;
  padding: 12px 16px;
  font-size: 0.92rem;
  font-weight: 800;
  border-radius: 14px;
}

.corp-welcome__tasks {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  flex: 1 1 auto;
  min-height: 0;
  max-height: min(280px, 52vh);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.corp-task-card {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.95);
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.corp-task-card:hover {
  background: #f8fafc;
  border-color: rgba(11, 99, 246, 0.22);
}

.corp-task-card__icon {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  font-size: 0.72rem;
  color: #0b63f6;
  background: rgba(11, 99, 246, 0.1);
  border-radius: 6px;
}

.corp-task-card__label {
  flex: 1;
  font-size: 0.82rem;
  line-height: 1.45;
  color: rgba(15, 23, 42, 0.9);
  font-weight: 600;
}

.corp-task-card__arrow {
  flex-shrink: 0;
  font-size: 1.1rem;
  color: rgba(100, 116, 139, 0.85);
}

.corp-welcome__hint {
  margin: 0;
  flex-shrink: 0;
  font-size: 0.72rem;
  color: rgba(100, 116, 139, 0.9);
}
</style>
