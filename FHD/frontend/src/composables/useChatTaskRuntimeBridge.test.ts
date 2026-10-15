import { effectScope, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import { useChatTaskRuntimeBridge } from './useChatTaskRuntimeBridge'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
const workspace = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), archiveCompletedTasks: vi.fn() }))
vi.mock('./useAgentTaskWorkspace', () => ({ useAgentTaskWorkspace: () => workspace }))
vi.mock('@/stores/mods', async () => { const { reactive } = await import('vue'); const state = reactive({ activeModId: 'a' }); return { useModsStore: () => state } })
vi.mock('@/stores/accountProfile', async () => { const { reactive } = await import('vue'); const state = reactive({ localUserId: 1 }); return { useAccountProfileStore: () => state } })
it('clears chat task state and restarts only a running workspace on scope change', () => {
  const scope = effectScope()
  const options = { taskList: ref([]), activeTaskId: ref('old'), expandedTaskIds: ref(['old']), sortTaskList: vi.fn(), persist: vi.fn(), loadConversation: vi.fn(), newConversation: vi.fn(), jumpToMessage: vi.fn(), toggleExpanded: vi.fn(), clearLocalHistory: vi.fn() }
  const bridge = scope.run(() => useChatTaskRuntimeBridge(options))!
  bridge.start()
  useModsStore().activeModId = 'b'
  expect(workspace.stop).toHaveBeenCalledTimes(1)
  expect(workspace.start).toHaveBeenCalledTimes(2)
  expect(options.activeTaskId.value).toBe('')
  expect(options.expandedTaskIds.value).toEqual([])
  bridge.stop()
  useAccountProfileStore().localUserId = 2
  expect(workspace.start).toHaveBeenCalledTimes(2)
  scope.stop()
})

it('does not clear the new scope history after an old archive completes', async () => {
  const scope = effectScope()
  const clearLocalHistory = vi.fn()
  let resolve!: () => void
  workspace.archiveCompletedTasks.mockReturnValueOnce(new Promise<void>((r) => { resolve = r }))
  const options = { taskList: ref([]), activeTaskId: ref(''), expandedTaskIds: ref<string[]>([]), sortTaskList: vi.fn(), persist: vi.fn(), loadConversation: vi.fn(), newConversation: vi.fn(), jumpToMessage: vi.fn(), toggleExpanded: vi.fn(), clearLocalHistory }
  const bridge = scope.run(() => useChatTaskRuntimeBridge(options))!
  const pending = bridge.clearTaskHistory()
  useModsStore().activeModId = 'new-history-scope'
  resolve()
  await pending
  expect(clearLocalHistory).not.toHaveBeenCalled()
  scope.stop()
})
