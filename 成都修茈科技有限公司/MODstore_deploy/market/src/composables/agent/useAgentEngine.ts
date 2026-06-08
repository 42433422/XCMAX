import { useRouter, useRoute } from 'vue-router'
import { useAgentStore } from '../../stores/agent'
import { skillRegistry } from '../../utils/agent/agentSkillRegistry'
import { useActionExecutor } from './useActionExecutor'
import { usePageAnalyzer } from './usePageAnalyzer'
import { serializeVisibleDom } from '../../utils/agent/pageSerializer'
import type { AgentContext, AgentMessage, LLMResponse, LLMToolCall } from '../../types/agent'
import { api } from '../../api'
import { getMarketPageKnowledge, getStructuredPageSummary } from '../../content/siteKnowledge'

let _msgId = 0
function nextId() { return `msg-${Date.now()}-${++_msgId}` }

function makeUserMsg(content: string): AgentMessage {
  return { id: nextId(), role: 'user', content, timestamp: Date.now() }
}

function makeAssistantMsg(content: string, isLoading = false): AgentMessage {
  return { id: nextId(), role: 'assistant', content, timestamp: Date.now(), isLoading }
}

export function useAgentEngine() {
  const router = useRouter()
  const route = useRoute()
  const agentStore = useAgentStore()
  const executor = useActionExecutor()
  const { getPageContext } = usePageAnalyzer()

  /** 主入口：处理用户输入 */
  async function handleInput(userText: string, opts?: { withScreenshot?: boolean }): Promise<void> {
    if (!userText.trim()) return
    agentStore.isLoading = true
    agentStore.setMode('thinking')

    const userMsg = makeUserMsg(userText)
    agentStore.addMessage(userMsg)

    const thinkingMsg = makeAssistantMsg('…', true)
    agentStore.addMessage(thinkingMsg)

    try {
      const routeName = route.name ? String(route.name) : null
      const domExcerpt = serializeVisibleDom().slice(0, 800)
      const context: AgentContext = {
        route: route.fullPath,
        pageTitle: document.title,
        pageSummary: getStructuredPageSummary({ routeName, domExcerpt }),
        userMessage: userText,
        history: agentStore.messages.slice(-12),
      }

      // 先尝试关键词匹配（Phase 1/2 离线路径）
      const matchedSkill = skillRegistry.matchByIntent(context)
      if (matchedSkill && !agentStore.currentConversationId) {
        const result = await matchedSkill.execute(context)
        agentStore.updateLastMessage({
          content: result.assistantReply || result.message,
          isLoading: false,
        })
        agentStore.setMode('idle')
        agentStore.isLoading = false
        return
      }

      // Phase 3+: LLM brain
      await callLLMBrain(context, opts?.withScreenshot ?? false)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      agentStore.updateLastMessage({ content: `出错了：${msg}`, isLoading: false })
      agentStore.setMode('error')
    } finally {
      agentStore.isLoading = false
      if (agentStore.mode === 'thinking') agentStore.setMode('idle')
    }
  }

  async function callLLMBrain(context: AgentContext, withScreenshot: boolean) {
    let screenshotDataUrl: string | null = null
    if (withScreenshot) {
      try {
        const { captureViewport } = await import('../../utils/agent/screenshotCapture')
        screenshotDataUrl = await captureViewport()
      } catch {
        // fallback: no screenshot
      }
    }

    // 构建 messages 列表
    const systemMsg = {
      role: 'system',
      content: buildSystemPrompt(context),
    }

    const historyMsgs = context.history
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-10)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))

    // 末尾用户消息（含可选截图）
    let userContent: unknown = context.userMessage
    if (screenshotDataUrl) {
      userContent = [
        { type: 'text', text: context.userMessage },
        { type: 'image_url', image_url: { url: screenshotDataUrl, detail: 'low' } },
      ]
    }
    const userApiMsg = { role: 'user', content: userContent }

    const messages = [systemMsg, ...historyMsgs, userApiMsg]

    let response: LLMResponse
    try {
      response = (await (api as any).agentButlerChat({
        messages,
        conversation_id: agentStore.currentConversationId,
        page_context: context.pageSummary,
      })) as LLMResponse
    } catch {
      // 降级：关键词匹配兜底
      const fallbackSkill = skillRegistry.matchByIntent(context)
      if (fallbackSkill) {
        const result = await fallbackSkill.execute(context)
        agentStore.updateLastMessage({ content: result.assistantReply || result.message, isLoading: false })
      } else {
        agentStore.updateLastMessage({
          content: '我暂时无法连接到 AI 大脑，请稍后再试。您也可以直接告诉我要去哪个页面。',
          isLoading: false,
        })
      }
      return
    }

    if (response.conversation_id) {
      agentStore.currentConversationId = response.conversation_id
    }

    // 处理 tool_calls
    if (response.tool_calls?.length) {
      await handleToolCalls(response.tool_calls, context)
    } else {
      agentStore.updateLastMessage({ content: response.text || '好的。', isLoading: false })
    }
  }

  async function handleToolCalls(toolCalls: LLMToolCall[], _context: AgentContext) {
    const firstTool = toolCalls[0]
    const name = firstTool.name
    const args = firstTool.args as Record<string, unknown>

    agentStore.updateLastMessage({ content: `正在执行：${name}…`, isLoading: true })
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
        result = await executor.enhanceCurrentPage(
          args as Parameters<typeof executor.enhanceCurrentPage>[0],
        )
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
          result = await skill.execute(ctx, args)
        } else {
          result = { success: false, message: `未知工具：${name}` }
        }
      }
    }

    agentStore.updateLastMessage({
      content: result.assistantReply || result.message,
      isLoading: false,
    })
    agentStore.setMode('idle')
  }

  function buildSystemPrompt(context: AgentContext): string {
    const routeName = route.name ? String(route.name) : ''
    const pageGuide = getMarketPageKnowledge(routeName)
    const guideBlock = pageGuide
      ? `\n当前页面说明（${pageGuide.title}）：\n${pageGuide.summary}\n要点：${pageGuide.highlights.join('；')}\n`
      : ''

    return `你是"XC AGI 数字管家"——这个平台的专属 AI 助手，不是用户购买的 AI 员工。
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
