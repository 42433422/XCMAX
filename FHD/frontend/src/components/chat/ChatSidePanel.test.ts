import { beforeEach, describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import type { TaskItem } from '@/composables/useChatPersistence'
import ChatConversationPanel from './ChatConversationPanel.vue'
import ChatSidePanel from './ChatSidePanel.vue'
import ChatTaskPanel from './ChatTaskPanel.vue'

const formatter = vi.fn(() => '')

const task: TaskItem = {
  id: 'task-1',
  type: 'workflow',
  title: '任务',
  source: 'workflow',
  status: 'success',
  startedAt: 1,
  updatedAt: 1,
}

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
    const wrapper = mountPanel([task])
    expect(wrapper.emitted('refresh-history')).toBeUndefined()

    await wrapper.findAll('[role="tab"]')[1].trigger('click')

    expect(wrapper.emitted('refresh-history')).toHaveLength(1)
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain('对话')
  })

  it('forwards task and conversation panel actions with their payloads', async () => {
    const wrapper = mountPanel([task])
    const taskPanel = wrapper.findComponent(ChatTaskPanel)
    const taskEvents: Array<[string, ...unknown[]]> = [
      ['confirm-task'],
      ['cancel-task'],
      ['refetch-order-number'],
      ['set-custom-order-number', 'SO-001'],
      ['shipment-download-click'],
      ['start-print'],
      ['switch-view', 'orders'],
      ['set-task-filter', 'running'],
      ['clear-task-history'],
      ['toggle-task-expanded', task.id],
      ['select-task', task],
      ['open-shipment-records'],
      ['jump-to-task-message', task],
      ['retry-task', task.id],
      ['pause-task', task.id],
      ['resume-task', task.id],
      ['approve-task', task.id],
      ['cancel-task-by-id', task.id],
      ['copy-assistant-push'],
      ['open-assistant-float'],
    ]
    taskEvents.forEach(([event, ...args]) => taskPanel.vm.$emit(event, ...args))
    taskEvents.forEach(([event, ...args]) => expect(wrapper.emitted(event)?.at(-1)).toEqual(args))

    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    const conversationPanel = wrapper.findComponent(ChatConversationPanel)
    const conversationEvents: Array<[string, ...unknown[]]> = [
      ['new'],
      ['refresh'],
      ['clear'],
      ['load', 'session-1'],
      ['rename', 'session-1', '新标题'],
      ['delete', 'session-1'],
    ]
    conversationEvents.forEach(([event, ...args]) => conversationPanel.vm.$emit(event, ...args))

    expect(wrapper.emitted('new-conversation')?.at(-1)).toEqual([])
    expect(wrapper.emitted('refresh-history')).toHaveLength(2)
    expect(wrapper.emitted('clear-history-sessions')?.at(-1)).toEqual([])
    expect(wrapper.emitted('load-session')?.at(-1)).toEqual(['session-1'])
    expect(wrapper.emitted('rename-session')?.at(-1)).toEqual(['session-1', '新标题'])
    expect(wrapper.emitted('delete-session')?.at(-1)).toEqual(['session-1'])

    await wrapper.findAll('[role="tab"]')[0].trigger('click')
    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain('任务')
  })
})
