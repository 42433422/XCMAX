import { ref } from 'vue'
import { useAgentStore } from '../../stores/agent'
import { buildActionPermission } from '../../utils/agent/agentPrivacyConfig'
import type { ActionRisk, PendingAction } from '../../types/agent'

let _actionCounter = 0

export function usePrivacyManager() {
  const agentStore = useAgentStore()
  const error = ref('')

  /**
   * 请求执行动作。
   * - low risk → 立即通过
   * - medium risk → 显示预览卡，用户可取消
   * - high risk → 显示强确认弹窗
   * 返回 true 表示用户同意，false 表示取消/拒绝
   */
  async function requestAction(
    action: string,
    risk: ActionRisk,
    label: string,
    args: Record<string, unknown> = {},
  ): Promise<boolean> {
    const permission = buildActionPermission(action, risk, label, args)

    if (permission.confirmStrategy === 'auto') return true

    // 生成 pending action，等待用户确认
    return new Promise<boolean>((resolve) => {
      const id = `action-${++_actionCounter}`
      const pending: PendingAction = {
        id,
        action,
        label,
        risk,
        args,
        resolve: (confirmed: boolean) => {
          agentStore.setPendingAction(null)
          resolve(confirmed)
        },
      }
      agentStore.setPendingAction(pending)
    })
  }

  return { requestAction, error }
}
