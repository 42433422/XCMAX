import type { AgentSkill, SkillResult } from '../../../types/agent'
import { api } from '../../../api'

type SessionSnapshot = {
  status: string
  error?: string | null
  artifact?: Record<string, unknown> | null
}

type SynthesizedAnswer = {
  question: string
  markdown: string
  cited_employees: string[]
  generated_at: string
  model: string
  error?: string
}

type AllHandsReport = {
  ok: boolean
  error?: string
  employees?: Array<{ employee_id: string; name?: string; status?: string }>
  summary?: { ok?: number; total?: number; user_question?: string }
  synthesized_answer?: SynthesizedAnswer | null
}

const POLL_INTERVAL_MS = 2000
const MAX_POLL_MS = 5 * 60 * 1000

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function extractQuestion(args: Record<string, unknown> | undefined, userMessage: string): string {
  const raw = args?.question
  if (typeof raw === 'string' && raw.trim()) return raw.trim()
  const msg = (userMessage || '').trim()
  // 支持 ``/全员大会 ...`` / ``/ask-all-hands ...`` 前缀
  const m = msg.match(/^(?:\/全员大会|\/ask-all-hands|\/allhands)\s+(.+)$/i)
  if (m && m[1]) return m[1].trim()
  return msg
}

function summarizeReply(question: string, report: AllHandsReport): string {
  const synth = report.synthesized_answer
  if (synth && synth.markdown && !synth.error) {
    const cited = (synth.cited_employees || []).join('、') || '—'
    return [
      `# 数字管家综合答复（员工大会 #${(report.summary?.total ?? report.employees?.length ?? 0)} 人）`,
      `> 问题：${question}`,
      '',
      synth.markdown.trim(),
      '',
      `_引用员工：${cited}（模型：${synth.model || '—'}）_`,
    ].join('\n')
  }
  // 综合阶段失败/不可用时退回到「逐员工答复」摘要
  const lines: string[] = [
    `# 员工大会答复（综合阶段不可用）`,
    `> 问题：${question}`,
    '',
  ]
  if (synth?.error) lines.push(`> 综合答复异常：${synth.error}`, '')
  for (const row of report.employees || []) {
    lines.push(`- **[${row.employee_id}]** ${row.name || ''} · 状态：${row.status || '—'}`)
  }
  return lines.join('\n')
}

async function pollSession(sessionId: string): Promise<AllHandsReport> {
  const t0 = Date.now()
  while (Date.now() - t0 < MAX_POLL_MS) {
    const sess = (await api.workbenchGetSession(sessionId)) as SessionSnapshot
    if (sess.status === 'done') {
      const artifact = sess.artifact || {}
      const raw = (artifact as Record<string, unknown>).all_hands_report
      if (raw && typeof raw === 'object') return raw as AllHandsReport
      throw new Error('全员大会会话已完成，但未返回有效报告内容')
    }
    if (sess.status === 'error') {
      throw new Error(String(sess.error || '全员大会失败'))
    }
    await sleep(POLL_INTERVAL_MS)
  }
  throw new Error('全员大会轮询超时（>5 分钟）')
}

export const askAllHandsSkill: AgentSkill = {
  // 同时作为 ``LLMToolCall.name`` 与 skill 内部 ID；
  // ``useAgentEngine.handleToolCalls`` 在不识别工具名时会走 ``skillRegistry.getById(name)`` 兜底，
  // 不加 ``builtin:`` 前缀以便 LLM 可以直接 tool_call 到本技能。
  id: 'ask_all_hands',
  name: '员工大会问答',
  description: '把一个问题转给所有在岗员工讨论，由数字管家做综合答复',
  version: '1.0.0',
  trigger: {
    keywords: [
      '/全员大会',
      '/ask-all-hands',
      '/allhands',
      '员工大会',
      '问全员',
      '召集全员',
      '让所有员工',
    ],
    intent: ['ask_all_hands', 'all_hands', '员工大会'],
  },
  permission: 'execute',
  metadata: { author: 'system', created_at: Date.now(), evolution_count: 0, usage_count: 0 },
  async execute(context, args): Promise<SkillResult> {
    const question = extractQuestion(args, context.userMessage)
    if (!question) {
      return {
        success: false,
        message: '需要先告诉我要问员工大会什么问题',
        assistantReply: '请告诉我你要问员工大会什么问题，例如：`/全员大会 有没有员工负责定时清理过期文件？`',
      }
    }
    try {
      const started = (await api.butlerAllHandsReportStartSession({
        user_question: question,
        synthesize: true,
        with_research: false,
        max_employees: 20,
        concurrency: 2,
      })) as { session_id?: string }
      const sid = String(started?.session_id || '').trim()
      if (!sid) throw new Error('启动员工大会失败：后端未返回 session_id')
      const report = await pollSession(sid)
      const reply = summarizeReply(question, report)
      return {
        success: true,
        message: `员工大会已就「${question.slice(0, 30)}${question.length > 30 ? '…' : ''}」给出综合答复`,
        assistantReply: reply,
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      return {
        success: false,
        message: `员工大会问答失败：${msg}`,
        assistantReply: `员工大会暂时回答不了：${msg}`,
      }
    }
  },
}
