import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { useChatResponseAttach } from './useChatResponseAttach'
import type { TaskItem } from './useChatPersistence'

function makeDeps() {
  const messages = ref([
    { role: 'user' as const, content: 'hi' },
    { role: 'ai' as const, content: 'reply' },
  ])
  const taskList = ref<TaskItem[]>([
    {
      id: 'wf-running',
      type: 'workflow',
      source: 'workflow',
      title: 'running wf',
      status: 'running',
      progress: 20,
    },
  ])
  const upsertTask = vi.fn()
  const api = useChatResponseAttach({
    messages,
    lastRequestContextSummary: ref(''),
    taskList,
    upsertTask,
    createTaskId: (p) => `${p}-id`,
  })
  return { messages, taskList, upsertTask, ...api }
}

describe('useChatResponseAttach', () => {
  it('attachThinkingStepsToLastAiMessage sets thinking on last ai', () => {
    const { messages, attachThinkingStepsToLastAiMessage } = makeDeps()
    attachThinkingStepsToLastAiMessage({
      success: true,
      data: { data: { thinking_steps: '步骤1\n步骤2' } },
    })
    expect(messages.value[1].thinkingSteps).toContain('步骤1')
  })

  it('attachTodoStepsToLastAiMessage sets todo list', () => {
    const { messages, attachTodoStepsToLastAiMessage } = makeDeps()
    attachTodoStepsToLastAiMessage({
      success: true,
      data: { data: { todo: ['a', 'b'] } },
    })
    expect(messages.value[1].todoSteps).toEqual(['a', 'b'])
  })

  it('attachWorkflowTraceToLastAiMessage sets trace', () => {
    const { messages, attachWorkflowTraceToLastAiMessage } = makeDeps()
    attachWorkflowTraceToLastAiMessage({
      success: true,
      data: {
        action: 'workflow_done',
        data: { node_results: [{ node_id: 'n1', success: true, tool_id: 'products' }] },
      },
    })
    expect(messages.value[1].nodeResults?.length).toBe(1)
    expect(messages.value[1].workflowAction).toBe('workflow_done')
  })

  it('syncTaskFromChatResponse queues workflow confirmation', () => {
    const { upsertTask, syncTaskFromChatResponse } = makeDeps()
    syncTaskFromChatResponse(
      {
        success: true,
        data: {
          action: 'workflow_confirmation_required',
          data: { pending_workflow_id: 'wf-9' },
        },
      },
      '执行任务',
    )
    expect(upsertTask).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'wf-9', type: 'workflow', status: 'queued' }),
    )
  })

  it('syncTaskFromChatResponse marks workflow done', () => {
    const { upsertTask, syncTaskFromChatResponse } = makeDeps()
    syncTaskFromChatResponse(
      { success: true, data: { action: 'workflow_done', data: {} } },
      'ok',
    )
    expect(upsertTask).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'wf-running', status: 'success', progress: 100 }),
    )
  })

  it('syncTaskFromChatResponse marks workflow failed', () => {
    const { upsertTask, syncTaskFromChatResponse } = makeDeps()
    syncTaskFromChatResponse(
      { success: false, message: 'boom', data: { action: 'workflow_failed', data: {} } },
      'bad',
    )
    expect(upsertTask).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'wf-running', status: 'failed', error: 'boom' }),
    )
  })

  it('syncTaskFromChatResponse updates running workflow progress from node_results', () => {
    const { upsertTask, syncTaskFromChatResponse } = makeDeps()
    syncTaskFromChatResponse(
      {
        success: true,
        data: {
          data: {
            node_results: [
              { node_id: 'n1', success: true },
              { node_id: 'n2', success: false },
            ],
          },
        },
      },
      'progress',
    )
    expect(upsertTask).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'running', stage: expect.stringContaining('1/2') }),
    )
  })

  it('attachContextSummaryToLastAiMessage writes summary on last ai', () => {
    const lastRequestContextSummary = ref('ctx summary')
    const messages = ref([{ role: 'ai' as const, content: 'x' }])
    const { attachContextSummaryToLastAiMessage } = useChatResponseAttach({
      messages,
      lastRequestContextSummary,
      taskList: ref([]),
      upsertTask: vi.fn(),
      createTaskId: (p) => p,
    })
    attachContextSummaryToLastAiMessage()
    expect(messages.value[0].contextSummary).toBe('ctx summary')
  })
})
