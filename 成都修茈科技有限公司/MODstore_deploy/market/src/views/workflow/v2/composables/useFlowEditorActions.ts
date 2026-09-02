/**
 * 工作流编辑器 · 画布/工具栏交互动作与模板弹窗（由 WorkflowFlowEditor.vue 原单文件机械迁出，行为不变）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { Connection, NodeChange, EdgeChange } from '@vue-flow/core'
import type { Ref } from 'vue'
import { api } from '../../../../api'
import { computeAutoLayout } from './useAutoLayout'
import type { NodeKind } from './useNodeRegistry'
import type { WorkflowFlowNode } from './useWorkflowGraph'
import type { useWorkflowGraph } from './useWorkflowGraph'
import type { useVueFlow } from '@vue-flow/core'

interface FlowEditorActionsDeps {
  props: { workflowId: number }
  graph: ReturnType<typeof useWorkflowGraph>
  flowInstance: ReturnType<typeof useVueFlow>
  selectedId: Ref<string | null>
}

export function useFlowEditorActions(deps: FlowEditorActionsDeps) {
  const { props, graph, flowInstance, selectedId } = deps

  const flash = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const sandboxResult = ref<unknown>(null)
  const versionsOpen = ref(false)

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
      } catch {
        /* empty */
      }
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
    await Promise.allSettled(graph.nodes.value.map((n) => graph.flushNodePosition(n.id)))
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
      const r = (await api.executeWorkflow(props.workflowId, {})) as { id?: number | string }
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
      const r = (await api.publishWorkflowVersion(props.workflowId, note.trim())) as {
        version_no?: number | string
      }
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
    saveAsTemplateModal.value.name = graph.meta.value?.name ? `${graph.meta.value.name} 模板` : ''
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
      const r = (await api.saveWorkflowAsTemplate(props.workflowId, {
        name: m.name.trim(),
        description: m.description.trim(),
        template_category: m.template_category,
        template_difficulty: m.template_difficulty,
        is_public: m.is_public,
        price: 0,
      })) as { id?: number | string }
      m.open = false
      showFlash('ok', `已发布为模板（id ${r?.id ?? '?'}）`)
    } catch (e) {
      showFlash('err', '发布模板失败：' + explainError(e))
    } finally {
      m.busy = false
    }
  }

  return {
    flash,
    sandboxResult,
    versionsOpen,
    saveAsTemplateModal,
    TEMPLATE_CATEGORIES,
    TEMPLATE_DIFFICULTIES,
    onNodesChange,
    onEdgesChange,
    onPaneClick,
    onNodeClick,
    onNodeDragStop,
    onConnect,
    onEdgeDoubleClick,
    onAddFromLibrary,
    onCanvasDragOver,
    onCanvasDrop,
    onPatchNode,
    onDeleteSelected,
    onAutoLayout,
    onSandbox,
    onExecute,
    onRename,
    onToggleActive,
    onPublish,
    onShowVersions,
    onRolledBack,
    onSaveAsTemplate,
    submitSaveAsTemplate,
  }
}
