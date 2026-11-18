<template>
  <Trace :class="['asc-chain', `is-${state}`]" data-testid="agent-step-chain">
    <TraceCollapsible :open="userOpen ?? autoOpen" @update:open="userOpen = $event">
      <TraceCollapsibleTrigger class="asc-summary">
        <TraceLine :status="traceStatus(state)">
          <TraceIcon><i class="fa fa-sitemap"></i></TraceIcon>
          <TraceTitle class="asc-title">执行链</TraceTitle>
          <TraceDescription>{{ steps.length }} 步</TraceDescription>
          <span :class="['asc-pill', `is-${state}`]">{{ stateLabel }}</span>
          <TraceDescription v-if="durationLabel">{{ durationLabel }}</TraceDescription>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <ol class="asc-steps">
          <li v-for="step in steps" :key="step.id" :class="['asc-step', `is-${step.state}`]">
            <component :is="hasDetails(step) ? TraceCollapsible : 'div'" :class="{ 'asc-step-details': hasDetails(step) }">
              <component
                :is="hasDetails(step) ? TraceCollapsibleTrigger : 'div'"
                class="asc-step-row"
                :class="{ 'is-static': !hasDetails(step) }"
              >
                <TraceLine :status="traceStatus(step.state)" class="asc-step-line">
                  <TraceIcon><i class="fa" :class="iconFor(step)"></i></TraceIcon>
                  <TraceTitle>{{ step.title }}</TraceTitle>
                  <TraceDescription v-if="step.subtitle" class="asc-step-subtitle">{{ step.subtitle }}</TraceDescription>
                  <span v-if="step.retries" class="asc-badge">重试 {{ step.retries }}</span>
                  <TraceDescription v-if="step.durationMs" class="asc-step-duration">{{
                    formatStepDuration(step.durationMs)
                  }}</TraceDescription>
                  <TraceIcon class="asc-step-status"><i class="fa" :class="stepStateIcon(step.state)"></i></TraceIcon>
                  <span class="sr-only">{{ stepStateLabel(step.state) }}</span>
                </TraceLine>
              </component>
              <p v-if="(step.state === 'running' || step.state === 'unknown') && step.hint" class="asc-live-hint" role="status">
                {{ step.hint }}
              </p>
              <div v-if="step.progress !== undefined" class="asc-progress">
                <progress :value="step.progress" max="100" :aria-label="`${step.title}进度`"></progress>
                <span>{{ step.progress }}%</span>
                <span v-if="step.processedRows !== undefined && step.totalRows !== undefined"
                  >已处理 {{ step.processedRows }} / {{ step.totalRows }} 行</span
                >
              </div>
              <TraceCollapsibleContent v-if="hasDetails(step)">
                <div class="asc-step-body">
                  <p v-if="step.retries">已重试 {{ step.retries }} 次</p>
                  <section v-if="step.output" class="asc-section">
                    <div class="asc-label">输出</div>
                    <pre>{{ step.output }}</pre>
                  </section>
                  <section v-if="step.error" class="asc-section is-error">
                    <div class="asc-label">错误</div>
                    <pre>{{ step.error }}</pre>
                  </section>
                  <section v-if="step.hint && step.state !== 'running' && step.state !== 'unknown'" class="asc-section">
                    <div class="asc-label">建议</div>
                    <p>{{ step.hint }}</p>
                  </section>
                </div>
              </TraceCollapsibleContent>
            </component>
          </li>
        </ol>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  </Trace>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from '@/components/ui/trace'
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
const autoOpen = computed(() => ['running', 'waiting', 'unknown', 'failed'].includes(state.value))
const userOpen = ref<boolean>()

function traceStatus(value: AgentStepState): 'running' | 'error' | 'pending' | undefined {
  if (value === 'failed' || value === 'blocked') return 'error'
  if (value === 'waiting' || value === 'unknown') return 'pending'
  return value === 'success' ? undefined : value
}

function hasDetails(step: AgentStepView): boolean {
  return hasStepDetails({ ...step, hint: step.state === 'running' || step.state === 'unknown' ? undefined : step.hint })
}

function iconFor(step: AgentStepView): string {
  if (step.live && step.state === 'running') return 'fa-circle-o-notch fa-spin'
  return toolIconClass(step.toolId, step.action)
}
</script>

<style scoped src="./AgentStepChain.css"></style>
