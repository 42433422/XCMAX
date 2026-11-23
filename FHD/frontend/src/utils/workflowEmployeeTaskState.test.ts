import { describe, expect, it } from 'vitest'
import type { AgentTaskSummary } from '@/api/agentRuns'
import { employeeIdOfTask, employeeTaskSnapshot, taskEmployeeIds, tasksForEmployee } from './workflowEmployeeTaskState'

const task: AgentTaskSummary = {
  task_id: 't',
  active_run_id: 'r',
  user_id: 'u',
  title: '标签打印',
  source: 'agent',
  task_type: 'employee',
  status: 'running',
  attempt: 1,
  run_count: 1,
}
const input = { empId: 'print', panelTitle: '打印员工', shortName: '打印', enabled: false, stale: false, lastVerifiedAt: 10 }

describe('authoritative employee task projection', () => {
  it('requires an explicit identity and works with lightweight and detailed snapshots', () => {
    expect(employeeIdOfTask(task)).toBe('')
    expect(employeeIdOfTask({ ...task, metadata: { employee_id: 'print' } })).toBe('print')
    expect(employeeIdOfTask({ ...task, metadata: { task_request: { tool_id: 'employee', params: { employee_id: 'print' } } } })).toBe(
      'print',
    )
    expect(
      employeeIdOfTask({
        ...task,
        active_run: {
          run_id: 'r',
          user_id: 'u',
          message: '',
          status: 'running',
          steps: [{ step_id: 's', node_id: 'n', tool_id: 'employee', action: 'execute', params: { employee_id: 'print' } }],
        },
      }),
    ).toBe('print')
    expect(
      employeeIdOfTask({
        ...task,
        title: 'print is working',
        metadata: { task_request: { tool_id: 'customers', params: { employee_id: 'print' } } },
      }),
    ).toBe('')
  })

  it('keeps active work ahead of history and never assigns unrelated tasks', () => {
    const rows = tasksForEmployee(
      [
        { ...task, task_id: 'done', status: 'completed', updated_at: '2026-11-22', metadata: { employee_id: 'print' } },
        { ...task, metadata: { employee_id: 'print' } },
        { ...task, task_id: 'other', metadata: { employee_id: 'other' } },
      ],
      'print',
    )
    expect(rows.map((row) => row.task_id)).toEqual(['t', 'done'])
  })

  it.each([
    ['running', 'working'],
    ['planning', 'reading'],
    ['waiting_user', 'waiting'],
    ['paused', 'waiting'],
    ['failed', 'error'],
    ['unknown', 'error'],
    ['completed', 'done'],
  ])('drives %s animation from the server status rather than percentage', (status, officeState) => {
    const snapshot = employeeTaskSnapshot({
      ...input,
      tasks: [{ ...task, status, progress: { percent: 100 } as AgentTaskSummary['progress'] }],
    })
    expect(snapshot.officeState).toBe(officeState)
    expect(snapshot.taskId).toBe('t')
    expect(snapshot.runId).toBe('r')
  })

  it('keeps uncertain execution and disconnected snapshots out of the completion animation', () => {
    const uncertain = {
      ...task,
      status: 'completed',
      active_run: { run_id: 'r', user_id: 'u', message: '', status: 'completed', final_output: { reconciliation_required: true } },
    }
    expect(employeeTaskSnapshot({ ...input, tasks: [uncertain] })).toMatchObject({
      status: 'unknown',
      officeState: 'error',
      visuallyBusy: false,
    })
    expect(employeeTaskSnapshot({ ...input, tasks: [task], stale: true })).toMatchObject({
      officeState: 'offline',
      visuallyBusy: false,
      taskId: 't',
    })
  })

  it('shows each employee’s real step during serial and parallel handoffs', () => {
    const shared = {
      ...task,
      metadata: {
        employee_assignments: [
          { employee_id: 'first', step_id: 'one', status: 'completed' },
          { employee_id: 'second', step_id: 'two', status: 'running' },
        ],
      },
    }
    expect(taskEmployeeIds(shared)).toEqual(['first', 'second'])
    expect(employeeIdOfTask(shared)).toBe('second')
    expect(employeeTaskSnapshot({ ...input, empId: 'first', tasks: [shared] }).officeState).toBe('done')
    expect(employeeTaskSnapshot({ ...input, empId: 'second', tasks: [shared] }).officeState).toBe('working')
    shared.metadata.employee_assignments[0].status = 'running'
    expect(employeeIdOfTask(shared)).toBe('')
    expect(tasksForEmployee([shared], 'first')).toHaveLength(1)
    expect(tasksForEmployee([shared], 'second')).toHaveLength(1)
    expect(employeeTaskSnapshot({ ...input, empId: 'first', tasks: [{ ...shared, status: 'paused' }] }).officeState).toBe('waiting')
    expect(
      employeeTaskSnapshot({
        ...input,
        empId: 'first',
        tasks: [{ ...shared, status: 'completed', metadata: { ...shared.metadata, reconciliation_required: true } }],
      }).officeState,
    ).toBe('error')
  })
})
