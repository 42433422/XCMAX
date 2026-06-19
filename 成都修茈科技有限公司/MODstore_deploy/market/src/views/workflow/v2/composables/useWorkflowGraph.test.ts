import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

const apiMock = vi.hoisted(() => ({
  addWorkflowEdge: vi.fn(),
  addWorkflowNode: vi.fn(),
  deleteWorkflowEdge: vi.fn(),
  deleteWorkflowNode: vi.fn(),
  getWorkflow: vi.fn(),
  updateWorkflow: vi.fn(),
  updateWorkflowNode: vi.fn(),
}))

vi.mock('../../../../api', () => ({
  api: apiMock,
}))

import { useWorkflowGraph } from './useWorkflowGraph'

describe('useWorkflowGraph', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('maps fallback workflow payload fields and ignores rename before metadata is loaded', async () => {
    apiMock.getWorkflow.mockResolvedValue({
      id: 42,
      name: '',
      description: '',
      is_active: 1,
      nodes: [
        {
          id: 11,
          node_type: 'unknown_kind',
          name: '',
          position_x: 'bad',
          position_y: null,
          config: null,
        },
        {
          id: 12,
          node_type: 'input',
          name: 'Start',
          position_x: '24',
          position_y: 48,
          config: { source: 'manual' },
        },
      ],
      edges: [
        {
          id: 21,
          source_node_id: 11,
          target_node_id: 12,
          condition: 'true',
        },
        {
          id: 22,
          source_node_id: 12,
          target_node_id: 11,
          condition: 'custom route',
        },
        {
          id: 23,
          source_node_id: 12,
          target_node_id: 11,
          condition: '',
        },
      ],
    })

    const graph = useWorkflowGraph(42)

    await graph.renameWorkflow('No-op', 'No metadata yet')
    expect(apiMock.updateWorkflow).not.toHaveBeenCalled()

    await graph.loadGraph()

    expect(graph.loading.value).toBe(false)
    expect(graph.meta.value).toEqual({
      name: '',
      description: '',
      is_active: true,
    })
    expect(graph.nodes.value[0]).toMatchObject({
      id: '11',
      type: 'mod',
      position: { x: 0, y: 0 },
      data: {
        kind: 'unknown_kind',
        config: {},
        backendId: 11,
      },
    })
    expect(graph.nodes.value[0].data.label).toBeTruthy()
    expect(graph.nodes.value[1]).toMatchObject({
      id: '12',
      type: 'mod',
      position: { x: 24, y: 48 },
      data: {
        label: 'Start',
        config: { source: 'manual' },
        backendId: 12,
      },
    })
    expect(graph.edges.value[0]).toMatchObject({
      id: '21',
      source: '11',
      target: '12',
      sourceHandle: 'true',
      data: { backendId: 21 },
    })
    expect(graph.edges.value[1]).toMatchObject({
      id: '22',
      label: 'custom route',
      sourceHandle: null,
      data: { backendId: 22 },
    })
    expect(graph.edges.value[2]).toMatchObject({
      id: '23',
      sourceHandle: null,
      data: { backendId: 23 },
    })
  })

  it('reports load/add/delete node failures and rolls back optimistic nodes', async () => {
    const loadError = new Error('load failed')
    apiMock.getWorkflow.mockRejectedValueOnce(loadError)

    const graph = useWorkflowGraph(7)

    await expect(graph.loadGraph()).rejects.toThrow('load failed')
    expect(graph.loading.value).toBe(false)
    expect(graph.lastError.value).toBe(loadError)

    const addError = new Error('add failed')
    apiMock.addWorkflowNode.mockRejectedValueOnce(addError)

    await expect(graph.addNode('employee', { x: 9, y: 10 })).rejects.toThrow('add failed')
    expect(graph.nodes.value).toEqual([])
    expect(graph.lastError.value).toBe(addError)

    graph.nodes.value = [
      {
        id: 'backend-node',
        type: 'mod',
        position: { x: 1, y: 2 },
        data: {
          kind: 'employee',
          label: 'Backend node',
          config: {},
          backendId: 99,
        },
      },
    ]
    const deleteError = new Error('delete failed')
    apiMock.deleteWorkflowNode.mockRejectedValueOnce(deleteError)

    await expect(graph.deleteNode('backend-node')).rejects.toThrow('delete failed')
    expect(graph.lastError.value).toBe(deleteError)
  })

  it('covers node flush debouncing, edge guards, delete fallbacks, and rename failures', async () => {
    vi.useFakeTimers()

    const graph = useWorkflowGraph(8)
    graph.meta.value = {
      id: 8,
      name: 'Original',
      description: 'Old description',
      isActive: false,
    }
    graph.nodes.value = [
      {
        id: 'local-node',
        type: 'mod',
        position: { x: 1, y: 2 },
        data: {
          kind: 'employee',
          label: 'Local node',
          config: {},
          backendId: 0,
        },
      },
      {
        id: 'source-node',
        type: 'mod',
        position: { x: 3, y: 4 },
        data: {
          kind: 'condition',
          label: 'Source node',
          config: { enabled: true },
          backendId: 101,
        },
      },
      {
        id: 'target-node',
        type: 'mod',
        position: { x: 5, y: 6 },
        data: {
          kind: 'employee',
          label: 'Target node',
          config: {},
          backendId: 102,
        },
      },
    ]
    graph.edges.value = [
      {
        id: 'local-edge',
        source: 'local-node',
        target: 'target-node',
        data: { condition: '', backendId: 0 },
      },
      {
        id: 'backend-edge',
        source: 'source-node',
        target: 'target-node',
        data: { condition: '', backendId: 501 },
      },
    ]

    graph.updateNodePositionLocally('missing-node', { x: 88, y: 99 })
    expect(graph.nodes.value[0].position).toEqual({ x: 1, y: 2 })

    await graph.flushNodePosition('missing-node')
    await graph.flushNodePosition('local-node')
    expect(apiMock.updateWorkflowNode).not.toHaveBeenCalled()

    const positionError = new Error('position failed')
    apiMock.updateWorkflowNode.mockRejectedValueOnce(positionError)
    await graph.flushNodePosition('source-node')
    expect(graph.lastError.value).toBe(positionError)

    graph.patchNodeData('source-node', { config: { enabled: false } })
    graph.patchNodeData('source-node', { config: { enabled: true, limit: 3 } })
    expect(apiMock.updateWorkflowNode).toHaveBeenCalledTimes(1)

    const configError = new Error('config failed')
    apiMock.updateWorkflowNode.mockRejectedValueOnce(configError)
    await vi.advanceTimersByTimeAsync(500)
    await nextTick()
    expect(graph.lastError.value).toBe(configError)

    await graph.flushNodeConfig('missing-node')
    await graph.flushNodeConfig('local-node')

    apiMock.addWorkflowEdge.mockResolvedValueOnce({
      id: 601,
      source_node_id: 101,
      target_node_id: 102,
      condition: 'false',
    })
    apiMock.addWorkflowEdge.mockResolvedValueOnce({
      id: 602,
      source_node_id: 101,
      target_node_id: 102,
      condition: null,
    })

    await graph.addEdge('missing-node', 'target-node')
    await graph.addEdge('source-node', 'local-node')
    await graph.addEdge('source-node', 'source-node')
    await graph.addEdge('source-node', 'target-node', 'false')
    await graph.addEdge('source-node', 'target-node')

    expect(apiMock.addWorkflowEdge).toHaveBeenCalledTimes(2)
    expect(graph.edges.value).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          data: { condition: 'false', backendId: 601 },
          sourceHandle: 'false',
        }),
        expect.objectContaining({
          data: { condition: '', backendId: 602 },
          sourceHandle: null,
        }),
      ]),
    )

    apiMock.addWorkflowEdge.mockRejectedValueOnce(new Error('edge failed'))
    await expect(graph.addEdge('source-node', 'target-node', 'custom')).rejects.toThrow('edge failed')
    expect(graph.lastError.value).toEqual(new Error('edge failed'))

    await graph.deleteEdge('local-edge')
    expect(apiMock.deleteWorkflowEdge).not.toHaveBeenCalled()
    expect(graph.edges.value.some((edge) => edge.id === 'local-edge')).toBe(false)

    const deleteEdgeError = new Error('delete edge failed')
    apiMock.deleteWorkflowEdge.mockRejectedValueOnce(deleteEdgeError)
    await graph.deleteEdge('backend-edge')
    expect(graph.lastError.value).toBe(deleteEdgeError)

    const renameError = new Error('rename failed')
    apiMock.updateWorkflow.mockRejectedValueOnce(renameError)
    await graph.renameWorkflow('Updated', 'New description')
    expect(graph.lastError.value).toBe(renameError)
  })
})
