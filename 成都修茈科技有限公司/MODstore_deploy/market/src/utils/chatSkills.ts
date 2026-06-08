/**
 * 工作台一档「直接对话」的技能开关定义与 system prompt 组装。
 * 与 SkillToolbar.vue 共用同一份 SkillDef，便于后续把 toolbar 抽成数据驱动。
 */

export interface SkillDef {
  id: string
  label: string
  icon: string
  tip: string
}

export const ALL_SKILLS: SkillDef[] = [
  { id: 'web', label: '联网搜索', icon: '🌐', tip: '与顶栏「联网搜索」相同：发送前检索公开网页摘要；也可在顶栏开关' },
  { id: 'think', label: '深度思考', icon: '🧠', tip: '展开思维链，更慢但更稳的推理；适合解题/方案推演' },
  { id: 'translate', label: '翻译', icon: '🌍', tip: '把消息翻译为目标语言（默认中英互译）' },
  { id: 'write', label: 'AI 写作', icon: '✍️', tip: '小红书 / 公众号 / 周报 / 公文等写作模板' },
  { id: 'code', label: 'AI 编程', icon: '💻', tip: '专注代码生成、解释、调试，输出可运行片段' },
  { id: 'data', label: '数据分析', icon: '📊', tip: '上传 CSV/Excel 后，自动给统计、图表建议、结论' },
  { id: 'study', label: '学术搜索', icon: '🎓', tip: '偏论文 / 文献 / 专业资料检索，附引用来源' },
]

export function buildSkillSystemPrompt(active: string[]): string {
  const parts: string[] = []
  if (active.includes('web')) parts.push('用户已启用「联网搜索」：系统会在发送前注入「网页检索摘要」块；你必须优先依据该块与附件作答，回答末尾列出参考链接（标题 + URL），并说明信息可能滞后。')
  if (active.includes('think')) parts.push('用户已启用「深度思考」：在最终答案前用「思路：」前缀简要写出 3-5 步推理脉络，再写「结论：」。')
  if (active.includes('translate')) parts.push('用户已启用「翻译」模式：默认把用户输入翻译为目标语言（中文输入→英文，其它→中文），保持人称与语气；若用户已在消息中指定目标语言以指定为准。')
  if (active.includes('write')) parts.push('用户已启用「AI 写作」：擅长小红书种草、公众号、周报、公文、广告文案；结构清晰、富有节奏，必要时附标题候选与正文。')
  if (active.includes('code')) parts.push('用户已启用「AI 编程」：默认输出可直接运行的代码（用 ``` 代码块包裹并标注语言），先给文件路径与依赖，再给完整代码，最后给 1-3 句风险/边界说明。')
  if (active.includes('data')) parts.push('用户已启用「数据分析」：若涉及数值或表格，给出列说明、数据清洗思路、统计指标（均值/分位数/分布）、并以 markdown 表格 + 文字结论呈现，必要时给 mermaid 流程图说明分析步骤。')
  if (active.includes('study')) parts.push('用户已启用「学术搜索」：以学术口吻输出，列出 3-5 条参考文献（作者、标题、年份、期刊/会议），并标注每条的核心结论。')
  return parts.join('\n\n')
}

export const SKILL_STORAGE_KEY = 'workbench_direct_skills_v1'

export function loadActiveSkills(): string[] {
  try {
    const raw = localStorage.getItem(SKILL_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function saveActiveSkills(active: string[]): void {
  try {
    localStorage.setItem(SKILL_STORAGE_KEY, JSON.stringify(Array.isArray(active) ? active : []))
  } catch {
    /* ignore */
  }
}
