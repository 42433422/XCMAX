import { computed, ref, type Ref } from 'vue'
import { api } from '../api'
import { errMessage } from '../utils/errMessage'
import type { WorkflowEdgeRow, WorkflowNodeRow, WorkflowRow } from '../views/workflow/workflowTypes'

/** WorkflowView 编辑器画布域（自 WorkflowView.vue 原样迁移） */
export function useWorkflowEditor(deps: {
  loading: Ref<boolean>
  activeTab: Ref<string>
  flash: (msg: string, ok?: boolean) => void
  /** 沙盒域 loadDecomposeGraph 的懒引用（沙盒 composable 在本 composable 之后创建） */
  loadDecomposeGraph: (workflowId: number) => Promise<void>
}) {
  const { loading, activeTab, flash } = deps
  const loadDecomposeGraph = deps.loadDecomposeGraph

  // 编辑器状态
  const currentWorkflow = ref<WorkflowRow | null>(null)
  const nodes = ref<WorkflowNodeRow[]>([])
  const edges = ref<WorkflowEdgeRow[]>([])
  const focusedNodeId = ref(0)

  // 拖拽状态
  const dragging = ref(false)
  const dragNode = ref<WorkflowNodeRow | null>(null)
  const dragOffset = ref({ x: 0, y: 0 })

  // 连接状态
  const connecting = ref(false)
  const connectStart = ref<number | null>(null)
  const connectStartPort = ref('')

  // 弹窗状态
  const showNodeConfigModal = ref(false)
  const selectedNode = ref<WorkflowNodeRow | null>(null)
  const selectedNodeForTemplate = computed(() => {
    const n = selectedNode.value
    if (n) {
      if (!n.config) n.config = {}
      return n as WorkflowNodeRow & { config: Record<string, unknown> }
    }
    return { id: 0, name: '', node_type: '', config: {}, position_x: 0, position_y: 0 } as WorkflowNodeRow & {
      config: Record<string, unknown>
    }
  })

  // 画布引用
  const canvas = ref<HTMLElement | null>(null)
  const connections = ref<HTMLElement | null>(null)

  function onCollectionIdsInput(event: Event) {
    const target = event.target as HTMLInputElement | null
    selectedNodeForTemplate.value.config.collection_ids = String(target?.value || '')
      .split(',')
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isFinite(value) && value > 0)
  }

  function formatCollectionIds(value: unknown): string {
    return Array.isArray(value) ? value.map(String).join(',') : ''
  }

  // 获取节点类型标签
  function getNodeTypeLabel(type: string | undefined) {
    const labels: Record<string, string> = {
      start: '开始节点',
      end: '结束节点',
      employee: '员工节点',
      condition: '条件节点',
      knowledge_search: '知识检索节点'
    }
    return (type && labels[type]) || type || '未知节点'
  }

  // 添加节点
  function addNode(type: string) {
    const node = {
      id: Date.now(),
      node_type: type,
      name: getNodeTypeLabel(type),
      config: {},
      position_x: 100,
      position_y: 100
    }
    nodes.value.push(node)
  }

  // 添加员工节点
  function addEmployeeNode(employeeId: string | number, employeeName: string) {
    const node = {
      id: Date.now(),
      node_type: 'employee',
      name: employeeName,
      config: {
        employee_id: employeeId,
        task: 'analyze_document'
      },
      position_x: 100,
      position_y: 100
    }
    nodes.value.push(node)
  }

  // 添加知识检索节点（默认配置可在选中节点后编辑）
  function addKnowledgeSearchNode() {
    const node = {
      id: Date.now(),
      node_type: 'knowledge_search',
      name: '知识检索',
      config: {
        query: '',
        collection_ids: [],
        top_k: 6,
        min_score: 0,
        output_var: 'knowledge'
      },
      position_x: 100,
      position_y: 100
    }
    nodes.value.push(node)
  }

  // 删除节点
  function deleteNode(nodeId: number) {
    // 删除节点
    nodes.value = nodes.value.filter(node => node.id !== nodeId)
    // 删除相关的边
    edges.value = edges.value.filter(edge =>
      edge.source_node_id !== nodeId && edge.target_node_id !== nodeId
    )
  }

  // 显示节点配置
  function showNodeConfig(nodeId: number) {
    const node = nodes.value.find(n => n.id === nodeId)
    if (node) {
      selectedNode.value = JSON.parse(JSON.stringify(node))
      showNodeConfigModal.value = true
    }
  }

  // 保存节点配置
  function saveNodeConfig() {
    const sel = selectedNode.value
    if (sel) {
      const index = nodes.value.findIndex((n) => n.id === sel.id)
      if (index !== -1) {
        nodes.value[index] = JSON.parse(JSON.stringify(sel))
      }
      showNodeConfigModal.value = false
    }
  }

  // 开始拖拽
  function startDrag(event: MouseEvent, node: WorkflowNodeRow) {
    dragging.value = true
    dragNode.value = node
    const el = event.target as HTMLElement
    const rect = el.getBoundingClientRect()
    dragOffset.value = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top
    }
  }

  // 开始连接
  function startConnect(event: MouseEvent, nodeId: number, port: string) {
    connecting.value = true
    connectStart.value = nodeId
    connectStartPort.value = port
  }

  // 获取边的路径
  function getEdgePath(edge: WorkflowEdgeRow) {
    const sourceNode = nodes.value.find(n => n.id === edge.source_node_id)
    const targetNode = nodes.value.find(n => n.id === edge.target_node_id)
    if (!sourceNode || !targetNode) return ''

    return `M ${sourceNode.position_x + 100} ${sourceNode.position_y + 25} L ${targetNode.position_x} ${targetNode.position_y + 25}`
  }

  // 监听鼠标移动
  function selectEdge(edgeId: number) {
    void edgeId
  }

  function onMouseMove(event: MouseEvent) {
    if (!canvas.value) return
    if (dragging.value && dragNode.value) {
      const canvasRect = canvas.value.getBoundingClientRect()
      dragNode.value.position_x = event.clientX - canvasRect.left - dragOffset.value.x
      dragNode.value.position_y = event.clientY - canvasRect.top - dragOffset.value.y
    }
  }

  // 监听鼠标释放
  function onMouseUp() {
    dragging.value = false
    dragNode.value = null
    connecting.value = false
    connectStart.value = null
    connectStartPort.value = ''
  }

  // 监听点击
  function onCanvasClick(event: MouseEvent) {
    const t = event.target as HTMLElement | null
    if (!t?.closest('.workflow-node') && !t?.closest('.connection-line')) {
      // 点击空白处，取消选择
    }
  }

  // 编辑工作流
  async function editWorkflow(workflowId: number) {
    loading.value = true
    try {
      const res = await api.getWorkflow(workflowId)
      currentWorkflow.value = res
      nodes.value = res.nodes
      edges.value = res.edges
      activeTab.value = 'editor'
      await loadDecomposeGraph(workflowId)
    } catch (e: unknown) {
      flash('加载工作流失败: ' + errMessage(e), false)
    } finally {
      loading.value = false
    }
  }

  // 将画布节点/边同步到服务端（沙盒与生产执行均读服务端图）
  async function saveWorkflow() {
    if (!currentWorkflow.value) {
      flash('请先选择工作流', false)
      return
    }
    const wid = currentWorkflow.value.id
    loading.value = true
    try {
      const cur = await api.getWorkflow(wid)
      for (const n of cur.nodes || []) {
        await api.deleteWorkflowNode(n.id)
      }
      const idMap = new Map()
      for (const n of nodes.value) {
        const created = await api.addWorkflowNode(
          wid,
          String(n.node_type ?? 'start'),
          String(n.name ?? ''),
          n.config || {},
          n.position_x ?? 0,
          n.position_y ?? 0,
        )
        idMap.set(n.id, created.id)
      }
      for (const e of edges.value) {
        const s = idMap.get(e.source_node_id)
        const t = idMap.get(e.target_node_id)
        if (s && t) {
          await api.addWorkflowEdge(wid, s, t, e.condition || '')
        }
      }
      await editWorkflow(wid)
      flash('已同步到服务端，可进行沙盒测试或生产执行')
    } catch (e: unknown) {
      flash('保存失败: ' + errMessage(e), false)
    } finally {
      loading.value = false
    }
  }

  /** 仅重置本域内存态（原 resetAutomationWorkbenchLocalState 中的编辑器部分） */
  function reset() {
    currentWorkflow.value = null
    nodes.value = []
    edges.value = []
    focusedNodeId.value = 0
    dragging.value = false
    connecting.value = false
    connectStart.value = null
    connectStartPort.value = ''
    selectedNode.value = null
    showNodeConfigModal.value = false
  }

  return {
    currentWorkflow,
    nodes,
    edges,
    focusedNodeId,
    dragging,
    dragNode,
    dragOffset,
    connecting,
    connectStart,
    connectStartPort,
    showNodeConfigModal,
    selectedNode,
    selectedNodeForTemplate,
    canvas,
    connections,
    getNodeTypeLabel,
    addNode,
    addEmployeeNode,
    addKnowledgeSearchNode,
    deleteNode,
    showNodeConfig,
    saveNodeConfig,
    startDrag,
    startConnect,
    getEdgePath,
    selectEdge,
    onMouseMove,
    onMouseUp,
    onCanvasClick,
    onCollectionIdsInput,
    formatCollectionIds,
    editWorkflow,
    saveWorkflow,
    reset,
  }
}
