import { useRouter, useRoute } from 'vue-router'
import { useAgentStore } from '../../stores/agent'
import { useAuthStore } from '../../stores/auth'
import { skillRegistry } from '../../utils/agent/agentSkillRegistry'
import { useActionExecutor } from './useActionExecutor'
import { usePageAnalyzer } from './usePageAnalyzer'
import { serializeVisibleDom } from '../../utils/agent/pageSerializer'
import type { AgentContext, AgentMessage, LLMResponse, LLMToolCall } from '../../types/agent'
import { api } from '../../api'
import { getMarketPageKnowledge, getStructuredPageSummary } from '../../content/siteKnowledge'
import { checkXiaoCLifeAction, minimumSkillLevel } from './xiaocLifeActionGuard'

let _msgId = 0
function nextId() {
  return `msg-${Date.now()}-${++_msgId}`
}

function makeUserMsg(content: string): AgentMessage {
  return { id: nextId(), role: 'user', content, timestamp: Date.now() }
}

function makeAssistantMsg(content: string, isLoading = false): AgentMessage {
  return { id: nextId(), role: 'assistant', content, timestamp: Date.now(), isLoading }
}

interface AgentTurn {
  conversationId: number | null
  signal: AbortSignal
  isCurrent: () => boolean
  updateReply: (patch: Partial<AgentMessage>) => void
}

export function useAgentEngine() {
  const _router = useRouter()
  const route = useRoute()
  const agentStore = useAgentStore()
  const auth = useAuthStore()
  const executor = useActionExecutor()
  const { getPageContext } = usePageAnalyzer()

  /** 主入口：处理用户输入 */
  async function handleInput(
    userText: string,
    opts?: { withScreenshot?: boolean; imageDataUrl?: string | null; skipUserInsert?: boolean },
  ): Promise<void> {
    const text = userText.trim()
    const uploaded = typeof opts?.imageDataUrl === 'string' ? opts.imageDataUrl.trim() : ''
    if ((!text && !uploaded && !opts?.withScreenshot) || agentStore.isLoading) return
    const history = agentStore.messages.filter((message) => !message.isLoading && !message.isError).slice(-12)
    const generation = agentStore.conversationGeneration
    const owner = auth.user?.id
    const controller = new AbortController()
    agentStore.requestController = controller
    agentStore.isLoading = true
    agentStore.setMode('thinking')

    const displayText = text || (uploaded || opts?.withScreenshot ? '[图片]' : '')
    if (opts?.skipUserInsert && history.at(-1)?.role === 'user' && history.at(-1)?.content === displayText) history.pop()
    if (!opts?.skipUserInsert) agentStore.addMessage(makeUserMsg(displayText))
    const existingReply = opts?.skipUserInsert ? agentStore.messages.at(-1) : undefined
    const reply = existingReply?.role === 'assistant' && existingReply.isLoading ? existingReply : makeAssistantMsg('…', true)
    if (reply !== existingReply) agentStore.addMessage(reply)
    const isCurrent = () => generation === agentStore.conversationGeneration && owner === auth.user?.id && !controller.signal.aborted
    const turn: AgentTurn = {
      conversationId: agentStore.currentConversationId,
      signal: controller.signal,
      isCurrent,
      updateReply: (patch) => {
        if (isCurrent()) agentStore.updateMessage(reply.id, patch)
      },
    }

    try {
      const routeName = route.name ? String(route.name) : null
      const domExcerpt = serializeVisibleDom().slice(0, 800)
      const context: AgentContext = {
        route: route.fullPath,
        pageTitle: document.title,
        pageSummary: getStructuredPageSummary({ routeName, domExcerpt }),
        userMessage: text || displayText,
        history,
      }

      // 有附图时跳过离线技能，直接走 LLM vision
      if (!uploaded && !opts?.withScreenshot) {
        const matchedSkill = skillRegistry.matchByIntent(context)
        if (matchedSkill && !turn.conversationId) {
          const blocked = await checkXiaoCLifeAction(minimumSkillLevel(matchedSkill.id))
          if (!isCurrent()) return
          if (!blocked) {
            const result = await matchedSkill.execute(context)
            if (!isCurrent()) return
            turn.updateReply({ content: result.assistantReply || result.message, isLoading: false, isError: !result.success })
            agentStore.setMode(result.success ? 'idle' : 'error')
            return
          }
          // An unavailable action does not prevent L1 from answering with advice.
        }
      }

      // Phase 3+: LLM brain
      await callLLMBrain(context, turn, {
        withScreenshot: opts?.withScreenshot ?? false,
        imageDataUrl: uploaded || null,
      })
    } catch (e: unknown) {
      if (!isCurrent()) return
      const msg = e instanceof Error ? e.message : String(e)
      turn.updateReply({ content: `出错了：${msg}`, isLoading: false, isError: true })
      agentStore.setMode('error')
    } finally {
      if (isCurrent()) {
        agentStore.requestController = null
        agentStore.isLoading = false
        if (agentStore.mode === 'thinking') agentStore.setMode('idle')
      }
    }
  }

  async function callLLMBrain(context: AgentContext, turn: AgentTurn, opts: { withScreenshot: boolean; imageDataUrl?: string | null }) {
    let screenshotDataUrl: string | null =
      typeof opts.imageDataUrl === 'string' && opts.imageDataUrl.trim() ? opts.imageDataUrl.trim() : null
    if (!screenshotDataUrl && opts.withScreenshot) {
      try {
        const { captureViewport } = await import('../../utils/agent/screenshotCapture')
        const captured = await captureViewport({ signal: turn.signal, autoTextFallback: false })
        if (!captured.ok || captured.kind !== 'image' || !captured.dataUrl?.startsWith('data:image/')) {
          throw new Error('Missing screenshot')
        }
        screenshotDataUrl = captured.dataUrl
      } catch {
        throw new Error('页面截图未取得，请重新截图或上传图片后再发送。')
      }
    }
    if (!turn.isCurrent()) return

    // 构建 messages 列表
    const systemMsg = {
      role: 'system',
      content: buildSystemPrompt(context),
    }

    const historyMsgs = context.history
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-10)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))

    // 末尾用户消息（含可选截图/上传图）
    let userContent: unknown = context.userMessage
    if (screenshotDataUrl) {
      userContent = [
        { type: 'text', text: context.userMessage },
        { type: 'image_url', image_url: { url: screenshotDataUrl, detail: 'low' } },
      ]
    }
    const userApiMsg = { role: 'user', content: userContent }

    const messages = [systemMsg, ...historyMsgs, userApiMsg]

    const response = (await api.agentButlerChat(
      {
        messages,
        conversation_id: turn.conversationId,
        page_context: context.pageSummary,
      },
      turn.signal,
    )) as LLMResponse
    if (!turn.isCurrent()) return
    if (!response || response.success === false) {
      throw new Error(response?.message || '未收到有效回复，请重试本轮对话。')
    }

    const tools = Array.isArray(response.tool_calls) ? response.tool_calls : []
    const replyText = typeof response.text === 'string' ? response.text.trim() : ''
    if (!tools.length && !replyText) throw new Error('未收到有效回复，请重试本轮对话。')
    if (response.conversation_id) agentStore.currentConversationId = response.conversation_id

    // 处理 tool_calls
    if (tools.length) {
      await handleToolCalls(tools, context, turn)
    } else {
      turn.updateReply({ content: replyText, isLoading: false })
    }
  }

  async function handleToolCalls(toolCalls: LLMToolCall[], _context: AgentContext, turn: AgentTurn) {
    const firstTool = toolCalls[0]
    const blocked = await checkXiaoCLifeAction(toolCalls.length > 1 ? 3 : 2)
    if (!turn.isCurrent()) return
    if (blocked) {
      turn.updateReply({ content: blocked.message, isLoading: false, isError: true })
      return
    }
    const name = firstTool.name
    const args = firstTool.args as Record<string, unknown>

    turn.updateReply({ content: `正在执行：${name}…`, isLoading: true })
    agentStore.setMode('operating')

    let result
    switch (name) {
      case 'navigate':
        result = await executor.navigate(args as Parameters<typeof executor.navigate>[0])
        break
      case 'click':
        result = await executor.click(args as Parameters<typeof executor.click>[0])
        break
      case 'fill':
        result = await executor.fill(args as Parameters<typeof executor.fill>[0])
        break
      case 'select':
        result = await executor.select(args as Parameters<typeof executor.select>[0])
        break
      case 'scroll':
        result = await executor.scroll(args as Parameters<typeof executor.scroll>[0])
        break
      case 'read':
        result = await executor.read()
        break
      case 'enhance_current_page':
        result = await executor.enhanceCurrentPage(args as Parameters<typeof executor.enhanceCurrentPage>[0])
        break
      default: {
        // 尝试 E-Skill
        const skill = skillRegistry.getById(name)
        if (skill) {
          const ctx: AgentContext = {
            route: route.fullPath,
            pageTitle: document.title,
            pageSummary: getPageContext(),
            userMessage: '',
            history: agentStore.messages.slice(-6),
          }
          const blockedSkill = await checkXiaoCLifeAction(minimumSkillLevel(skill.id))
          if (!turn.isCurrent()) return
          result = blockedSkill ?? (await skill.execute(ctx, args))
        } else {
          result = { success: false, message: `未知工具：${name}` }
        }
      }
    }

    if (!turn.isCurrent()) return
    turn.updateReply({
      content: result.assistantReply || result.message,
      isLoading: false,
      isError: !result.success,
    })
    agentStore.setMode(result.success ? 'idle' : 'error')
  }

  function buildSystemPrompt(context: AgentContext): string {
    const routeName = route.name ? String(route.name) : ''
    const pageGuide = getMarketPageKnowledge(routeName)
    const guideBlock = pageGuide
      ? `\n当前页面说明（${pageGuide.title}）：\n${pageGuide.summary}\n要点：${pageGuide.highlights.join('；')}\n`
      : ''

    return `你是「XC AGI 数字管家」小C——这个平台的专属 AI 助手，不是用户购买的 AI 员工。
你可以帮用户：
- 导航到任意页面（plans/ai-store/wallet/recharge/account/workbench-shell/orders/templates/dev 等路由）
- 读取当前页面内容并回答问题
- 帮用户找到合适的 AI 员工
- 引导用户完成充值、购买会员等操作
- 主动建议合适的功能和员工

当前页面路径：${context.route}
${guideBlock}
页面摘要：
${context.pageSummary}

重要原则：
1. 低风险操作（导航、读取）直接执行；中风险（填表、点击）展示预览；高风险（支付）必须用户明确确认
2. 不要主动替用户完成付款，只引导到页面
3. 每次操作后告知用户已完成了什么
4. 回复简短、友好，不要过多解释
5. 如需执行页面操作，使用 function calling 工具

可用工具：navigate（跳转）、click（点击）、fill（填写）、select（选择）、scroll（滚动）、read（读取页面）、enhance_current_page（vibe-coding 改写 Mod/工作流/员工，高风险，需确认）`
  }

  return { handleInput }
}
