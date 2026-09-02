<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：画布/工具栏交互动作与模板弹窗在 ./composables/useFlowEditorActions.ts，
// 样式在 ./workflowFlowEditor.css。
import { computed, ref } from 'vue'
import { VueFlow, useVueFlow, type NodeTypesObject } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import GenericNode from './nodes/GenericNode.vue'
import NodeLibraryPanel from './panels/NodeLibraryPanel.vue'
import PropertiesPanel from './panels/PropertiesPanel.vue'
import ToolbarPanel from './panels/ToolbarPanel.vue'
import VersionsPanel from './panels/VersionsPanel.vue'
import VariablesPanel from './panels/VariablesPanel.vue'
import ExecutionReplay from './panels/ExecutionReplay.vue'
import { useWorkflowGraph, type WorkflowFlowNode } from './composables/useWorkflowGraph'
import { useFlowEditorActions } from './composables/useFlowEditorActions'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const props = defineProps<{
  workflowId: number
}>()

const emit = defineEmits<{
  (e: 'back'): void
}>()

const graph = useWorkflowGraph(props.workflowId)
const selectedId = ref<string | null>(null)

const flowInstance = useVueFlow({ id: `wf2-${props.workflowId}` })

const nodeTypes = { mod: GenericNode } as unknown as NodeTypesObject

const selectedNode = computed<WorkflowFlowNode | null>(() => {
  if (!selectedId.value) return null
  return graph.nodes.value.find((n) => n.id === selectedId.value) || null
})

const {
  flash, sandboxResult, versionsOpen, saveAsTemplateModal,
  TEMPLATE_CATEGORIES, TEMPLATE_DIFFICULTIES,
  onNodesChange, onEdgesChange, onPaneClick, onNodeClick, onNodeDragStop,
  onConnect, onEdgeDoubleClick, onAddFromLibrary, onCanvasDragOver, onCanvasDrop,
  onPatchNode, onDeleteSelected, onAutoLayout, onSandbox, onExecute,
  onRename, onToggleActive, onPublish, onShowVersions, onRolledBack,
  onSaveAsTemplate, submitSaveAsTemplate,
} = useFlowEditorActions({ props, graph, flowInstance, selectedId })
</script>

<template>
  <section class="wf2">
    <ToolbarPanel
      :workflow-name="graph.meta.value?.name || ''"
      :saving="graph.saving.value"
      :is-active="!!graph.meta.value?.is_active"
      @back="emit('back')"
      @rename="onRename"
      @auto-layout="onAutoLayout"
      @sandbox="onSandbox"
      @execute="onExecute"
      @toggle-active="onToggleActive"
      @publish="onPublish"
      @versions="onShowVersions"
      @save-as-template="onSaveAsTemplate"
    />

    <VersionsPanel :workflow-id="workflowId" :open="versionsOpen" @close="versionsOpen = false" @rolled-back="onRolledBack" />

    <div v-if="flash" class="wf2-flash" :class="`wf2-flash--${flash.kind}`">
      {{ flash.text }}
    </div>

    <div class="wf2-body">
      <NodeLibraryPanel @add="onAddFromLibrary" />

      <div class="wf2-canvas-wrap" @dragover="onCanvasDragOver" @drop="onCanvasDrop">
        <VueFlow
          :id="`wf2-${props.workflowId}`"
          :nodes="graph.nodes.value"
          :edges="graph.edges.value"
          :node-types="nodeTypes"
          :default-edge-options="{ type: 'smoothstep' }"
          :delete-key-code="null"
          fit-view-on-init
          @nodes-change="onNodesChange"
          @edges-change="onEdgesChange"
          @node-drag-stop="onNodeDragStop"
          @node-click="onNodeClick"
          @pane-click="onPaneClick"
          @connect="onConnect"
          @edge-double-click="onEdgeDoubleClick"
        >
          <Background pattern-color="rgba(148,163,184,0.10)" :gap="20" />
          <Controls position="bottom-left" />
          <MiniMap position="bottom-right" :node-color="(n: any) => (n?.data?.kind ? '#6366f1' : '#94a3b8')" pannable zoomable />
        </VueFlow>

        <div v-if="graph.loading.value" class="wf2-canvas-overlay">加载中...</div>
        <div v-else-if="!graph.nodes.value.length" class="wf2-canvas-empty">
          <div class="wf2-canvas-empty__inner">
            <h3>从左侧拖入节点开始编排</h3>
            <p>第一个节点建议是「开始」或某个触发器</p>
          </div>
        </div>
      </div>

      <PropertiesPanel :selected="selectedNode" @patch="onPatchNode" @delete="onDeleteSelected" />

      <div class="wf2-right-panels">
        <VariablesPanel :nodes="graph.nodes.value" />
        <ExecutionReplay :workflow-id="workflowId" />
      </div>
    </div>

    <aside v-if="sandboxResult" class="wf2-sandbox-panel">
      <header class="wf2-sandbox-panel__head">
        <h4>沙盒结果</h4>
        <button class="wf2-tb-btn" type="button" @click="sandboxResult = null">关闭</button>
      </header>
      <pre class="wf2-sandbox-panel__pre">{{ JSON.stringify(sandboxResult, null, 2) }}</pre>
    </aside>

    <transition name="wf2-fade">
      <div v-if="saveAsTemplateModal.open" class="wf2-tplmask" @click.self="saveAsTemplateModal.open = saveAsTemplateModal.busy">
        <div class="wf2-tplcard">
          <header class="wf2-tplcard__head">
            <h3>发布为模板</h3>
            <button class="wf2-tb-btn" type="button" :disabled="saveAsTemplateModal.busy" @click="saveAsTemplateModal.open = false">
              关闭
            </button>
          </header>
          <div class="wf2-tplcard__body">
            <label class="wf2-tplfield">
              <span>模板名称</span>
              <input v-model="saveAsTemplateModal.name" type="text" placeholder="例如：客服 7 天分级回复" />
            </label>
            <label class="wf2-tplfield">
              <span>说明（可选）</span>
              <textarea v-model="saveAsTemplateModal.description" rows="3" />
            </label>
            <div class="wf2-tplrow">
              <label class="wf2-tplfield">
                <span>类别</span>
                <select v-model="saveAsTemplateModal.template_category">
                  <option v-for="c in TEMPLATE_CATEGORIES" :key="c" :value="c">{{ c }}</option>
                </select>
              </label>
              <label class="wf2-tplfield">
                <span>难度</span>
                <select v-model="saveAsTemplateModal.template_difficulty">
                  <option v-for="d in TEMPLATE_DIFFICULTIES" :key="d.value" :value="d.value">
                    {{ d.label }}
                  </option>
                </select>
              </label>
            </div>
            <label class="wf2-tplfield wf2-tplfield--inline">
              <input type="checkbox" v-model="saveAsTemplateModal.is_public" />
              <span>公开发布到模板市场</span>
            </label>
          </div>
          <footer class="wf2-tplcard__foot">
            <button class="wf2-tb-btn" type="button" :disabled="saveAsTemplateModal.busy" @click="saveAsTemplateModal.open = false">
              取消
            </button>
            <button class="wf2-tb-btn wf2-tb-btn--primary" type="button" :disabled="saveAsTemplateModal.busy" @click="submitSaveAsTemplate">
              {{ saveAsTemplateModal.busy ? '发布中…' : '发布' }}
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </section>
</template>

<style scoped src="./workflowFlowEditor.css"></style>
