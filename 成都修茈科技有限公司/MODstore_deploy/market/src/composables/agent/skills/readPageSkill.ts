import type { AgentSkill } from '../../../types/agent'
import { serializeVisibleDom } from '../../../utils/agent/pageSerializer'

export const readPageSkill: AgentSkill = {
  id: 'builtin:read_page',
  name: '读取页面内容',
  description: '读取并总结当前页面的内容，帮助用户了解页面信息',
  version: '1.0.0',
  trigger: {
    keywords: ['这里有什么', '页面', '有什么', '看看', '读取', '告诉我', '介绍', '什么内容'],
    intent: ['read', 'summary', '总结', '简介'],
  },
  permission: 'read',
  metadata: { author: 'system', created_at: Date.now(), evolution_count: 0, usage_count: 0 },
  async execute(context) {
    const summary = serializeVisibleDom()
    const short = summary.slice(0, 600)
    return {
      success: true,
      message: short,
      assistantReply: `当前页面信息如下：\n${short}`,
    }
  },
}
