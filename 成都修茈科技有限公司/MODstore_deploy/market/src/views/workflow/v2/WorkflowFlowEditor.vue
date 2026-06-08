<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  VueFlow,
  useVueFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeTypesObject,
} from '@vue-flow/core'
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
import { computeAutoLayout } from './composables/useAutoLayout'
import { type NodeKind } from './composables/useNodeRegistry'
import { api } from '../../../api'

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
const flash = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const sandboxResult = ref<unknown>(null)
const versionsOpen = ref(false)

const flowInstance = useVueFlow({ id: `wf2-${props.workflowId}` })

const nodeTypes = { mod: GenericNode } as unknown as NodeTypesObject

const selectedNode = computed<WorkflowFlowNode | null>(() => {
  if (!selectedId.value) return null
  return graph.nodes.value.find((n) => n.id === selectedId.value) || null
})

function showFlash(kind: 'ok' | 'err', text: string, ms = 2400) {
  flash.value = { kind, text }
  setTimeout(() => {
    if (flash.value && flash.value.text === text) flash.value = null
  }, ms)
}

function explainError(e: unknown): string {
  if (!e) return '未知错误'
  if (typeof e === 'string') return e
  const anyE = e as { message?: string; detail?: unknown }
  if (anyE.detail) return typeof anyE.detail === 'string' ? anyE.detail : JSON.stringify(anyE.detail)
  if (anyE.message) return anyE.message
  try {
    return JSON.stringify(e)
  } catch {
    return String(e)
  }
}

onMounted(async () => {
  try {
    await graph.loadGraph()
  } catch (e) {
    showFlash('err', '加载失败：' + explainError(e), 4000)
  }
})

onBeforeUnmount(() => {
  selectedId.value = null
})

function onNodesChange(changes: NodeChange[]) {
  flowInstance.applyNodeChanges(changes)
}

function onEdgesChange(changes: EdgeChange[]) {
  flowInstance.applyEdgeChanges(changes)
}

function onPaneClick() {
  selectedId.value = null
}

function onNodeClick(ev: { node: WorkflowFlowNode }) {
  selectedId.value = ev.node.id
}

async function onNodeDragStop(ev: { node: WorkflowFlowNode }) {
  const live = flowInstance.findNode(ev.node.id)
  if (live) {
    graph.updateNodePositionLocally(ev.node.id, { x: live.position.x, y: live.position.y })
  }
  await graph.flushNodePosition(ev.node.id)
}

async function onConnect(conn: Connection) {
  if (!conn.source || !conn.target) return
  try {
    await graph.addEdge(conn.source, conn.target, conn.sourceHandle ?? null)
  } catch (e) {
    showFlash('err', '添加连线失败：' + explainError(e))
  }
}

async function onEdgeDoubleClick(ev: { edge: { id: string } }) {
  if (!confirm('删除这条连线？')) return
  await graph.deleteEdge(ev.edge.id)
}

function projectFromClient(clientX: number, clientY: number) {
  if (typeof flowInstance.screenToFlowCoordinate === 'function') {
    return flowInstance.screenToFlowCoordinate({ x: clientX, y: clientY })
  }
  return flowInstance.project({ x: clientX, y: clientY })
}

async function addNodeAt(kind: NodeKind, clientX?: number, clientY?: number) {
  let position = { x: 80, y: 80 }
  if (typeof clientX === 'number' && typeof clientY === 'number') {
    try {
      position = projectFromClient(clientX, clientY) || position
    } catch {}
  } else {
    position = { x: 120 + Math.random() * 60, y: 120 + Math.random() * 60 }
  }
  try {
    const id = await graph.addNode(kind, position)
    selectedId.value = id
  } catch (e) {
    showFlash('err', '添加节点失败：' + explainError(e))
  }
}

function onAddFromLibrary(kind: NodeKind) {
  void addNodeAt(kind)
}

function onCanvasDragOver(ev: DragEvent) {
  if (ev.dataTransfer?.types.includes('application/wf2-node-kind')) {
    ev.preventDefault()
    ev.dataTransfer.dropEffect = 'move'
  }
}

function onCanvasDrop(ev: DragEvent) {
  const kind = ev.dataTransfer?.getData('application/wf2-node-kind') as NodeKind | ''
  if (!kind) return
  ev.preventDefault()
  void addNodeAt(kind, ev.clientX, ev.clientY)
}

function onPatchNode(payload: { id: string; label?: string; config?: Record<string, unknown> }) {
  const target = graph.nodes.value.find((n) => n.id === payload.id)
  if (!target) return
  graph.patchNodeData(payload.id, {
    ...(payload.label !== undefined ? { label: payload.label } : {}),
    ...(payload.config !== undefined ? { config: payload.config } : {}),
  })
}

async function onDeleteSelected(id: string) {
  if (!confirm('确认删除该节点及其连接？')) return
  await graph.deleteNode(id)
  selectedId.value = null
}

async function onAutoLayout() {
  if (!graph.nodes.value.length) return
  const positions = computeAutoLayout(graph.nodes.value, graph.edges.value, { direction: 'LR' })
  for (const n of graph.nodes.value) {
    const p = positions.get(n.id)
    if (!p) continue
    graph.updateNodePositionLocally(n.id, p)
  }
  await Promise.allSettled(
    graph.nodes.value.map((n) => graph.flushNodePosition(n.id)),
  )
  if (typeof flowInstance.fitView === 'function') {
    flowInstance.fitView({ padding: 0.18 })
  }
  showFlash('ok', '已重新布局')
}

async function onSandbox() {
  try {
    sandboxResult.value = await api.workflowSandboxRun(props.workflowId, {
      input_data: {},
      mock_employees: true,
      validate_only: false,
    })
    showFlash('ok', '沙盒运行完成（点结果面板查看）')
  } catch (e) {
    showFlash('err', '沙盒运行失败：' + explainError(e))
  }
}

async function onExecute() {
  if (!confirm('立即执行当前工作流？将真实调用员工和外部资源。')) return
  try {
    const r: any = await api.executeWorkflow(props.workflowId, {})
    showFlash('ok', `执行已提交（execution #${r?.id ?? '?'}）`)
  } catch (e) {
    showFlash('err', '执行失败：' + explainError(e))
  }
}

async function onRename() {
  if (!graph.meta.value) return
  const next = prompt('修改工作流名称', graph.meta.value.name || '')
  if (next === null) return
  await graph.renameWorkflow(next.trim() || graph.meta.value.name, graph.meta.value.description)
}

async function onToggleActive() {
  const m = graph.meta.value
  if (!m) return
  try {
    await api.updateWorkflow(props.workflowId, m.name, m.description, !m.is_active)
    m.is_active = !m.is_active
    showFlash('ok', m.is_active ? '已激活' : '已停用')
  } catch (e) {
    showFlash('err', '切换状态失败：' + explainError(e))
  }
}

async function onPublish() {
  if (!graph.nodes.value.length) {
    showFlash('err', '画布为空，无法发布')
    return
  }
  const note = prompt('为本次发布写一段备注（可留空）', '')
  if (note === null) return
  try {
    const r: any = await api.publishWorkflowVersion(props.workflowId, note.trim())
    showFlash('ok', `已发布 v${r?.version_no ?? '?'}`)
  } catch (e) {
    showFlash('err', '发布失败：' + explainError(e))
  }
}

function onShowVersions() {
  versionsOpen.value = true
}

async function onRolledBack(versionNo: number) {
  await graph.loadGraph()
  selectedId.value = null
  showFlash('ok', `已回滚到 v${versionNo}`)
}

const saveAsTemplateModal = ref<{
  open: boolean
  busy: boolean
  name: string
  description: string
  template_category: string
  template_difficulty: string
  is_public: boolean
}>({
  open: false,
  busy: false,
  name: '',
  description: '',
  template_category: '通用',
  template_difficulty: 'intermediate',
  is_public: true,
})

const TEMPLATE_CATEGORIES = ['客服', '营销', '数据分析', 'HR', '电商', '内容创作', '研发工程', '通用']
const TEMPLATE_DIFFICULTIES = [
  { value: 'beginner', label: '新手' },
  { value: 'intermediate', label: '进阶' },
  { value: 'advanced', label: '专家' },
]

function onSaveAsTemplate() {
  if (!graph.nodes.value.length) {
    showFlash('err', '画布为空，无法发布为模板')
    return
  }
  saveAsTemplateModal.value.open = true
  saveAsTemplateModal.value.name = graph.meta.value?.name
    ? `${graph.meta.value.name} 模板`
    : ''
  saveAsTemplateModal.value.description = graph.meta.value?.description || ''
}

async function submitSaveAsTemplate() {
  const m = saveAsTemplateModal.value
  if (!m.name.trim()) {
    showFlash('err', '请填写模板名称')
    return
  }
  m.busy = true
  try {
    const r: any = await api.saveWorkflowAsTemplate(props.workflowId, {
      name: m.name.trim(),
      description: m.description.trim(),
      template_category: m.template_category,
      template_difficulty: m.template_difficulty,
      is_public: m.is_public,
      price: 0,
    })
    m.open = false
    showFlash('ok', `已发布为模板（id ${r?.id ?? '?'}）`)
  } catch (e) {
    showFlash('err', '发布模板失败：' + explainError(e))
  } finally {
    m.busy = false
  }
}
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

    <VersionsPanel
      :workflow-id="workflowId"
      :open="versionsOpen"
      @close="versionsOpen = false"
      @rolled-back="onRolledBack"
    />

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
          <MiniMap
            position="bottom-right"
            :node-color="(n: any) => n?.data?.kind ? '#6366f1' : '#94a3b8'"
            pannable
            zoomable
          />
        </VueFlow>

        <div v-if="graph.loading.value" class="wf2-canvas-overlay">加载中...</div>
        <div v-else-if="!graph.nodes.value.length" class="wf2-canvas-empty">
          <div class="wf2-canvas-empty__inner">
            <h3>从左侧拖入节点开始编排</h3>
            <p>第一个节点建议是「开始」或某个触发器</p>
          </div>
        </div>
      </div>

      <PropertiesPanel
        :selected="selectedNode"
        @patch="onPatchNode"
        @delete="onDeleteSelected"
      />

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
      <div
        v-if="saveAsTemplateModal.open"
        class="wf2-tplmask"
        @click.self="saveAsTemplateModal.open = saveAsTemplateModal.busy"
      >
        <div class="wf2-tplcard">
          <header class="wf2-tplcard__head">
            <h3>发布为模板</h3>
            <button
              class="wf2-tb-btn"
              type="button"
              :disabled="saveAsTemplateModal.busy"
              @click="saveAsTemplateModal.open = false"
            >
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
            <button
              class="wf2-tb-btn"
              type="button"
              :disabled="saveAsTemplateModal.busy"
              @click="saveAsTemplateModal.open = false"
            >
              取消
            </button>
            <button
              class="wf2-tb-btn wf2-tb-btn--primary"
              type="button"
              :disabled="saveAsTemplateModal.busy"
              @click="submitSaveAsTemplate"
            >
              {{ saveAsTemplateModal.busy ? '发布中…' : '发布' }}
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </section>
</template>

<style scoped>
/* ===== 工作流编辑器深色主题变量 ===== */
.wf2 {
  --wf-canvas-bg: #0b1120;
  --wf-panel-bg: rgba(15, 23, 42, 0.88);
  --wf-panel-border: rgba(148, 163, 184, 0.10);
  --wf-text-primary: #f1f5f9;
  --wf-text-secondary: #94a3b8;
  --wf-text-muted: #64748b;
  --wf-accent: #6366f1;
  --wf-accent-glow: rgba(99, 102, 241, 0.35);

  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--wf-canvas-bg);
}

/* Flash 提示 */
.wf2-flash {
  position: absolute;
  top: 70px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  z-index: 30;
  backdrop-filter: blur(12px);
  animation: wf2-flash-slide 0.3s ease;
}

@keyframes wf2-flash-slide {
  from {
    opacity: 0;
    transform: translateX(-50%) translateY(-12px);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
}

.wf2-flash--ok {
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.25);
  color: #4ade80;
  box-shadow: 0 0 20px rgba(34, 197, 94, 0.15);
}

.wf2-flash--err {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #f87171;
  box-shadow: 0 0 20px rgba(239, 68, 68, 0.15);
}

.wf2-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.wf2-canvas-wrap {
  flex: 1;
  position: relative;
  min-width: 0;
  background: var(--wf-canvas-bg);
}

/* 覆盖 Vue Flow 默认背景与连线 */
:deep(.vue-flow__container) {
  background: var(--wf-canvas-bg) !important;
}

:deep(.vue-flow__edge path) {
  stroke: rgba(148, 163, 184, 0.35);
  stroke-width: 2;
  transition: stroke 0.2s ease;
}

:deep(.vue-flow__edge.selected path),
:deep(.vue-flow__edge:hover path) {
  stroke: rgba(99, 102, 241, 0.7);
  stroke-width: 2.5;
  filter: drop-shadow(0 0 4px rgba(99, 102, 241, 0.4));
}

:deep(.vue-flow__edge-text) {
  fill: #94a3b8;
  font-size: 11px;
}

:deep(.vue-flow__controls) {
  background: rgba(15, 23, 42, 0.8) !important;
  backdrop-filter: blur(12px);
  border: 1px solid rgba(148, 163, 184, 0.12) !important;
  border-radius: 10px !important;
  box-shadow: 0 8px 24px -8px rgba(0, 0, 0, 0.4) !important;
}

:deep(.vue-flow__controls-button) {
  background: transparent !important;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08) !important;
  color: #94a3b8 !important;
}

:deep(.vue-flow__controls-button:hover) {
  background: rgba(148, 163, 184, 0.1) !important;
  color: #f1f5f9 !important;
}

:deep(.vue-flow__controls-button svg) {
  fill: currentColor;
}

:deep(.vue-flow__minimap) {
  background: rgba(15, 23, 42, 0.7) !important;
  border: 1px solid rgba(148, 163, 184, 0.1) !important;
  border-radius: 10px !important;
}

.wf2-canvas-overlay,
.wf2-canvas-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  color: var(--wf-text-muted);
}

.wf2-canvas-empty__inner {
  background: rgba(30, 41, 59, 0.7);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(148, 163, 184, 0.12);
  padding: 32px 40px;
  border-radius: 16px;
  text-align: center;
  pointer-events: auto;
  box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.5);
}

.wf2-canvas-empty__inner h3 {
  margin: 0 0 8px;
  font-size: 18px;
  color: var(--wf-text-primary);
  font-weight: 600;
}

.wf2-canvas-empty__inner p {
  margin: 0;
  font-size: 13px;
  color: var(--wf-text-secondary);
}

/* 沙盒结果面板 */
.wf2-sandbox-panel {
  position: absolute;
  right: 16px;
  top: 100px;
  width: 380px;
  max-height: calc(100vh - 140px);
  background: var(--wf-panel-bg);
  backdrop-filter: blur(16px);
  border: 1px solid var(--wf-panel-border);
  border-radius: 14px;
  box-shadow: 0 24px 48px -12px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  z-index: 20;
}

.wf2-sandbox-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--wf-panel-border);
}

.wf2-sandbox-panel__head h4 {
  margin: 0;
  font-size: 14px;
  color: var(--wf-text-primary);
  font-weight: 600;
}

.wf2-tb-btn {
  font-size: 12px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(30, 41, 59, 0.6);
  color: var(--wf-text-secondary);
  padding: 5px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.wf2-tb-btn:hover {
  background: rgba(148, 163, 184, 0.15);
  color: var(--wf-text-primary);
}

.wf2-sandbox-panel__pre {
  margin: 0;
  padding: 12px 16px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--wf-text-primary);
  background: rgba(15, 23, 42, 0.5);
  white-space: pre-wrap;
  overflow: auto;
  border-radius: 0 0 14px 14px;
}

/* 模板弹窗 */
.wf2-tplmask {
  position: fixed;
  inset: 0;
  background: rgba(2, 6, 23, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
  padding: 16px;
}

.wf2-tplcard {
  width: min(520px, 100%);
  background: rgba(30, 41, 59, 0.95);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 16px;
  box-shadow: 0 32px 64px -16px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
}

.wf2-tplcard__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.10);
}

.wf2-tplcard__head h3 {
  margin: 0;
  font-size: 16px;
  color: var(--wf-text-primary);
  font-weight: 600;
}

.wf2-tplcard__body {
  padding: 16px 20px;
}

.wf2-tplcard__foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid rgba(148, 163, 184, 0.10);
}

.wf2-tplfield {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}

.wf2-tplfield span {
  font-size: 13px;
  color: var(--wf-text-secondary);
  font-weight: 500;
}

.wf2-tplfield input,
.wf2-tplfield textarea,
.wf2-tplfield select {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
  font-family: inherit;
  color: var(--wf-text-primary);
  background: rgba(15, 23, 42, 0.6);
  transition: all 0.2s ease;
}

.wf2-tplfield input::placeholder,
.wf2-tplfield textarea::placeholder {
  color: var(--wf-text-muted);
}

.wf2-tplfield input:focus,
.wf2-tplfield textarea:focus,
.wf2-tplfield select:focus {
  outline: none;
  border-color: var(--wf-accent);
  box-shadow: 0 0 0 3px var(--wf-accent-glow);
  background: rgba(15, 23, 42, 0.8);
}

.wf2-tplfield--inline {
  flex-direction: row;
  align-items: center;
  gap: 10px;
}

.wf2-tplrow {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.wf2-fade-enter-active,
.wf2-fade-leave-active {
  transition: opacity 0.2s ease;
}

.wf2-fade-enter-from,
.wf2-fade-leave-to {
  opacity: 0;
}
</style>
