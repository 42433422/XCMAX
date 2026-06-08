import type { AgentSkill } from '../../../types/agent'

export function createSearchEmployeeSkill(router: ReturnType<typeof import('vue-router').useRouter>): AgentSkill {
  return {
    id: 'builtin:search_employee',
    name: '搜索 AI 员工',
    description: '在 AI 市场中搜索并推荐合适的员工',
    version: '1.0.0',
    trigger: {
      keywords: ['搜索员工', '找员工', '查找员工', '有没有', '推荐员工', '查询员工', '员工市场', '找一个'],
      intent: ['search', 'find_employee', '员工', 'employee'],
    },
    permission: 'execute',
    metadata: { author: 'system', created_at: Date.now(), evolution_count: 0, usage_count: 0 },
    async execute(context, args) {
      const query = (args?.query as string) || context.userMessage
      try {
        await router.push({ name: 'ai-store', query: { q: query } })
        return {
          success: true,
          message: `已前往 AI 市场搜索：${query}`,
          assistantReply: `好的，已为您在 AI 市场中搜索「${query}」，请查看搜索结果。`,
        }
      } catch (e: unknown) {
        return { success: false, message: `跳转失败：${e instanceof Error ? e.message : String(e)}` }
      }
    },
  }
}
