/**
 * useChatWorkflowPanel 拆分：电话员工（phone-agent）状态拉取与轮询。
 */
import { listPhoneAgentEmployeeIds } from '@/utils/modWorkflowEmployees'
import type { useModsStore } from '@/stores/mods'
import type { PhoneAgentStatusPayload } from './phoneAgentStatus'

export interface PhoneAgentPollingDeps {
  getModsForUi: () => ReturnType<typeof useModsStore>['modsForUi']
  readWorkflowEmployeeEnabledMap: () => Record<string, boolean>
  /** 面板 meta 解析（facade 装配时回填 tasks 模块实现，时序与拆分前一致） */
  resolveWorkflowEmployeePanelMeta: (empId: string) => { title: string; summary: string } | null
  /** 轮询到新状态时回写任务（对应拆分前 upsertWorkflowEmployeeTask(empId, { phoneStatus })） */
  onStatusUpdate: (empId: string, ps: PhoneAgentStatusPayload) => void
  resolvePhoneChannelByEmployee: (empId: string) => 'wechat' | 'adb'
  getPhoneAgentApiBase: (empId: string) => string
}

export function usePhoneAgentPolling(deps: PhoneAgentPollingDeps) {
  const { resolvePhoneChannelByEmployee, getPhoneAgentApiBase, readWorkflowEmployeeEnabledMap, resolveWorkflowEmployeePanelMeta } = deps

  const PHONE_AGENT_POLL_MS = 2000
  let phoneAgentPollTimer: number | null = null

  /** 所有已启用的电话类员工（manifest 含 phone_agent API）；无 manifest 时不算启用 */
  function getEnabledPhoneEmployeeIds(): string[] {
    const enabled = readWorkflowEmployeeEnabledMap()
    const out: string[] = []
    for (const empId of listPhoneAgentEmployeeIds(deps.getModsForUi())) {
      if (enabled[empId] && resolveWorkflowEmployeePanelMeta(empId)) out.push(empId)
    }
    return out
  }

  /** 与 TopAssistantFloat 一致：启用微信电话员工时应启动后端 phone-agent。重启 run.py 后 _running 为 false，仅靠 localStorage 开关不会再次 POST /start，故在轮询侧兜底。 */
  async function requestPhoneAgentStart(empId: string): Promise<void> {
    const base = getPhoneAgentApiBase(empId).replace(/\/+$/, '')
    if (!base) return
    const ch = resolvePhoneChannelByEmployee(empId)
    try {
      const resp = await fetch(`${base}/start?channel=${ch}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel: ch }),
      })
      const raw = await resp.text()
      let data: { success?: boolean; message?: string; error?: string } = {}
      try {
        data = raw ? (JSON.parse(raw) as typeof data) : {}
      } catch {
        data = {}
      }
      if (!data.success) {
        const msg =
          (typeof data.message === 'string' && data.message.trim()) ||
          (typeof data.error === 'string' && data.error.trim()) ||
          (resp.ok ? '未知错误' : `HTTP ${resp.status}`)
        const hint = !raw.trim().startsWith('{') ? raw.slice(0, 200) : ''
        console.warn('[奇士美 PRO] phone-agent/start:', msg + (hint ? ` | body: ${hint}` : ''))
      }
    } catch (e) {
      console.warn('[奇士美 PRO] phone-agent/start 请求失败:', e)
    }
  }

  async function fetchPhoneAgentStatusPayload(empId: string): Promise<PhoneAgentStatusPayload> {
    const base = getPhoneAgentApiBase(empId).replace(/\/+$/, '')
    const lastPolledAt = Date.now()
    if (!base) {
      return {
        lastPolledAt,
        running: false,
        fetchError: '当前为原版模式或未加载 Mod，无电话扩展接口',
      }
    }
    const ch = resolvePhoneChannelByEmployee(empId)
    try {
      const r = await fetch(`${base}/status?channel=${ch}`)
      const j = await r.json().catch(() => ({}))
      if (j?.success && j?.data && typeof j.data === 'object') {
        return { ...j.data, lastPolledAt } as PhoneAgentStatusPayload
      }
      const msg =
        typeof j?.message === 'string' && j.message.trim()
          ? j.message.trim()
          : !r.ok
            ? r.status === 404
              ? `HTTP 404（请确认路径为 ${base}/status，勿使用 /statu 等拼写错误）`
              : `HTTP ${r.status}`
            : '响应缺少 data'
      return { lastPolledAt, running: false, fetchError: msg }
    } catch (e) {
      const err = e instanceof Error ? e.message : String(e)
      return { lastPolledAt, running: false, fetchError: err }
    }
  }

  function stopPhoneAgentStatusPoll() {
    if (phoneAgentPollTimer) {
      window.clearInterval(phoneAgentPollTimer)
      phoneAgentPollTimer = null
    }
  }

  async function pollPhoneAgentStatusForEnabledEmployees(): Promise<void> {
    const ids = getEnabledPhoneEmployeeIds()
    if (ids.length === 0) {
      stopPhoneAgentStatusPoll()
      return
    }
    const enabled = readWorkflowEmployeeEnabledMap()
    for (const empId of ids) {
      if (!enabled[empId]) continue
      await requestPhoneAgentStart(empId)
      let ps = await fetchPhoneAgentStatusPayload(empId)
      if (!ps.fetchError && !ps.running) {
        await requestPhoneAgentStart(empId)
        ps = await fetchPhoneAgentStatusPayload(empId)
      }
      deps.onStatusUpdate(empId, ps)
    }
  }

  function startPhoneAgentStatusPoll() {
    stopPhoneAgentStatusPoll()
    void pollPhoneAgentStatusForEnabledEmployees()
    phoneAgentPollTimer = window.setInterval(() => {
      void pollPhoneAgentStatusForEnabledEmployees()
    }, PHONE_AGENT_POLL_MS)
  }

  function isPollActive(): boolean {
    return phoneAgentPollTimer != null
  }

  return {
    getEnabledPhoneEmployeeIds,
    requestPhoneAgentStart,
    fetchPhoneAgentStatusPayload,
    startPhoneAgentStatusPoll,
    stopPhoneAgentStatusPoll,
    isPollActive,
  }
}
