<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ElTag } from 'element-plus'
import type { AgentRunStep } from '@/api/agentRuns'
import { taskStatusLabel } from '@/utils/taskWorkspacePresentation'
import { executionGraph } from './executionGraph'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const props = defineProps<{ steps: AgentRunStep[]; runId: string }>()
const id = `employee-execution-${props.runId}`
const { fitView } = useVueFlow(id)
const graph = computed(() => executionGraph(props.steps))
const selectedId = ref('')
const selected = computed(() => props.steps.find((s) => (s.node_id || s.step_id) === selectedId.value))
watch(
  () => props.steps.map((s) => `${s.node_id}:${s.depends_on?.join(',')}`).join('|'),
  async () => {
    await nextTick()
    void fitView({ padding: 0.3, maxZoom: 1 })
  },
)
</script>
<template>
  <div class="execution-canvas" aria-label="任务执行流程图">
    <VueFlow
      :id="id"
      :nodes="graph.nodes"
      :edges="graph.edges"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :edges-updatable="false"
      :min-zoom="0.2"
      :max-zoom="1.2"
      :fit-view-on-init="true"
      :default-viewport="{ x: 0, y: 0, zoom: 0.8 }"
      @node-click="selectedId = $event.node.id"
    >
      <Background pattern-color="#dce3ed" :gap="22" />
      <Controls :show-interactive="false" />
      <MiniMap :pannable="true" :zoomable="true" />
    </VueFlow>
    <div v-if="selected" class="execution-node-detail">
      <strong>{{ selected.description || selected.tool_id }}</strong
      ><el-tag size="small">{{ taskStatusLabel(selected.status) }}</el-tag
      ><span v-if="selected.error" role="alert">{{ selected.error }}</span>
    </div>
  </div>
</template>
<style scoped>
.execution-canvas {
  height: 100%;
  min-height: 240px;
  position: relative;
  background: #fbfcfe;
}
.execution-canvas :deep(.vue-flow__node-default) {
  white-space: pre-line;
  text-align: left;
  line-height: 1.8;
  font-size: 12px;
  border-radius: 10px;
  padding: 16px;
  width: 220px;
  box-shadow: 0 3px 12px #1e293b08;
}
.execution-canvas :deep(.vue-flow__minimap) {
  width: 130px;
  height: 85px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow: hidden;
}
.execution-canvas :deep(.vue-flow__controls) {
  box-shadow: 0 1px 8px #1e293b14;
  border-radius: 6px;
  overflow: hidden;
}
.execution-node-detail {
  position: absolute;
  left: 16px;
  right: 16px;
  top: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  background: white;
  border: 1px solid #dce3ed;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
  z-index: 5;
}
.execution-node-detail > span[role='alert'] {
  width: 100%;
  color: #b42318;
}
@media (max-width: 680px) {
  .execution-canvas :deep(.vue-flow__minimap) {
    display: none;
  }
}
</style>
