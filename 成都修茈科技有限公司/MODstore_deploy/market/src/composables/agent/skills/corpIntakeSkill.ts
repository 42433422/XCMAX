import type { AgentContext, SkillExecuteResult } from '../../../types/agent'
import type { QuickAction } from '../../../content/siteKnowledge'
import { resolveCorpPageId } from '../../../content/siteKnowledge'
import {
  applyDraftSafe,
  scrollToIntake,
  waitForBridge,
  type ContactIntakeState,
  type IntakeStepId,
} from '../../../corp-butler/contactIntakeBridge'
import { intakeFormPlacementHint } from '../../../corp-butler/corpViewport'
import { api } from '../../../api'

export type CorpIntakeMatch =
  | { kind: 'fill' }
  | { kind: 'step'; stepId: IntakeStepId }
  | { kind: 'review' }

function reply(text: string): SkillExecuteResult {
  return { success: true, message: text, assistantReply: text }
}

const STEP_ALIASES: Record<string, IntakeStepId> = {
  profile: 'profile',
  problem: 'problem',
  workflow: 'workflow',
  contact: 'contact',
  plan: 'plan',
  review: 'review',
  '1': 'profile',
  '2': 'problem',
  '3': 'workflow',
  '4': 'contact',
  '5': 'plan',
  '6': 'review',
}

function parseStepFromMessage(q: string): IntakeStepId | null {
  const m = q.match(/第\s*([1-6])\s*题/)
  if (m) return STEP_ALIASES[m[1]] || null
  if (/联系方式|姓名|邮箱|手机/.test(q)) return 'contact'
  if (/核对|预览|提交前|review/.test(q)) return 'review'
  if (/计划|时间|预算|对接/.test(q)) return 'plan'
  if (/流程|日常|怎么做/.test(q)) return 'workflow'
  if (/困扰|头疼|改善/.test(q)) return 'problem'
  if (/认识|岗位|角色|第\s*1/.test(q)) return 'profile'
  return null
}

/** 联系页：问卷填表 / 跳转意图（优先于 corpSiteSkill） */
export function matchCorpIntakeIntent(ctx: AgentContext): CorpIntakeMatch | null {
  if (resolveCorpPageId(ctx.route || '') !== 'contact') return null
  const q = ctx.userMessage.trim()
  if (!q) return null

  if (/填表|问卷|预填|帮我写|填写需求|写入问卷|自动填/.test(q)) return { kind: 'fill' }
  if (/核对|预览|提交前/.test(q)) return { kind: 'review' }
  if (/跳到|跳转|下一步|上一题|去.*题/.test(q)) {
    const step = parseStepFromMessage(q)
    if (step) return { kind: 'step', stepId: step }
  }
  const stepOnly = parseStepFromMessage(q)
  if (stepOnly && /第|步|题|联系方式|核对/.test(q)) return { kind: 'step', stepId: stepOnly }
  return null
}

export async function runIntakeFillFromMessage(
  userMessage: string,
  pageSummary: string,
): Promise<SkillExecuteResult> {
  const bridge = await waitForBridge()
  if (!bridge) {
    scrollToIntake()
    return reply(`${intakeFormPlacementHint()}问卷尚未就绪，请刷新页面后重试；您也可以直接在表单中逐步填写。`)
  }
  if (bridge.isSubmitted()) {
    return reply('您已提交过需求问卷，如需修改请通过电话或邮件联系我们。')
  }

  try {
    const res = (await api.agentCorpIntakeFill({
      message: userMessage,
      current_draft: bridge.getState(),
      page_summary: pageSummary.slice(0, 3500),
    })) as { success?: boolean; reply?: string; draft?: Partial<ContactIntakeState> }

    const draft = res?.draft || {}
    const assistantText = (res?.reply || '').trim()
    if (!Object.keys(draft).length) {
      scrollToIntake()
      return reply(
        assistantText ||
          `我未能从描述中解析出可填写的字段，请补充岗位、日常事务和联系方式，或直接在${intakeFormPlacementHint()}表单填写。`,
      )
    }

    const ok = applyDraftSafe(draft)
    if (!ok) {
      return reply('问卷已提交或不可用，无法继续预填。')
    }

    const filled = Object.keys(draft).filter((k) => {
      const v = draft[k as keyof ContactIntakeState]
      return Array.isArray(v) ? v.length > 0 : String(v ?? '').trim()
    })
    const tail =
      filled.length > 0
        ? `\n\n已尝试写入：${filled.join('、')}。请在${intakeFormPlacementHint()}核对，不确定的项请自行修改。`
        : ''
    return reply((assistantText || `已根据您的描述预填问卷，请在${intakeFormPlacementHint()}逐步核对。`) + tail)
  } catch {
    scrollToIntake()
    return reply(
      `智能预填暂时不可用，已为您定位到问卷区域。请直接在${intakeFormPlacementHint()}分步填写，或稍后再试。`,
    )
  }
}

export async function executeCorpIntakeMatch(
  match: CorpIntakeMatch,
  ctx: AgentContext,
): Promise<SkillExecuteResult> {
  const bridge = await waitForBridge()
  if (!bridge) {
    scrollToIntake()
    return reply(`请先在${intakeFormPlacementHint()}打开需求问卷；若未显示，请刷新页面（Cmd+Shift+R）。`)
  }
  if (bridge.isSubmitted()) {
    return reply('需求问卷已提交，感谢信任！如需补充说明请联系我们的顾问。')
  }

  if (match.kind === 'fill') {
    return runIntakeFillFromMessage(ctx.userMessage, ctx.pageSummary || '')
  }

  if (match.kind === 'review') {
    bridge.goToStep('review')
    scrollToIntake()
    return reply(`已跳转到「核对并提交」步骤，请检查${intakeFormPlacementHint()}摘要后点击提交。`)
  }

  bridge.goToStep(match.stepId)
  scrollToIntake()
  const labels: Record<IntakeStepId, string> = {
    profile: '认识您',
    problem: '您的困扰',
    workflow: '日常事务',
    contact: '联系方式',
    plan: '计划',
    review: '提交',
  }
  return reply(`已跳转到「${labels[match.stepId]}」步骤，请继续在${intakeFormPlacementHint()}填写。`)
}

export async function runIntakeQuickTask(action: QuickAction): Promise<SkillExecuteResult | null> {
  if (!action.task) return null

  const bridge = await waitForBridge()
  if (!bridge && action.task !== 'navigate') {
    scrollToIntake()
    return reply('问卷加载中，请稍候再点任务卡片，或刷新页面。')
  }

  switch (action.task) {
    case 'intake_fill': {
      const prompt =
        action.payload?.prompt?.trim() ||
        action.message?.trim() ||
        `请根据我的描述帮我填写${intakeFormPlacementHint()}需求问卷`
      return runIntakeFillFromMessage(prompt, '')
    }
    case 'intake_step': {
      const stepId = (action.payload?.stepId || 'profile') as IntakeStepId
      if (bridge && !bridge.isSubmitted()) {
        bridge.goToStep(stepId)
        scrollToIntake()
      }
      return reply(`已为您打开问卷的「${stepId}」步骤，请在${intakeFormPlacementHint()}继续填写。`)
    }
    case 'intake_review': {
      if (bridge && !bridge.isSubmitted()) {
        bridge.goToStep('review')
        scrollToIntake()
      }
      return reply(`已打开提交前核对页，请检查${intakeFormPlacementHint()}内容后提交。`)
    }
    case 'navigate': {
      const href = action.payload?.href?.trim()
      if (!href) return reply('请说明要前往的页面。')
      const target = href.startsWith('http') ? href : href
      window.setTimeout(() => {
        window.location.assign(target)
      }, 400)
      return reply(`正在为您打开「${action.label}」…`)
    }
    default:
      return null
  }
}

/** 官网任务卡片统一入口（填表 / 跳步 / 页面跳转） */
export const runCorpQuickTask = runIntakeQuickTask
