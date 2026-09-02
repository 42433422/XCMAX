// LeftRail Agent 面板逻辑：草稿生成/重试/中止与运行时间线应用。
import { ref } from 'vue'
import type { Ref } from 'vue'
import { useAgentLoop } from '../../../../composables/useAgentLoop'
import { useWorkbenchStore } from '../../../../stores/workbench'
import type { AgentRun } from '../../../../stores/workbench'

export type RailView = 'list' | 'agent'

export function useLeftRailAgent(deps: {
  store: ReturnType<typeof useWorkbenchStore>
  agentLoop: ReturnType<typeof useAgentLoop>
  view: Ref<RailView>
  loadEmployees: () => Promise<void>
}) {
  const { store, agentLoop, view, loadEmployees } = deps

  const agentInput = ref('')
  const agentRunning = ref(false)
  let currentAbort: (() => void) | null = null

  async function runAgentDraft() {
    const brief = agentInput.value.trim()
    if (!brief || agentRunning.value) return
    agentRunning.value = true
    agentInput.value = ''
    view.value = 'agent'

    const { abort } = await agentLoop.runEmployeeDraft(brief)
    currentAbort = abort
    agentRunning.value = false
  }

  async function retryEmployeeDraft() {
    const brief = store.currentRun?.brief?.trim()
    if (!brief || agentRunning.value) return
    agentRunning.value = true
    const { abort } = await agentLoop.runEmployeeDraft(brief)
    currentAbort = abort
    agentRunning.value = false
  }

  async function onDraftPublished(_modId: string) {
    await loadEmployees()
  }

  function abortCurrentRun() {
    currentAbort?.()
    currentAbort = null
    agentRunning.value = false
  }

  function applyRunManifest(run: AgentRun) {
    if (!run.manifest) return
    store.setTarget(store.target.kind, store.target.id, run.manifest as Record<string, unknown>, store.target.name)
  }

  function formatTs(ts: number) {
    return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const AGENT_SUGGESTED = [
    '帮我创建一个电话客服员工，专注售后问题处理',
    '创建一个数据分析员工，能处理 CSV 并生成报表',
    '设计一个全能型 AI 助手，支持图文理解和对话',
  ]

  function useSuggestion(s: string) {
    agentInput.value = s
  }

  return {
    agentInput,
    agentRunning,
    runAgentDraft,
    retryEmployeeDraft,
    onDraftPublished,
    abortCurrentRun,
    applyRunManifest,
    formatTs,
    AGENT_SUGGESTED,
    useSuggestion,
  }
}
