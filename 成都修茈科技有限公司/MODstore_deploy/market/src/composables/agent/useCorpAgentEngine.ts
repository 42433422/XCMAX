import { useAgentStore } from '../../stores/agent'
import { serializeVisibleDom } from '../../utils/agent/pageSerializer'
import type { AgentContext, AgentMessage } from '../../types/agent'
import type { QuickAction } from '../../content/siteKnowledge'
import { matchCorpSiteIntent } from './skills/corpSiteSkill'
import {
  executeCorpIntakeMatch,
  matchCorpIntakeIntent,
  runIntakeFillFromMessage,
  runCorpQuickTask,
} from './skills/corpIntakeSkill'
import {
  CORP_LINKS,
  getCorpPageKnowledge,
  getStructuredPageSummary,
  resolveCorpPageId,
} from '../../content/siteKnowledge'
import { api } from '../../api'
import { intakeFormPlacementHint } from '../../corp-butler/corpViewport'

let _msgId = 0
function nextId() {
  return `corp-msg-${Date.now()}-${++_msgId}`
}

function makeUserMsg(content: string): AgentMessage {
  return { id: nextId(), role: 'user', content, timestamp: Date.now() }
}

function makeAssistantMsg(content: string, isLoading = false): AgentMessage {
  return { id: nextId(), role: 'assistant', content, timestamp: Date.now(), isLoading }
}

function fallbackReply(origin: string): string {
  return (
    `我是修茈科技官网 AI 管家，可以解答产品、案例与预约咨询。\n\n` +
    `• 产品能力 → ${origin}${CORP_LINKS.services}\n` +
    `• 预约沟通 → ${origin}${CORP_LINKS.contact}\n` +
    `• 登录 AI 市场 → ${origin}${CORP_LINKS.market}\n\n` +
    `您也可以直接问：「有哪些产品？」「怎么联系你们？」`
  )
}

/** 官网静态站 / 公开落地页对话引擎（问卷技能优先，关键词次之，可选 corp-chat LLM） */
export function useCorpAgentEngine() {
  const agentStore = useAgentStore()

  async function finishWithReply(thinkingMsgId: string, text: string, mode: 'idle' | 'error' = 'idle') {
    agentStore.updateLastMessage({ content: text, isLoading: false })
    agentStore.setMode(mode)
    agentStore.isLoading = false
  }

  async function handleInput(userText: string, opts?: { skipUserInsert?: boolean }): Promise<void> {
    const text = userText.trim()
    if (!text) return

    agentStore.isLoading = true
    agentStore.setMode('thinking')
    if (!opts?.skipUserInsert) {
      agentStore.addMessage(makeUserMsg(text))
      agentStore.addMessage(makeAssistantMsg('…', true))
    }

    const pathname = `${location.pathname}`
    const pageId = resolveCorpPageId(pathname)
    const domExcerpt = serializeVisibleDom().slice(0, 800)

    try {
      const context: AgentContext = {
        route: `${location.pathname}${location.search}`,
        pageTitle: document.title,
        pageSummary: getStructuredPageSummary({ corpPathname: pathname, domExcerpt }),
        userMessage: text,
        history: agentStore.messages.slice(-12),
      }

      const intakeMatch = matchCorpIntakeIntent(context)
      if (intakeMatch) {
        const intakeResult = await executeCorpIntakeMatch(intakeMatch, context)
        if (intakeResult?.assistantReply) {
          await finishWithReply('', intakeResult.assistantReply)
          return
        }
      }

      const matched = matchCorpSiteIntent(context)
      if (matched?.assistantReply) {
        await finishWithReply('', matched.assistantReply)
        return
      }

      if (pageId === 'contact' && /填|问卷|预填|跟单|录入|单据|excel/i.test(text)) {
        const fillResult = await runIntakeFillFromMessage(text, context.pageSummary || '')
        if (fillResult?.assistantReply) {
          await finishWithReply('', fillResult.assistantReply)
          return
        }
      }

      const llmReply = await tryCorpLlmChat(text, pageId, context.pageSummary, context.history)
      const reply = llmReply || fallbackReply(location.origin)
      await finishWithReply('', reply)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      await finishWithReply('', `暂时无法处理：${msg}`, 'error')
    } finally {
      agentStore.isLoading = false
      if (agentStore.mode === 'thinking') agentStore.setMode('idle')
    }
  }

  async function runIntakeTask(action: QuickAction): Promise<void> {
    const label = action.label.trim()
    if (!label && !action.task) return

    agentStore.isLoading = true
    agentStore.setMode('thinking')
    if (action.message?.trim()) {
      agentStore.addMessage(makeUserMsg(action.message.trim()))
    } else {
      agentStore.addMessage(makeUserMsg(label))
    }
    agentStore.addMessage(makeAssistantMsg('…', true))

    try {
      const taskResult = await runCorpQuickTask(action)
      if (taskResult?.assistantReply) {
        await finishWithReply('', taskResult.assistantReply)
        return
      }
      if (action.message?.trim()) {
        await handleInput(action.message.trim(), { skipUserInsert: true })
        return
      }
      await finishWithReply('', `已收到，请继续在${intakeFormPlacementHint()}问卷中填写。`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      await finishWithReply('', `暂时无法处理：${msg}`, 'error')
    } finally {
      agentStore.isLoading = false
      if (agentStore.mode === 'thinking') agentStore.setMode('idle')
    }
  }

  return { handleInput, runIntakeTask }
}

async function tryCorpLlmChat(
  userText: string,
  pageId: string,
  pageContext: string,
  history: AgentMessage[],
): Promise<string | null> {
  try {
    const page = getCorpPageKnowledge(pageId)
    const historyMsgs = history
      .filter((m) => (m.role === 'user' || m.role === 'assistant') && !m.isLoading)
      .slice(-8)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))

    const res = (await api.agentCorpChat({
      messages: [...historyMsgs, { role: 'user', content: userText }],
      page_id: pageId,
      page_context: `${page.title}\n${page.summary}\n\n${pageContext}`.slice(0, 3500),
    })) as { content?: string; message?: string; success?: boolean }

    const text = (res?.content || res?.message || '').trim()
    return text || null
  } catch {
    return null
  }
}
