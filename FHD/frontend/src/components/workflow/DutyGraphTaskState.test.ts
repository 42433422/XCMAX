import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, effectScope, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import type { AgentTaskSummary } from '@/api/agentRuns'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
import { useDutyRosterState } from '../../../../admin-console/src/components/workflow/dutyRoster/useDutyRosterState'
import { useDutyGraphBuild } from '../../../../admin-console/src/components/workflow/dutyRoster/useDutyGraphBuild'
import type { DutyLoopCore } from '../../../../admin-console/src/components/workflow/dutyRoster/useDutyLoopCore'
import type { DutyData } from '../../../../admin-console/src/components/workflow/dutyRoster/useDutyRosterData'

describe('admin department graph uses the shared task ledger', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('synchronizes repeated department nodes without changing layout, and marks stale data', async () => {
    const scope = effectScope()
    const fitView = vi.fn()
    const store = useAgentTaskCenterStore()
    const task: AgentTaskSummary = {
      task_id: 'task-1', user_id: 'user-1', title: '更新网站', source: 'employee', task_type: 'employee',
      status: 'running', attempt: 1, run_count: 1, active_run_id: 'run-1',
      metadata: { employee_id: 'site-content-editor' },
    }
    store.tasks = [task]
    store.stale = false
    store.lastVerifiedAt = Date.now()
    const graph = scope.run(() => {
      const state = useDutyRosterState({ query: { view: 'department' } } as RouteLocationNormalizedLoaded)
      const employee = { id: 'site-content-editor', name: '网站编辑', source: 'catalog' as const }
      state.employees.value = [employee]
      const result = useDutyGraphBuild(state, {
        loopParticipantIdSet: computed(() => new Set<string>()),
      } as DutyLoopCore, {
        buildRosterEmployeeRows: () => [employee],
      } as unknown as DutyData, { fitView, syncEmployeeRouteQuery: vi.fn() })
      result.buildDepartmentGraph([employee])
      return result
    })!
    try {
      const relatedNodes = () => graph.liveFlowNodes.value.filter(node => node.data?.id === 'site-content-editor')
      expect(relatedNodes().length).toBeGreaterThan(1)
      expect(relatedNodes().every(node => node.data.taskSnapshot.runId === 'run-1' && node.data.taskSnapshot.officeState === 'working')).toBe(true)
      const positions = relatedNodes().map(node => node.position)
      store.tasks = [{ ...task, status: 'waiting_user', approval_required: true }]
      await nextTick()
      expect(relatedNodes().every(node => node.data.taskSnapshot.officeState === 'waiting')).toBe(true)
      expect(relatedNodes().map(node => node.position)).toEqual(positions)
      expect(fitView).not.toHaveBeenCalled()
      store.stale = true
      await nextTick()
      expect(relatedNodes().every(node => node.data.taskSnapshot.officeState === 'offline' && node.data.taskSnapshot.stale)).toBe(true)
      expect(graph.taskSnapshots.value.get('site-content-editor')?.taskId).toBe('task-1')
    } finally {
      scope.stop()
    }
  })
})
