import { reactive } from 'vue'

/** 审批方式：手动（每项确认）/ 自动（自动通过并留记录）。 */
export type ApprovalMode = 'manual' | 'auto'

export interface ApprovalModeState {
  enabled: boolean
  mode: ApprovalMode
}

const STORAGE_KEY = 'xcagi_approval_mode'

function readState(): ApprovalModeState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ApprovalModeState> | null
      if (parsed && typeof parsed === 'object') {
        return {
          enabled: parsed.enabled === true,
          mode: parsed.mode === 'auto' ? 'auto' : 'manual',
        }
      }
    }
  } catch {
    // 非浏览器环境 / 隐私模式
  }
  return { enabled: false, mode: 'manual' }
}

/** 模块级单例：跨组件共享同一审批状态。 */
const state = reactive<ApprovalModeState>(readState())

function persist(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 忽略配额 / 隐私模式错误
  }
}

/**
 * 全局审批模式（Codex 风格）：开关 + 手动/自动两档。
 * 审批记录仍由后端写入审批工作台，本层只控制前端是否自动确认。
 */
export function useApprovalMode() {
  function setEnabled(enabled: boolean): void {
    state.enabled = enabled
    persist()
  }

  function setMode(mode: ApprovalMode): void {
    state.mode = mode
    persist()
  }

  return { state, setEnabled, setMode }
}