import type { AgentSkill, AgentContext } from '../../types/agent'

class SkillRegistry {
  private skills: Map<string, AgentSkill> = new Map()

  register(skill: AgentSkill): void {
    this.skills.set(skill.id, skill)
  }

  unregister(id: string): void {
    this.skills.delete(id)
  }

  getAll(): AgentSkill[] {
    return Array.from(this.skills.values())
  }

  getById(id: string): AgentSkill | undefined {
    return this.skills.get(id)
  }

  /** 根据用户消息和页面上下文匹配最合适的技能（关键词 + 意图 + 路由） */
  matchByIntent(context: AgentContext): AgentSkill | null {
    const text = context.userMessage.toLowerCase()
    const route = context.route

    let bestMatch: AgentSkill | null = null
    let bestScore = 0

    for (const skill of this.skills.values()) {
      let score = 0

      // 关键词匹配
      if (skill.trigger.keywords) {
        for (const kw of skill.trigger.keywords) {
          if (text.includes(kw.toLowerCase())) {
            score += 2
          }
        }
      }

      // 意图匹配
      if (skill.trigger.intent) {
        for (const intent of skill.trigger.intent) {
          if (text.includes(intent.toLowerCase())) {
            score += 3
          }
        }
      }

      // 路由上下文加权
      if (skill.trigger.context) {
        for (const ctx of skill.trigger.context) {
          if (route.startsWith(ctx)) {
            score += 1
          }
        }
      }

      if (score > bestScore) {
        bestScore = score
        bestMatch = skill
      }
    }

    return bestScore >= 2 ? bestMatch : null
  }

  /** 返回适合当前上下文的技能列表（供 LLM function calling 生成 tool schema） */
  getSkillsForContext(route: string): AgentSkill[] {
    return this.getAll().filter((s) => {
      if (!s.trigger.context || s.trigger.context.length === 0) return true
      return s.trigger.context.some((ctx) => route.startsWith(ctx))
    })
  }
}

export const skillRegistry = new SkillRegistry()
