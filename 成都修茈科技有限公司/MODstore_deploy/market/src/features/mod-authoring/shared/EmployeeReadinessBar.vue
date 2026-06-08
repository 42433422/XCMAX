<script setup lang="ts">
import { computed } from 'vue'
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

withDefaults(
  defineProps<{
    mode?: 'wizard' | 'expert'
  }>(),
  { mode: 'wizard' },
)

const {
  employeeReadiness,
  employeeReadinessGaps,
  readinessSummaryLabel,
  workflowEmployeesRows,
  closureBusy,
  patchWorkflowBusy,
  loading,
  runWorkflowEmployeeClosure,
  patchWorkflowEmployeeNodesRetry,
} = useModAuthoringContext()

const readinessBadgeOk = computed(
  () => workflowEmployeesRows.value.length > 0 && Boolean(employeeReadiness.value?.ok),
)
</script>

<template>
  <div v-if="employeeReadiness" class="readiness-panel readiness-panel--compact">
    <div class="readiness-head">
      <h3 class="sub-title readiness-title">员工</h3>
      <div class="readiness-head-aside">
        <button
          type="button"
          class="btn btn-sm btn-primary"
          :disabled="closureBusy || loading"
          @click="() => void runWorkflowEmployeeClosure()"
        >
          {{ closureBusy ? '处理中…' : '一键闭环' }}
        </button>
        <button
          v-if="mode === 'expert'"
          type="button"
          class="btn btn-sm btn-secondary"
          :disabled="patchWorkflowBusy || loading || closureBusy"
          @click="() => void patchWorkflowEmployeeNodesRetry()"
        >
          {{ patchWorkflowBusy ? '对齐中…' : '对齐画布' }}
        </button>
        <span :class="['readiness-badge', readinessBadgeOk ? 'readiness-badge-ok' : 'readiness-badge-warn']">
          {{
            workflowEmployeesRows.length === 0
              ? '待添加'
              : readinessBadgeOk
                ? '就绪'
                : readinessSummaryLabel
          }}
        </span>
      </div>
    </div>
    <ul v-if="employeeReadinessGaps.length" class="readiness-gaps">
      <li v-for="(gap, idx) in employeeReadinessGaps" :key="'gap-' + idx">{{ gap }}</li>
    </ul>
  </div>
</template>
