import { beforeEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import type { TaskItem } from '@/composables/useChatPersistence'
import ChatSidePanel from './ChatSidePanel.vue'

const formatter = vi.fn(() => '')

function mountPanel(taskList: TaskItem[] = []) {
  return shallowMount(ChatSidePanel, {
    props: {
      currentTask: null,
      taskList,
      filteredTaskList: taskList,
      activeTaskId: '',
      expandedTaskIds: [],
      taskFilter: 'all',
      latestAssistantPush: null,
      pushCopied: false,
      orderNumberFetching: false,
      isExecuting: false,
      taskTableColumns: [],
      taskTableItems: [],
      taskOrderNumber: '',
      formatTaskTime: formatter,
      formatTaskSourceLabel: formatter,
      workflowTaskDotStatusClass: formatter,
      workflowTaskDotTitle: formatter,
      historySessions: [],
      currentSessionId: 'session-current',
      historyLoading: false,
      historyError: '',
    },
  })
}

describe('ChatSidePanel', () => {
  beforeEach(() => {
    formatter.mockClear()
  })

  it('loads conversations when the empty panel initially opens on the conversation tab', () => {
    const wrapper = mountPanel()

    expect(wrapper.emitted('refresh-history')).toHaveLength(1)
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain('对话')
  })

  it('loads conversations when the user switches from tasks to the conversation tab', async () => {
    const task: TaskItem = {
      id: 'task-1',
      type: 'workflow',
      title: '任务',
      source: 'workflow',
      status: 'success',
      startedAt: 1,
      updatedAt: 1,
    }
    const wrapper = mountPanel([task])
    expect(wrapper.emitted('refresh-history')).toBeUndefined()

    await wrapper.findAll('[role="tab"]')[1].trigger('click')

    expect(wrapper.emitted('refresh-history')).toHaveLength(1)
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain('对话')
  })
})
