// 考试试跑流水线状态机：步骤流转、进度与面板可见性。
import { computed, ref } from 'vue'
import {
  computePipelinePercent,
  computePipelineStepViews,
  PIPELINE_JSON_FLOW,
  PIPELINE_WORD_FLOW,
  type PipelineStepId,
  type PipelineStepStatus,
} from './employeeExamTypes'

export function useEmployeeExamPipeline() {
  const pipelineFlow = ref<typeof PIPELINE_WORD_FLOW | typeof PIPELINE_JSON_FLOW>(PIPELINE_WORD_FLOW)
  const pipelineStatuses = ref<Record<PipelineStepId, PipelineStepStatus>>({
    word: 'pending',
    prepare_json: 'pending',
    report: 'pending',
    preview: 'pending',
  })
  const pipelineMessage = ref('')
  const pipelineVisible = ref(false)

  function resetPipeline(flow: typeof PIPELINE_WORD_FLOW | typeof PIPELINE_JSON_FLOW) {
    pipelineFlow.value = flow
    const statuses: Record<PipelineStepId, PipelineStepStatus> = {
      word: 'skipped',
      prepare_json: 'pending',
      report: 'pending',
      preview: 'pending',
    }
    for (const step of flow) {
      statuses[step.id] = 'pending'
    }
    for (const id of ['word', 'prepare_json', 'report', 'preview'] as PipelineStepId[]) {
      if (!flow.some((s) => s.id === id)) statuses[id] = 'skipped'
    }
    pipelineStatuses.value = statuses
    pipelineMessage.value = ''
    pipelineVisible.value = true
  }

  function setPipelineStep(id: PipelineStepId, status: PipelineStepStatus, message?: string) {
    pipelineStatuses.value = { ...pipelineStatuses.value, [id]: status }
    if (message !== undefined) pipelineMessage.value = message
  }

  const showPipelinePanel = computed(() => pipelineVisible.value)

  const pipelineStepViews = computed(() => computePipelineStepViews(pipelineFlow.value, pipelineStatuses.value))

  const pipelinePercent = computed(() => computePipelinePercent(pipelineFlow.value, pipelineStatuses.value))

  return {
    pipelineFlow,
    pipelineStatuses,
    pipelineMessage,
    pipelineVisible,
    resetPipeline,
    setPipelineStep,
    showPipelinePanel,
    pipelineStepViews,
    pipelinePercent,
  }
}
