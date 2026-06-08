import type { AgentSkill } from '../../../types/agent'

export function createPurchasePlanSkill(router: ReturnType<typeof import('vue-router').useRouter>): AgentSkill {
  return {
    id: 'builtin:purchase_plan',
    name: '购买会员套餐',
    description: '引导用户购买指定会员套餐（高风险：需要明确确认）',
    version: '1.0.0',
    trigger: {
      keywords: ['购买会员', '开会员', '升级会员', '买会员', '会员套餐', 'pro', 'vip', '升级'],
      intent: ['purchase', 'buy', 'subscribe', '购买', '升级'],
    },
    permission: 'full',
    metadata: { author: 'system', created_at: Date.now(), evolution_count: 0, usage_count: 0 },
    async execute(_context, _args) {
      try {
        await router.push({ name: 'plans' })
        return {
          success: true,
          message: '已跳转到会员套餐页面',
          assistantReply: '已为您打开会员套餐页面，请选择适合您的套餐。点击购买按钮时我会再次为您确认。',
        }
      } catch (e: unknown) {
        return { success: false, message: `跳转失败：${e instanceof Error ? e.message : String(e)}` }
      }
    },
  }
}
