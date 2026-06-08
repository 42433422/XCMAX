import type { AgentSkill } from '../../../types/agent'

export function createWalletRechargeSkill(router: ReturnType<typeof import('vue-router').useRouter>): AgentSkill {
  return {
    id: 'builtin:wallet_recharge',
    name: '钱包充值',
    description: '引导用户前往充值页面',
    version: '1.0.0',
    trigger: {
      keywords: ['充值', '充钱', '余额不足', '添加余额', '加钱', 'recharge', '提现'],
      intent: ['recharge', 'wallet', '充值'],
    },
    permission: 'execute',
    metadata: { author: 'system', created_at: Date.now(), evolution_count: 0, usage_count: 0 },
    async execute(_context, _args) {
      try {
        await router.push({ name: 'recharge' })
        return {
          success: true,
          message: '已跳转到充值页面',
          assistantReply: '好的，已为您打开充值页面，请选择充值金额。',
        }
      } catch (e: unknown) {
        return { success: false, message: `跳转失败：${e instanceof Error ? e.message : String(e)}` }
      }
    },
  }
}
