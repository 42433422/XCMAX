import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatTaskPanel from './ChatTaskPanel.vue'
import type { TaskItem } from '@/composables/useChatPersistence'

function makeTask(overrides: Partial<TaskItem>): TaskItem {
  return {
    id: 'task-1',
    type: 'manual_task',
    title: '测试任务',
    source: 'manual',
    status: 'running',
    startedAt: 1,
    updatedAt: 1,
    payload: {},
    ...overrides,
  }
}

function mountPanel(tasks: TaskItem[]) {
  return mount(ChatTaskPanel, {
    props: {
      currentTask: null,
      taskList: tasks,
      filteredTaskList: tasks,
      expandedTaskIds: tasks.map((task) => task.id),
      taskFilter: 'all',
      isProMode: false,
      proRuntimeTask: null,
      latestAssistantPush: null,
      pushCopied: false,
      orderNumberFetching: false,
      isExecuting: false,
      taskTableColumns: [],
      taskTableItems: [],
      taskOrderNumber: '',
      formatTaskTime: () => '刚刚',
      formatTaskSourceLabel: () => '手动',
      workflowTaskDotStatusClass: (task) => task.status,
      workflowTaskDotTitle: (task) => task.status,
    },
  })
}

describe('ChatTaskPanel task action capabilities', () => {
  it('hides the existing fake retry and cancel actions when payload has no real capability', () => {
    const wrapper = mountPanel([
      makeTask({ id: 'failed-task', status: 'failed' }),
      makeTask({ id: 'running-task', status: 'running' }),
      makeTask({
        id: 'incomplete-capability',
        status: 'failed',
        payload: { actionCapabilities: { retry: { enabled: true } } },
      }),
    ])

    expect(wrapper.find('[data-action="retry-task"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="cancel-task-by-id"]').exists()).toBe(false)
  })

  it('shows and emits actions only for endpoint-backed capabilities declared by the task', async () => {
    const wrapper = mountPanel([
      makeTask({
        id: 'retryable-task',
        status: 'failed',
        payload: {
          actionCapabilities: {
            retry: { enabled: true, endpoint: '/api/tasks/retryable-task/retry' },
          },
        },
      }),
      makeTask({
        id: 'cancellable-task',
        status: 'running',
        payload: {
          actionCapabilities: {
            cancel: { enabled: true, endpoint: '/api/tasks/cancellable-task/cancel' },
          },
        },
      }),
    ])

    await wrapper.get('[data-action="retry-task"]').trigger('click')
    await wrapper.get('[data-action="cancel-task-by-id"]').trigger('click')

    expect(wrapper.emitted('retry-task')).toEqual([['retryable-task']])
    expect(wrapper.emitted('cancel-task-by-id')).toEqual([['cancellable-task']])
  })
})
