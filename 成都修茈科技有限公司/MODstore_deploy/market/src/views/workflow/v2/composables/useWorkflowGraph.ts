/**
 * 后端 WorkflowNode/Edge ↔ Vue Flow nodes/edges 的双向适配 + 增量持久化。
 *
 * 设计原则：
 * - 不引入"大对象 putAll"，按现有 workflow_api 增量调用，避免后端再开新接口；
 * - 节点拖动结束（onNodeDragStop）→ PUT 节点位置；
 * - 节点配置面板改动 → debounce 后 PUT；
 * - 添加节点 → POST，并把后端返回的真实 id 写回 Vue Flow node.id；
 * - 添加边（onConnect）→ POST 边，拿回 id；删除边 → DELETE。
 *
 * Vue Flow 的 node.id 必须是字符串。我们用后端整数 id 转 string 做映射；
 * 新建节点提交前用 `tmp_<uuid>` 占位，POST 成功后替换。
 */

import { ref, shallowRef } from 'vue'
import { api } from '../../../../api'
import { getNodeMeta, type NodeKind } from './useNodeRegistry'
import type {
  BackendWorkflowEdge,
  BackendWorkflowNode,
  WorkflowFlowEdge,
  WorkflowFlowNode,
  WorkflowFlowNodeData,
} from '../../../../domain/workflow/types'

export type {
  BackendWorkflowEdge,
  BackendWorkflowNode,
  WorkflowFlowEdge,
  WorkflowFlowNode,
  WorkflowFlowNodeData,
}

/**
 * 历史代码用 `BackendNode` / `BackendEdge` 命名，保留别名以避免大范围 import 改动。
 * 新代码请直接使用 domain 类型 `BackendWorkflowNode` / `BackendWorkflowEdge`。
 */
export type BackendNode = BackendWorkflowNode
export type BackendEdge = BackendWorkflowEdge

function genTmpId(): string {
  return `tmp_${Math.random().toString(36).slice(2, 10)}_${Date.now()}`
}

function backendNodeToFlow(n: BackendWorkflowNode): WorkflowFlowNode {
  const meta = getNodeMeta(n.node_type)
  return {
    id: String(n.id),
    type: 'mod',
    position: { x: Number(n.position_x) || 0, y: Number(n.position_y) || 0 },
    data: {
      kind: (meta.kind || n.node_type) as NodeKind,
      label: n.name || meta.label,
      config: n.config || {},
      backendId: n.id,
    },
  }
}

function backendEdgeToFlow(e: BackendWorkflowEdge): WorkflowFlowEdge {
  const branch = (e.condition || '').trim()
  const sourceHandle =
    branch === 'true' ? 'true' : branch === 'false' ? 'false' : null
  return {
    id: String(e.id),
    source: String(e.source_node_id),
    target: String(e.target_node_id),
    sourceHandle,
    type: 'smoothstep',
    label: branch && branch !== 'true' && branch !== 'false' ? branch : undefined,
    data: { condition: e.condition || '', backendId: e.id },
  }
}

export function useWorkflowGraph(workflowId: number) {
  const nodes = ref<WorkflowFlowNode[]>([])
  const edges = ref<WorkflowFlowEdge[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const lastError = shallowRef<unknown>(null)
  const meta = ref<{ name: string; description: string; is_active: boolean } | null>(null)

  const debouncers = new Map<string, ReturnType<typeof setTimeout>>()

  async function loadGraph() {
    loading.value = true
    try {
      const detail: any = await api.getWorkflow(workflowId)
      meta.value = {
        name: detail.name || '',
        description: detail.description || '',
        is_active: !!detail.is_active,
      }
      nodes.value = (detail.nodes || []).map(backendNodeToFlow)
      edges.value = (detail.edges || []).map(backendEdgeToFlow)
    } catch (e) {
      lastError.value = e
      throw e
    } finally {
      loading.value = false
    }
  }

  async function addNode(kind: NodeKind, position: { x: number; y: number }) {
    const m = getNodeMeta(kind)
    const tmpId = genTmpId()
    const local: WorkflowFlowNode = {
      id: tmpId,
      type: 'mod',
      position,
      data: {
        kind,
        label: m.label,
        config: { ...m.defaultConfig },
        backendId: 0,
      },
    }
    nodes.value = [...nodes.value, local]

    saving.value = true
    try {
      const created: any = await api.addWorkflowNode(
        workflowId,
        kind,
        m.label,
        local.data!.config,
        position.x,
        position.y,
      )
      const realId = String(created.id)
      nodes.value = nodes.value.map((n): WorkflowFlowNode => {
        if (n.id !== tmpId) return n
        return {
          ...n,
          id: realId,
          data: { ...(n.data as WorkflowFlowNodeData), backendId: Number(created.id) },
        }
      })
      return realId
    } catch (e) {
      nodes.value = nodes.value.filter((n) => n.id !== tmpId)
      lastError.value = e
      throw e
    } finally {
      saving.value = false
    }
  }

  async function deleteNode(nodeId: string) {
    const target = nodes.value.find((n) => n.id === nodeId)
    if (!target || !target.data?.backendId) {
      nodes.value = nodes.value.filter((n) => n.id !== nodeId)
      return
    }
    saving.value = true
    try {
      await api.deleteWorkflowNode(target.data.backendId)
      nodes.value = nodes.value.filter((n) => n.id !== nodeId)
      edges.value = edges.value.filter((e) => e.source !== nodeId && e.target !== nodeId)
    } catch (e) {
      lastError.value = e
      throw e
    } finally {
      saving.value = false
    }
  }

  function updateNodePositionLocally(nodeId: string, position: { x: number; y: number }) {
    nodes.value = nodes.value.map((n): WorkflowFlowNode => {
      if (n.id !== nodeId) return n
      return { ...n, position }
    })
  }

  async function flushNodePosition(nodeId: string) {
    const n = nodes.value.find((x) => x.id === nodeId)
    if (!n || !n.data?.backendId) return
    saving.value = true
    try {
      await api.updateWorkflowNode(
        n.data.backendId,
        n.data.label,
        n.data.config,
        n.position.x,
        n.position.y,
      )
    } catch (e) {
      lastError.value = e
    } finally {
      saving.value = false
    }
  }

  function patchNodeData(nodeId: string, patch: Partial<WorkflowFlowNodeData>) {
    nodes.value = nodes.value.map((n): WorkflowFlowNode => {
      if (n.id !== nodeId) return n
      return { ...n, data: { ...(n.data as WorkflowFlowNodeData), ...patch } }
    })
    const existing = debouncers.get(nodeId)
    if (existing) clearTimeout(existing)
    const handle = setTimeout(() => {
      void flushNodeConfig(nodeId)
    }, 500)
    debouncers.set(nodeId, handle)
  }

  async function flushNodeConfig(nodeId: string) {
    const n = nodes.value.find((x) => x.id === nodeId)
    if (!n || !n.data?.backendId) return
    saving.value = true
    try {
      await api.updateWorkflowNode(
        n.data.backendId,
        n.data.label,
        n.data.config,
        n.position.x,
        n.position.y,
      )
    } catch (e) {
      lastError.value = e
    } finally {
      saving.value = false
    }
  }

  async function addEdge(
    source: string,
    target: string,
    sourceHandle?: string | null,
  ) {
    const sn = nodes.value.find((n) => n.id === source)
    const tn = nodes.value.find((n) => n.id === target)
    if (!sn?.data?.backendId || !tn?.data?.backendId) return
    if (sn.data.backendId === tn.data.backendId) return
    const condition = sourceHandle === 'true' || sourceHandle === 'false' ? sourceHandle : ''
    saving.value = true
    try {
      const created: any = await api.addWorkflowEdge(
        workflowId,
        sn.data.backendId,
        tn.data.backendId,
        condition,
      )
      edges.value = [
        ...edges.value,
        {
          id: String(created.id),
          source,
          target,
          sourceHandle: condition || null,
          type: 'smoothstep',
          data: { condition, backendId: Number(created.id) },
        },
      ]
    } catch (e) {
      lastError.value = e
      throw e
    } finally {
      saving.value = false
    }
  }

  async function deleteEdge(edgeId: string) {
    const target = edges.value.find((e) => e.id === edgeId)
    if (!target) return
    if (!target.data?.backendId) {
      edges.value = edges.value.filter((e) => e.id !== edgeId)
      return
    }
    saving.value = true
    try {
      await api.deleteWorkflowEdge(target.data.backendId)
      edges.value = edges.value.filter((e) => e.id !== edgeId)
    } catch (e) {
      lastError.value = e
    } finally {
      saving.value = false
    }
  }

  async function renameWorkflow(name: string, description: string) {
    if (!meta.value) return
    saving.value = true
    try {
      await api.updateWorkflow(workflowId, name, description, meta.value.is_active)
      meta.value = { ...meta.value, name, description }
    } catch (e) {
      lastError.value = e
    } finally {
      saving.value = false
    }
  }

  return {
    nodes,
    edges,
    loading,
    saving,
    meta,
    lastError,
    loadGraph,
    addNode,
    deleteNode,
    updateNodePositionLocally,
    flushNodePosition,
    patchNodeData,
    flushNodeConfig,
    addEdge,
    deleteEdge,
    renameWorkflow,
  }
}
