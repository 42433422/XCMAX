<template>
  <details
    :class="['asc-chain', `is-${state}`]"
    :open="userOpen ?? autoOpen"
    data-testid="agent-step-chain"
  >
    <summary class="asc-summary" @click.prevent="toggle">
      <i class="fa fa-sitemap asc-icon" aria-hidden="true"></i>
      <span class="asc-title">执行链</span>
      <span class="asc-count">{{ steps.length }} 步</span>
      <span :class="['asc-pill', `is-${state}`]">{{ stateLabel }}</span>
      <span v-if="durationLabel" class="asc-duration">{{ durationLabel }}</span>
      <i class="fa fa-angle-down asc-chevron" aria-hidden="true"></i>
    </summary>

    <ol class="asc-steps">
      <li v-for="step in steps" :key="step.id" :class="['asc-step', `is-${step.state}`]">
        <details v-if="hasDetails(step)" class="asc-step-details">
          <summary class="asc-step-row" @click.stop>
            <span class="asc-step-icon" aria-hidden="true"><i class="fa" :class="iconFor(step)"></i></span>
            <span class="asc-step-heading">
              <span class="asc-step-title">{{ step.title }}</span>
              <span v-if="step.subtitle" class="asc-step-subtitle">{{ step.subtitle }}</span>
            </span>
            <span v-if="step.retries" class="asc-badge is-retry">重试 {{ step.retries }}</span>
            <span v-if="step.durationMs" class="asc-step-duration">{{ formatDuration(step.durationMs) }}</span>
            <i class="fa asc-step-status" :class="statusIcon(step.state)" aria-hidden="true"></i>
            <i class="fa fa-chevron-right asc-step-chevron" aria-hidden="true"></i>
          </summary>
          <div class="asc-step-body">
            <section v-if="step.output" class="asc-section">
              <div class="asc-label"><i class="fa fa-check-circle" aria-hidden="true"></i>输出</div>
              <pre>{{ step.output }}</pre>
            </section>
            <section v-if="step.error" class="asc-section is-error">
              <div class="asc-label"><i class="fa fa-exclamation-triangle" aria-hidden="true"></i>错误</div>
              <pre>{{ step.error }}</pre>
            </section>
            <section v-if="step.hint" class="asc-section is-hint">
              <div class="asc-label"><i class="fa fa-lightbulb-o" aria-hidden="true"></i>建议</div>
              <p>{{ step.hint }}</p>
            </section>
          </div>
        </details>

        <div v-else class="asc-step-row is-static">
          <span class="asc-step-icon" aria-hidden="true"><i class="fa" :class="iconFor(step)"></i></span>
          <span class="asc-step-heading">
            <span class="asc-step-title">{{ step.title }}</span>
            <span v-if="step.subtitle" class="asc-step-subtitle">{{ step.subtitle }}</span>
          </span>
          <span v-if="step.durationMs" class="asc-step-duration">{{ formatDuration(step.durationMs) }}</span>
          <i class="fa asc-step-status" :class="statusIcon(step.state)" aria-hidden="true"></i>
        </div>
      </li>
    </ol>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  chainDurationMs,
  chainState,
  formatStepDuration,
  hasStepDetails,
  stepStateIcon,
  stepStateLabel,
  type AgentStepView,
  type AgentStepState,
} from '@/utils/agentStepChain'
import { toolIconClass } from '@/utils/toolLabels'

const props = defineProps<{
  steps: AgentStepView[]
}>()

const state = computed<AgentStepState>(() => chainState(props.steps))
const stateLabel = computed(() => stepStateLabel(state.value))
const durationLabel = computed(() => {
  const ms = chainDurationMs(props.steps)
  return ms ? formatStepDuration(ms) : ''
})

/** 执行中自动展开，落终态自动收起；用户手动点过后以用户为准。 */
const autoOpen = computed(() => state.value === 'running' || state.value === 'waiting' || state.value === 'failed')
const userOpen = ref<boolean>()

function toggle() {
  userOpen.value = !(userOpen.value ?? autoOpen.value)
}

function hasDetails(step: AgentStepView): boolean {
  return hasStepDetails(step)
}

function iconFor(step: AgentStepView): string {
  if (step.live) return 'fa-circle-o-notch fa-spin'
  return toolIconClass(step.toolId, step.action)
}

function statusIcon(value: AgentStepState): string {
  return stepStateIcon(value)
}

function formatDuration(ms: number): string {
  return formatStepDuration(ms)
}
</script>

<style scoped src="./AgentStepChain.css"></style>
