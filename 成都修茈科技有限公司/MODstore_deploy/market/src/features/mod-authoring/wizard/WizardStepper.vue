<script setup lang="ts">
import { WIZARD_STEPS } from '../types'

defineProps<{
  currentStep: number
  completion: boolean[]
}>()

const emit = defineEmits<{
  go: [step: number]
}>()
</script>

<template>
  <nav class="wizard-stepper" aria-label="制作步骤">
    <button
      v-for="(s, i) in WIZARD_STEPS"
      :key="s.key"
      type="button"
      class="wizard-step"
      :class="{
        active: currentStep === s.id,
        done: completion[i],
      }"
      @click="emit('go', s.id)"
    >
      <span class="wizard-step-num">{{ completion[i] ? '✓' : s.id }}</span>
      <span class="wizard-step-label">{{ s.label }}</span>
    </button>
  </nav>
</template>
