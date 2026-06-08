<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../../../../api'

const props = defineProps<{
  workflowId: number
}>()

interface Step {
  order: number
  node_id: number
  node_type: string
  node_name: string
  duration_ms: number
  input_snapshot: Record<string, unknown>
  output_delta: Record<string, unknown>
  edge_taken: { edge_id: number; condition: string | null; matched: boolean } | null
}

interface Execution {
  id: number
  status: string
  steps: Step[]
  output: Record<string, unknown>
  created_at: string
}

const executions = ref<Execution[]>([])
const selectedExecId = ref<number | null>(null)
const currentStep = ref(0)
const playing = ref(false)
const loading = ref(false)

const selectedExec = computed(() =>
  executions.value.find((e) => e.id === selectedExecId.value) || null,
)

const steps = computed(() => selectedExec.value?.steps || [])

const currentNodeId = computed(() => {
  if (!steps.value.length || currentStep.value < 0) return null
  return steps.value[currentStep.value]?.node_id ?? null
})

async function loadExecutions() {
  loading.value = true
  try {
    const res = await api.get(`/api/workflow/${props.workflowId}/executions`, {
      params: { limit: 20 },
    })
    executions.value = res.data?.items || res.data || []
  } catch {
    executions.value = []
  } finally {
    loading.value = false
  }
}

function selectExecution(id: number) {
  selectedExecId.value = id
  currentStep.value = 0
  playing.value = false
}

function stepForward() {
  if (currentStep.value < steps.value.length - 1) {
    currentStep.value++
  } else {
    playing.value = false
  }
}

function stepBackward() {
  if (currentStep.value > 0) {
    currentStep.value--
  }
}

function togglePlay() {
  if (playing.value) {
    playing.value = false
    return
  }
  playing.value = true
  const interval = setInterval(() => {
    if (!playing.value || currentStep.value >= steps.value.length - 1) {
      playing.value = false
      clearInterval(interval)
      return
    }
    currentStep.value++
  }, 800)
}

function nodeStatus(nodeId: number): 'success' | 'failed' | 'running' | 'pending' {
  if (nodeId === currentNodeId.value) return 'running'
  const stepIndex = steps.value.findIndex((s) => s.node_id === nodeId)
  if (stepIndex < 0) return 'pending'
  if (stepIndex < currentStep.value) return 'success'
  return 'pending'
}

loadExecutions()
</script>

<template>
  <div class="execution-replay">
    <div class="panel-header">
      <h3>执行回放</h3>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!executions.length" class="empty-hint">
      暂无执行记录
    </div>

    <template v-else>
      <div class="exec-selector">
        <select v-model="selectedExecId" @change="selectExecution(selectedExecId!)">
          <option v-for="e in executions" :key="e.id" :value="e.id">
            #{{ e.id }} - {{ e.status }} - {{ e.created_at?.slice(0, 19) }}
          </option>
        </select>
      </div>

      <div v-if="selectedExec" class="replay-controls">
        <button @click="stepBackward" :disabled="currentStep <= 0">◀</button>
        <button @click="togglePlay">{{ playing ? '⏸' : '▶' }}</button>
        <button @click="stepForward" :disabled="currentStep >= steps.length - 1">▶</button>
        <span class="step-counter">{{ currentStep + 1 }} / {{ steps.length }}</span>
      </div>

      <div v-if="selectedExec && steps.length" class="step-detail">
        <div class="step-header">
          <span class="step-order">#{{ steps[currentStep]?.order }}</span>
          <span class="step-name">{{ steps[currentStep]?.node_name }}</span>
          <span class="step-type">({{ steps[currentStep]?.node_type }})</span>
          <span class="step-duration">{{ steps[currentStep]?.duration_ms?.toFixed(1) }}ms</span>
        </div>
        <div class="step-data">
          <details>
            <summary>输入</summary>
            <pre>{{ JSON.stringify(steps[currentStep]?.input_snapshot, null, 2) }}</pre>
          </details>
          <details>
            <summary>输出</summary>
            <pre>{{ JSON.stringify(steps[currentStep]?.output_delta, null, 2) }}</pre>
          </details>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.execution-replay {
  padding: 12px;
  font-size: 13px;
}
.panel-header {
  margin-bottom: 12px;
}
.panel-header h3 {
  margin: 0;
  font-size: 14px;
}
.loading, .empty-hint {
  color: #9ca3af;
  text-align: center;
  padding: 20px 0;
}
.exec-selector select {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 12px;
  margin-bottom: 10px;
}
.replay-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.replay-controls button {
  padding: 4px 10px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
}
.replay-controls button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.step-counter {
  font-size: 12px;
  color: #6b7280;
  margin-left: auto;
}
.step-detail {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 10px;
}
.step-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.step-order {
  font-weight: 600;
}
.step-name {
  font-weight: 500;
}
.step-type {
  color: #6b7280;
  font-size: 11px;
}
.step-duration {
  margin-left: auto;
  font-size: 11px;
  color: #6b7280;
}
.step-data pre {
  background: #f8fafc;
  padding: 8px;
  border-radius: 4px;
  font-size: 11px;
  max-height: 200px;
  overflow: auto;
}
.step-data details {
  margin-bottom: 6px;
}
.step-data summary {
  cursor: pointer;
  font-size: 12px;
  color: #4b5563;
}
</style>
