import { useRouter } from 'vue-router'
import { usePrivacyManager } from './usePrivacyManager'
import { useAgentStore } from '../../stores/agent'
import { useAuthStore } from '../../stores/auth'
import { useButlerOrchestrator } from './useButlerOrchestrator'
import { ACTION_RISKS, ROUTE_NAME_MAP } from '../../utils/agent/agentActionTypes'
import { serializeVisibleDom } from '../../utils/agent/pageSerializer'
import type { SkillResult } from '../../types/agent'
import { checkXiaoCLifeAction } from './xiaocLifeActionGuard'

const ACTION_LOG_KEY = 'xc_butler_action_log'
const MAX_LOG_ENTRIES = 50

interface ActionLogEntry {
  ts: number
  action: string
  label: string
  risk: string
  success: boolean
  detail?: string
}

function appendLog(entry: ActionLogEntry) {
  try {
    const raw = sessionStorage.getItem(ACTION_LOG_KEY)
    const arr: ActionLogEntry[] = raw ? JSON.parse(raw) : []
    arr.push(entry)
    if (arr.length > MAX_LOG_ENTRIES) arr.splice(0, arr.length - MAX_LOG_ENTRIES)
    sessionStorage.setItem(ACTION_LOG_KEY, JSON.stringify(arr))
  } catch {
    // ignore
  }
}

export function getActionLog(): ActionLogEntry[] {
  try {
    const raw = sessionStorage.getItem(ACTION_LOG_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

export function useActionExecutor() {
  const router = useRouter()
  const { requestAction } = usePrivacyManager()
  const agentStore = useAgentStore()
  const auth = useAuthStore()

  function captureScope() {
    const generation = agentStore.conversationGeneration
    const owner = auth.user?.id
    return () => generation === agentStore.conversationGeneration && owner === auth.user?.id
  }

  const staleResult = (): SkillResult => ({
    success: false,
    message: '原会话已停止或变化，操作结果需在原账号核对。',
  })

  /** 导航到指定路由（低风险） */
  async function navigate(args: { route?: string; name?: string; query?: Record<string, string> }): Promise<SkillResult> {
    const isCurrent = captureScope()
    const blocked = await checkXiaoCLifeAction(2, isCurrent)
    if (!isCurrent()) return staleResult()
    if (blocked) return blocked
    const label = `跳转到 ${args.route || args.name}`
    agentStore.setMode('operating')
    try {
      const routeName = args.name || ROUTE_NAME_MAP[args.route || ''] || args.route || ''
      await router.push({ name: routeName, query: args.query })
      if (!isCurrent()) return staleResult()
      appendLog({ ts: Date.now(), action: 'navigate', label, risk: 'low', success: true })
      return {
        success: true,
        message: `已跳转到 ${routeName}`,
        assistantReply: `好的，已为您跳转。`,
      }
    } catch (e: unknown) {
      if (!isCurrent()) return staleResult()
      const msg = e instanceof Error ? e.message : String(e)
      appendLog({
        ts: Date.now(),
        action: 'navigate',
        label,
        risk: 'low',
        success: false,
        detail: msg,
      })
      return { success: false, message: msg }
    } finally {
      if (isCurrent()) agentStore.setMode('idle')
    }
  }

  /** 点击页面元素（中风险） */
  async function click(args: { selector?: string; butlerTarget?: string; label?: string }): Promise<SkillResult> {
    const isCurrent = captureScope()
    const label = args.label || args.butlerTarget || args.selector || '点击操作'
    const ok = await requestAction('click', ACTION_RISKS.click, label, args)
    if (!isCurrent()) return staleResult()
    if (!ok) return { success: false, message: '用户已取消' }

    const blocked = await checkXiaoCLifeAction(2, isCurrent)
    if (!isCurrent()) return staleResult()
    if (blocked) return blocked

    agentStore.setMode('operating')
    try {
      const el = findElement(args)
      if (!el) return { success: false, message: `未找到目标元素：${label}` }
      if (el.closest('[data-xiaoc-control-plane]')) return { success: false, message: '小 C 的自主等级与预算只能由管理员直接设置。' }
      ;(el as HTMLElement).click()
      if (!isCurrent()) return staleResult()
      appendLog({ ts: Date.now(), action: 'click', label, risk: 'medium', success: true })
      return { success: true, message: `已点击：${label}` }
    } catch (e: unknown) {
      if (!isCurrent()) return staleResult()
      const msg = e instanceof Error ? e.message : String(e)
      appendLog({
        ts: Date.now(),
        action: 'click',
        label,
        risk: 'medium',
        success: false,
        detail: msg,
      })
      return { success: false, message: msg }
    } finally {
      if (isCurrent()) agentStore.setMode('idle')
    }
  }

  /** 填写表单输入（中风险） */
  async function fill(args: { selector?: string; butlerTarget?: string; label?: string; value: string }): Promise<SkillResult> {
    const isCurrent = captureScope()
    const label = `填写 ${args.label || args.butlerTarget || '输入框'}：${args.value}`
    const ok = await requestAction('fill', ACTION_RISKS.fill, label, args)
    if (!isCurrent()) return staleResult()
    if (!ok) return { success: false, message: '用户已取消' }

    const blocked = await checkXiaoCLifeAction(2, isCurrent)
    if (!isCurrent()) return staleResult()
    if (blocked) return blocked

    agentStore.setMode('operating')
    try {
      const el = findElement(args) as HTMLInputElement | HTMLTextAreaElement | null
      if (!el) return { success: false, message: `未找到输入框：${args.label}` }
      if (el.closest('[data-xiaoc-control-plane]')) return { success: false, message: '小 C 的自主等级与预算只能由管理员直接设置。' }
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set
      if (nativeInputValueSetter) {
        nativeInputValueSetter.call(el, args.value)
        el.dispatchEvent(new Event('input', { bubbles: true }))
        if (!isCurrent()) return staleResult()
        el.dispatchEvent(new Event('change', { bubbles: true }))
      } else {
        el.value = args.value
      }
      if (!isCurrent()) return staleResult()
      appendLog({ ts: Date.now(), action: 'fill', label, risk: 'medium', success: true })
      return { success: true, message: `已填写：${label}` }
    } catch (e: unknown) {
      if (!isCurrent()) return staleResult()
      const msg = e instanceof Error ? e.message : String(e)
      appendLog({
        ts: Date.now(),
        action: 'fill',
        label,
        risk: 'medium',
        success: false,
        detail: msg,
      })
      return { success: false, message: msg }
    } finally {
      if (isCurrent()) agentStore.setMode('idle')
    }
  }

  /** 选择下拉/单选（中风险） */
  async function select(args: { selector?: string; butlerTarget?: string; label?: string; value: string }): Promise<SkillResult> {
    const isCurrent = captureScope()
    const label = `选择 ${args.label || '选项'}：${args.value}`
    const ok = await requestAction('select', ACTION_RISKS.select, label, args)
    if (!isCurrent()) return staleResult()
    if (!ok) return { success: false, message: '用户已取消' }

    const blocked = await checkXiaoCLifeAction(2, isCurrent)
    if (!isCurrent()) return staleResult()
    if (blocked) return blocked

    agentStore.setMode('operating')
    try {
      const el = findElement(args) as HTMLSelectElement | null
      if (!el) return { success: false, message: `未找到选择框：${args.label}` }
      if (el.closest('[data-xiaoc-control-plane]')) return { success: false, message: '小 C 的自主等级与预算只能由管理员直接设置。' }
      el.value = args.value
      el.dispatchEvent(new Event('change', { bubbles: true }))
      if (!isCurrent()) return staleResult()
      appendLog({ ts: Date.now(), action: 'select', label, risk: 'medium', success: true })
      return { success: true, message: `已选择：${label}` }
    } catch (e: unknown) {
      if (!isCurrent()) return staleResult()
      const msg = e instanceof Error ? e.message : String(e)
      appendLog({
        ts: Date.now(),
        action: 'select',
        label,
        risk: 'medium',
        success: false,
        detail: msg,
      })
      return { success: false, message: msg }
    } finally {
      if (isCurrent()) agentStore.setMode('idle')
    }
  }

  /** 滚动页面（低风险） */
  async function scroll(args: { direction: 'up' | 'down' | 'top' | 'bottom'; px?: number }): Promise<SkillResult> {
    const isCurrent = captureScope()
    const blocked = await checkXiaoCLifeAction(2, isCurrent)
    if (!isCurrent()) return staleResult()
    if (blocked) return blocked
    const px = args.px || 300
    switch (args.direction) {
      case 'top':
        window.scrollTo({ top: 0, behavior: 'smooth' })
        break
      case 'bottom':
        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
        break
      case 'up':
        window.scrollBy({ top: -px, behavior: 'smooth' })
        break
      case 'down':
        window.scrollBy({ top: px, behavior: 'smooth' })
        break
    }
    return { success: true, message: `已滚动：${args.direction}` }
  }

  /** 读取页面内容（低风险） */
  async function read(): Promise<SkillResult> {
    const isCurrent = captureScope()
    const blocked = await checkXiaoCLifeAction(2, isCurrent)
    if (!isCurrent()) return staleResult()
    if (blocked) return blocked
    const content = serializeVisibleDom()
    return {
      success: true,
      message: content,
      assistantReply: `当前页面内容摘要：\n${content.slice(0, 500)}`,
    }
  }

  /**
   * vibe-coding 改写当前页面对象（高风险）。
   * 先弹高风险确认，用户同意后启动编排管线。
   */
  async function enhanceCurrentPage(args: { brief: string; scope?: string }): Promise<SkillResult> {
    const isCurrent = captureScope()
    const orchestrator = useButlerOrchestrator()
    const tgt = orchestrator.detectTarget()
    const targetLabel = tgt ? `${tgt.type} ${tgt.id}` : '当前页面'
    const label = `用 vibe-coding 改写 ${targetLabel}：${args.brief}`

    // High-risk confirmation via existing privacy/confirm flow
    const ok = await requestAction('enhance_current_page', 'high', label, args as unknown as Record<string, unknown>)
    if (!isCurrent()) return staleResult()
    if (!ok) {
      return { success: false, message: '用户已取消', assistantReply: '已取消，未做任何修改。' }
    }

    const blocked = await checkXiaoCLifeAction(3, isCurrent)
    if (!isCurrent()) return staleResult()
    if (blocked) return blocked

    if (!tgt) {
      return {
        success: false,
        message: '当前页面无法直接改写',
        assistantReply: '当前页面无法直接改写，请先打开具体的 Mod / 工作流 / 员工页再试。',
      }
    }

    const result = await orchestrator.start(args.brief, args.scope)
    if (!isCurrent()) return staleResult()
    if (!result.ok) {
      return {
        success: false,
        message: result.error || '启动失败',
        assistantReply: `改写启动失败：${result.error || '未知错误'}`,
      }
    }

    return {
      success: true,
      message: '改写管线已启动',
      assistantReply: 'AI 正在为你改造，请在弹出的进度窗口中查看详情，完成后页面将自动刷新。',
    }
  }

  return { navigate, click, fill, select, scroll, read, enhanceCurrentPage }
}

/** 按 data-butler-id、aria-label、button文本查找元素 */
function findElement(args: { selector?: string; butlerTarget?: string; label?: string }): Element | null {
  if (args.selector) {
    try {
      return document.querySelector(args.selector)
    } catch {
      /* ignore */
    }
  }
  if (args.butlerTarget) {
    const el = document.querySelector(`[data-butler-id="${args.butlerTarget}"]`)
    if (el) return el
  }
  if (args.label) {
    // 尝试 aria-label
    const byAria = document.querySelector(`[aria-label="${args.label}"]`)
    if (byAria) return byAria
    // 尝试 button 文本
    const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
    const match = buttons.find((b) => b.textContent?.trim().includes(args.label!))
    if (match) return match
  }
  return null
}
