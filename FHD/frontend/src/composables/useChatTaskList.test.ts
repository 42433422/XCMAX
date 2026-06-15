import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useChatTaskList } from './useChatTaskList'

vi.mock('./useChatPersistence', () => ({
  TASK_HISTORY_LIMIT: 100,
}))

describe('useChatTaskList', () => {
  let onPersist: ReturnType<typeof vi.fn>

  beforeEach(() => {
    onPersist = vi.fn()
  })

  it('returns composable API', () => {
    const taskList = useChatTaskList({ onPersist })
    expect(taskList.taskList).toBeDefined()
    expect(taskList.activeTaskId).toBeDefined()
    expect(taskList.expandedTaskIds).toBeDefined()
    expect(taskList.taskFilter).toBeDefined()
    expect(taskList.activeTask).toBeDefined()
    expect(taskList.filteredTaskList).toBeDefined()
    expect(typeof taskList.createTaskId).toBe('function')
    expect(typeof taskList.upsertTask).toBe('function')
    expect(typeof taskList.finishTask).toBe('function')
    expect(typeof taskList.failTask).toBe('function')
    expect(typeof taskList.cancelTaskById).toBe('function')
    expect(typeof taskList.retryTask).toBe('function')
    expect(typeof taskList.toggleTaskExpanded).toBe('function')
    expect(typeof taskList.setTaskFilter).toBe('function')
    expect(typeof taskList.clearTaskHistory).toBe('function')
    expect(typeof taskList.jumpToTaskMessage).toBe('function')
  })

  it('createTaskId generates unique ids', () => {
    const taskList = useChatTaskList({ onPersist })
    const id1 = taskList.createTaskId('test')
    const id2 = taskList.createTaskId('test')
    expect(id1).not.toBe(id2)
    expect(id1).toMatch(/^test_/)
  })

  it('upsertTask adds new task', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
    })
    expect(taskList.taskList.value).toHaveLength(1)
    expect(taskList.taskList.value[0].id).toBe('task-1')
    expect(taskList.taskList.value[0].status).toBe('queued')
    expect(onPersist).toHaveBeenCalled()
  })

  it('upsertTask sets activeTaskId', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
    })
    expect(taskList.activeTaskId.value).toBe('task-1')
  })

  it('upsertTask updates existing task', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
      status: 'queued',
    })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Updated Task',
      type: 'test',
      source: 'user',
      status: 'running',
      progress: 50,
    })
    expect(taskList.taskList.value).toHaveLength(1)
    expect(taskList.taskList.value[0].status).toBe('running')
    expect(taskList.taskList.value[0].progress).toBe(50)
  })

  it('finishTask marks task as success', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
      status: 'running',
    })
    taskList.finishTask('task-1', 'Done!')
    const task = taskList.taskList.value.find((t) => t.id === 'task-1')
    expect(task?.status).toBe('success')
    expect(task?.progress).toBe(100)
    expect(task?.summary).toBe('Done!')
  })

  it('finishTask does nothing for non-existent task', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.finishTask('non-existent', 'Done')
    expect(taskList.taskList.value).toHaveLength(0)
  })

  it('failTask marks task as failed', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
      status: 'running',
    })
    taskList.failTask('task-1', 'Something went wrong')
    const task = taskList.taskList.value.find((t) => t.id === 'task-1')
    expect(task?.status).toBe('failed')
    expect(task?.error).toBe('Something went wrong')
  })

  it('cancelTaskById marks task as cancelled', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
      status: 'running',
    })
    taskList.cancelTaskById('task-1')
    const task = taskList.taskList.value.find((t) => t.id === 'task-1')
    expect(task?.status).toBe('cancelled')
  })

  it('retryTask marks task as running with retry suffix', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
      status: 'failed',
    })
    taskList.retryTask('task-1')
    const task = taskList.taskList.value.find((t) => t.id === 'task-1')
    expect(task?.status).toBe('running')
    expect(task?.title).toContain('重试')
    expect(task?.progress).toBe(0)
  })

  it('toggleTaskExpanded adds and removes task id', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.toggleTaskExpanded('task-1')
    expect(taskList.expandedTaskIds.value).toContain('task-1')
    taskList.toggleTaskExpanded('task-1')
    expect(taskList.expandedTaskIds.value).not.toContain('task-1')
  })

  it('activeTask returns the active task', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({
      id: 'task-1',
      title: 'Test Task',
      type: 'test',
      source: 'user',
    })
    expect(taskList.activeTask.value?.id).toBe('task-1')
  })

  it('activeTask returns null when no active task', () => {
    const taskList = useChatTaskList({ onPersist })
    expect(taskList.activeTask.value).toBeNull()
  })

  it('filteredTaskList returns all tasks by default', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({ id: 't1', title: 'T1', type: 'test', source: 'user', status: 'running' })
    taskList.upsertTask({ id: 't2', title: 'T2', type: 'test', source: 'user', status: 'success' })
    expect(taskList.filteredTaskList.value).toHaveLength(2)
  })

  it('filteredTaskList filters by running status', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({ id: 't1', title: 'T1', type: 'test', source: 'user', status: 'running' })
    taskList.upsertTask({ id: 't2', title: 'T2', type: 'test', source: 'user', status: 'success' })
    taskList.setTaskFilter('running')
    expect(taskList.filteredTaskList.value).toHaveLength(1)
    expect(taskList.filteredTaskList.value[0].status).toBe('running')
  })

  it('filteredTaskList filters by success status', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({ id: 't1', title: 'T1', type: 'test', source: 'user', status: 'running' })
    taskList.upsertTask({ id: 't2', title: 'T2', type: 'test', source: 'user', status: 'success' })
    taskList.setTaskFilter('success')
    const list = taskList.filteredTaskList.value
    expect(list.some((t) => t.status === 'success')).toBe(true)
  })

  it('filteredTaskList filters by failed status', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({ id: 't1', title: 'T1', type: 'test', source: 'user', status: 'failed' })
    taskList.upsertTask({ id: 't2', title: 'T2', type: 'test', source: 'user', status: 'success' })
    taskList.setTaskFilter('failed')
    expect(taskList.filteredTaskList.value.some((t) => t.status === 'failed')).toBe(true)
  })

  it('clearTaskHistory removes completed tasks', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({ id: 't1', title: 'T1', type: 'test', source: 'user', status: 'running' })
    taskList.upsertTask({ id: 't2', title: 'T2', type: 'test', source: 'user', status: 'success' })
    taskList.upsertTask({ id: 't3', title: 'T3', type: 'test', source: 'user', status: 'failed' })
    taskList.clearTaskHistory()
    expect(taskList.taskList.value).toHaveLength(1)
    expect(taskList.taskList.value[0].status).toBe('running')
  })

  it('sortTaskList sorts by status rank', () => {
    const taskList = useChatTaskList({ onPersist })
    taskList.upsertTask({ id: 't1', title: 'T1', type: 'test', source: 'user', status: 'success' })
    taskList.upsertTask({ id: 't2', title: 'T2', type: 'test', source: 'user', status: 'running' })
    taskList.upsertTask({ id: 't3', title: 'T3', type: 'test', source: 'user', status: 'failed' })
    expect(taskList.taskList.value[0].status).toBe('running')
  })
})
