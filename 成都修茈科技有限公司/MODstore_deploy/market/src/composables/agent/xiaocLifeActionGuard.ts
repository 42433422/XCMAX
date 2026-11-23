import { useAuthStore } from '../../stores/auth'
import { xiaocLifeApi } from '../../application/xiaocLifeApi'
import type { SkillResult } from '../../types/agent'

/** Fresh server read immediately before a management-side action; never a UI-cache permission. */
export async function checkXiaoCLifeAction(requiredLevel = 2, isCurrent = () => true): Promise<SkillResult | null> {
  const cancelled = { success: false, message: '原会话已停止或变化，本次工具未执行。' }
  if (!isCurrent()) return cancelled
  const auth = useAuthStore()
  if (!auth.isAdmin && auth.currentMode !== 'admin') return null
  const actor = auth.user?.id
  try {
    const state = await xiaocLifeApi.read()
    if (!isCurrent()) return cancelled
    if (actor !== auth.user?.id || !auth.isAdmin) {
      return { success: false, message: '管理账号已变化，请重新提出操作请求。' }
    }
    if (state.scope !== 'enterprise' || !Number.isInteger(state.level) || state.level < requiredLevel || state.level > 6) {
      return {
        success: false,
        message:
          requiredLevel > 2
            ? '当前自主模式不允许多步骤或员工编排，请调至 L3 以上后重新提出请求。'
            : '当前小 C 为对话模式，页面工具未执行。',
      }
    }
    return null
  } catch {
    return { success: false, message: '无法核实企业小 C 的最新自主模式，本次工具未执行。' }
  }
}

export function minimumSkillLevel(skillId: string) {
  return ['builtin:navigate', 'builtin:read_page', 'builtin:search_employee', 'builtin:wallet_recharge', 'builtin:purchase_plan'].includes(
    skillId,
  )
    ? 2
    : 3
}
