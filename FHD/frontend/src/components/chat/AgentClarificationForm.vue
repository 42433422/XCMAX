<template>
  <form class="agent-clarification" @submit.prevent="submit">
    <p>{{ question.question }}</p>
    <template v-if="supported">
      <label v-for="field in question.fields" :key="field.key">
        {{ field.label }}
        <input v-model="answers[field.key]" :type="field.type === 'number' || field.type === 'integer' ? 'number' : 'text'"
          :step="field.type === 'integer' ? 1 : 'any'" required :disabled="busy || submitted" />
      </label>
      <button class="btn btn-primary btn-sm" type="submit" :disabled="busy || submitted">
        {{ submitted ? '已提交，等待任务继续' : busy ? '正在提交…' : '补充信息并继续' }}
      </button>
    </template>
    <p v-else>此问题需要补充明细，请打开任务对话查看。</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </form>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { agentRunsApi } from '@/api/agentRuns'

export interface ClarificationQuestion {
  step_id: string
  question: string
  fields: Array<{ key: string; label: string; type: string }>
}
const props = defineProps<{ runId: string; question: ClarificationQuestion }>()
const answers = reactive<Record<string, string | number>>({})
const busy = ref(false)
const submitted = ref(false)
const error = ref('')
const supported = computed(() => props.question.fields?.length > 0 && props.question.fields.every(field => ['string', 'number', 'integer'].includes(field.type)))
watch(() => `${props.runId}:${props.question.step_id}`, () => {
  Object.keys(answers).forEach(key => delete answers[key])
  submitted.value = false
  error.value = ''
})
async function submit() {
  if (busy.value || submitted.value || !supported.value) return
  const parameters: Record<string, unknown> = {}
  for (const field of props.question.fields) {
    const value = answers[field.key]
    if (value === undefined || String(value).trim() === '') { error.value = `请填写${field.label}`; return }
    if (field.type === 'string') parameters[field.key] = String(value).trim()
    else {
      const number = Number(value)
      if (!Number.isFinite(number) || (field.type === 'integer' && !Number.isInteger(number))) { error.value = `请检查${field.label}`; return }
      parameters[field.key] = number
    }
  }
  busy.value = true
  error.value = ''
  try {
    const response = await agentRunsApi.answerClarification(props.runId, { step_id: props.question.step_id, parameters })
    if (response.success === false) throw new Error(response.message || '提交失败，请重试')
    submitted.value = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '提交失败，请重试'
  } finally { busy.value = false }
}
</script>

<style scoped>
.agent-clarification { padding: 12px; border: 1px solid var(--border-color, #ddd); border-radius: 8px; }
label { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
input { padding: 8px; border: 1px solid var(--border-color, #ddd); border-radius: 4px; }
[role=alert] { color: var(--danger-color, #b42318); }
</style>
