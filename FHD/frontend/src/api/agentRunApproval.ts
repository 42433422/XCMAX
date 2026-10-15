import agentRunsApi from './agentRuns'
import type { AgentRunResponse } from './agentRuns'

/** 确认凭证失效时给用户看的提示（#2289）；后端 403 校验保持不变。 */
export const APPROVAL_GRANT_REJECTED_MESSAGE =
  '确认凭证已过期或与当前步骤不匹配，已自动重新获取但仍无法继续。请刷新任务后再点「审批并执行」，或在对话里重新下达指令。'
export const APPROVAL_GRANT_MISSING_MESSAGE = '任务当前没有可用的审批凭证'

interface ApproveOptions {
  runtimeContext?: Record<string, unknown>
  /** 取到凭证后、真正继续前再确认调用方仍然有效（如工作区已切换则放弃）。 */
  isCurrent?: () => boolean
}

function isForbidden(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && (error as { status?: unknown }).status === 403)
}

/**
 * 每次都现取凭证再继续；遇到 403（凭证过期/步骤已变化）时重新获取一次凭证重试，
 * 仍被拒绝则抛出可直接展示的错误，绝不静默失败。调用方失效时返回 null 且不继续。
 */
export async function approveRunWithFreshGrant(runId: string, options: ApproveOptions = {}): Promise<AgentRunResponse | null> {
  const attempt = async (): Promise<AgentRunResponse | null> => {
    const snapshot = await agentRunsApi.getRun(runId)
    if (options.isCurrent && !options.isCurrent()) return null
    const grant = String(snapshot.approval?.grant || '').trim()
    if (!grant) throw new Error(APPROVAL_GRANT_MISSING_MESSAGE)
    return agentRunsApi.continueRun(runId, {
      approval_grant: grant,
      ...(options.runtimeContext ? { runtime_context: options.runtimeContext } : {}),
    })
  }
  try {
    return await attempt()
  } catch (error) {
    if (!isForbidden(error)) throw error
  }
  try {
    return await attempt()
  } catch (error) {
    if (isForbidden(error)) throw new Error(APPROVAL_GRANT_REJECTED_MESSAGE)
    throw error
  }
}
