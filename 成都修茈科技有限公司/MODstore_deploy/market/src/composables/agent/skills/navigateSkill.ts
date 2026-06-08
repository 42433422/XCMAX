import type { AgentSkill } from '../../../types/agent'
import { ROUTE_NAME_MAP } from '../../../utils/agent/agentActionTypes'

export function createNavigateSkill(router: ReturnType<typeof import('vue-router').useRouter>): AgentSkill {
  return {
    id: 'builtin:navigate',
    name: '页面导航',
    description: '帮助用户跳转到指定页面',
    version: '1.0.0',
    trigger: {
      keywords: ['去', '跳转', '打开', '进入', '导航', 'go', 'open', '到'],
      intent: ['navigate', '页面'],
    },
    permission: 'execute',
    metadata: { author: 'system', created_at: Date.now(), evolution_count: 0, usage_count: 0 },
    async execute(context) {
      const text = context.userMessage.toLowerCase()

      // 尝试从消息中提取目标路由
      let targetRouteName = ''
      for (const [kw, routeName] of Object.entries(ROUTE_NAME_MAP)) {
        if (text.includes(kw.toLowerCase())) {
          targetRouteName = routeName
          break
        }
      }

      if (!targetRouteName) {
        return { success: false, message: '未能识别目标页面，请说出具体页面名（例如：去会员页、打开钱包）。' }
      }

      try {
        await router.push({ name: targetRouteName })
        return {
          success: true,
          message: `已跳转到 ${targetRouteName}`,
          assistantReply: `好的，已为您跳转到目标页面。`,
        }
      } catch (e: unknown) {
        return { success: false, message: `导航失败：${e instanceof Error ? e.message : String(e)}` }
      }
    },
  }
}
