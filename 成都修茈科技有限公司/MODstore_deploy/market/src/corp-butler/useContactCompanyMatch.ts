import { ref, shallowRef } from 'vue'
import { authHeaders } from '../api/shared'
import { getBridge } from './contactIntakeBridge'

export type CompanyMatchItem = {
  name: string
  exact?: boolean
  in_crm?: boolean
  has_history?: boolean
  submission_count?: number
  source?: string
}

export type CompanyMatchPayload = {
  ok?: boolean
  found?: boolean
  matched?: CompanyMatchItem | null
  suggestions?: CompanyMatchItem[]
  web_error?: string
  web_used?: boolean
  query_incomplete?: boolean
}

function looksLikeFullCompanyLegalName(q: string): boolean {
  return /(?:有限公司|有限责任公司|股份有限公司|集团有限公司)/.test((q || '').trim())
}

function companyMatchWarnText(q: string, payload: CompanyMatchPayload | null): string {
  if (payload?.web_error) {
    return '联网检索暂不可用，将按您填写的名称继续'
  }
  if (payload?.query_incomplete || !looksLikeFullCompanyLegalName(q)) {
    return '联网检索未找到公司全称，请补全后重试或继续手动填写'
  }
  return '联网检索未匹配到该公司，将按您填写的名称继续'
}

function companyMatchContinueHint(q: string, payload: CompanyMatchPayload | null): string {
  if (payload?.web_error) {
    return '可继续填写系统类型；请稍后重试联网核对'
  }
  if (!payload?.found) {
    return '可继续填写系统类型；补全公司全称后请再次点选系统类型'
  }
  return '可继续填写系统类型'
}

const COMPANY_SOURCE_MARKERS = [
  '爱企查',
  '启信宝',
  '企查查',
  '天眼查',
  '水滴信用',
  '百度百科',
  '百度知道',
  '企查猫',
  '利查查',
]

/** 与 contact-intake.js 一致：满 2 字后提示点行业，聚焦行业字段才开始联网匹配 */
const HINT_FOCUS_INDUSTRY = '点选「行业 / 业务类型」开始匹配公司'

export type ContactCompanyMatchContext = 'contact' | 'workbench'

const MATCH_API_BY_CONTEXT: Record<ContactCompanyMatchContext, string> = {
  contact: '/api/public/contact/companies/match',
  workbench: '/api/market/workbench/companies/match',
}

export function formatCompanyDisplayName(name: string): string {
  let s = (name || '').trim()
  if (!s) return ''
  s = s.split(/\s*[-_|｜]\s*/)[0].trim()
  for (const marker of COMPANY_SOURCE_MARKERS) {
    if (s.endsWith(marker)) s = s.slice(0, -marker.length).replace(/[\s\-_|｜]+$/, '').trim()
  }
  return s.replace(/\s+/g, '').slice(0, 80)
}

export function normalizeCompanyMatchPayload(data: CompanyMatchPayload | null): CompanyMatchPayload | null {
  if (!data || typeof data !== 'object') return data
  const cleanItem = (item: CompanyMatchItem | null | undefined) => {
    if (!item?.name) return item
    return { ...item, name: formatCompanyDisplayName(item.name) }
  }
  const suggestions: CompanyMatchItem[] = []
  const seen = new Set<string>()
  for (const raw of Array.isArray(data.suggestions) ? data.suggestions : []) {
    const item = cleanItem(raw)
    const key = item?.name || ''
    if (!key || seen.has(key)) continue
    seen.add(key)
    suggestions.push(item!)
  }
  const matched = data.matched ? cleanItem(data.matched) : null
  if (matched?.name && !suggestions.some((s) => s.name === matched!.name)) {
    suggestions.unshift(matched)
  }
  return { ...data, matched: matched ?? null, suggestions }
}

export function useContactCompanyMatch(context: ContactCompanyMatchContext = 'contact') {
  const isWorkbench = context === 'workbench'
  const hint = ref('')
  const hintVariant = ref<'ok' | 'new' | ''>('')
  const resultMode = ref<'hidden' | 'ok' | 'warn'>('hidden')
  const resultText = ref('')
  const resolvedName = ref('')
  const suggestions = ref<CompanyMatchItem[]>([])
  const showSuggestions = ref(false)
  const matching = ref(false)
  /** 仅聚焦「行业 / 业务类型」后为 true，才展示状态条 / 结果框 / 下拉 */
  const matchUiUnlocked = ref(false)

  let matchSeq = 0
  let matchTimer: ReturnType<typeof setTimeout> | null = null
  let lastSyncedQuery = ''
  let matchInFlight = false
  const cache = shallowRef<CompanyMatchPayload | null>(null)

  function resetUi() {
    hint.value = ''
    hintVariant.value = ''
    resultMode.value = 'hidden'
    resultText.value = ''
    suggestions.value = []
    showSuggestions.value = false
    resolvedName.value = ''
    cache.value = null
    lastSyncedQuery = ''
    matchUiUnlocked.value = false
  }

  function clearMatchList() {
    resultMode.value = 'hidden'
    suggestions.value = []
    showSuggestions.value = false
  }

  function workbenchMatchedHint(payload: CompanyMatchPayload | null, matched: CompanyMatchItem) {
    if (payload?.web_used || matched.source === 'web') {
      return '已通过联网检索核对，可点「插入对话」或继续编辑'
    }
    return '已匹配历史记录，可插入对话'
  }

  function workbenchContinueHint(q: string, payload: CompanyMatchPayload | null) {
    if (payload?.web_error) return '可手动继续输入公司名并插入对话'
    if (!payload?.found) return '补全公司全称后重试，或仍可使用当前输入插入对话'
    return '请从下方选择公司全称'
  }

  function applyUiFromPayload(data: CompanyMatchPayload | null, query: string) {
    const q = query.trim()
    if (q.length < 2) {
      resetUi()
      return
    }

    const payload = data ? normalizeCompanyMatchPayload(data) : null
    cache.value = payload
    const matched = payload?.matched
    const list = Array.isArray(payload?.suggestions) ? payload.suggestions : []
    const multiPick = list.length > 1

    if (matched?.name && !multiPick) {
      resolvedName.value = matched.name
      resultMode.value = 'hidden'
      resultText.value = ''
      hint.value = isWorkbench
        ? workbenchMatchedHint(payload, matched)
        : payload?.web_used || matched.source === 'web'
          ? '已通过百度/企查查类检索核对，请继续填写系统类型'
          : '已匹配，请继续填写系统类型'
      hintVariant.value = 'ok'
      showSuggestions.value = false
      suggestions.value = []
      if (!isWorkbench) void syncBridgeCompany(q, matched)
      return
    }

    if (matched?.name && multiPick) {
      resolvedName.value = ''
      resultMode.value = 'hidden'
      hint.value = isWorkbench
        ? '请从下方选择公司全称'
        : '请从下方选择公司全称（搜索词仍保留在输入框）'
      hintVariant.value = ''
      suggestions.value = list
      showSuggestions.value = list.length > 0
      return
    }

    if (payload && !payload.found) {
      resolvedName.value = ''
      resultMode.value = 'warn'
      resultText.value = companyMatchWarnText(q, payload)
      hint.value = isWorkbench ? workbenchContinueHint(q, payload) : companyMatchContinueHint(q, payload)
      hintVariant.value = 'new'
      suggestions.value = list
      showSuggestions.value = list.length > 0
      return
    }

    resolvedName.value = ''
    resultMode.value = 'hidden'
    hint.value = list.length ? '请选择下方匹配的公司名称' : ''
    hintVariant.value = ''
    suggestions.value = list
    showSuggestions.value = list.length > 0
  }

  async function syncBridgeCompany(typed: string, matched?: CompanyMatchItem) {
    const hidden = document.getElementById('intake-ai-company') as HTMLInputElement | null
    if (hidden) hidden.value = typed
    const bridge = getBridge()
    if (bridge?.selectAiCompany && matched?.name) {
      bridge.selectAiCompany(matched)
    }
  }

  async function runMatch(query: string) {
    const q = query.trim()
    if (q.length < 2) {
      resetUi()
      return
    }
    const seq = ++matchSeq
    matchInFlight = true
    matching.value = true
    clearMatchList()
    hint.value = `正在用「${q}」匹配公司名称…`
    hintVariant.value = ''

    try {
      const api = MATCH_API_BY_CONTEXT[context]
      const headers: Record<string, string> = { ...(authHeaders() || {}) }
      const res = await fetch(`${api}?q=${encodeURIComponent(q)}&limit=8&web=true`, {
        credentials: 'same-origin',
        headers: Object.keys(headers).length ? headers : undefined,
      })
      if (seq !== matchSeq) return
      if (!res.ok) {
        if (res.status === 429) {
          resultMode.value = 'warn'
          resultText.value = '匹配请求过于频繁'
          hint.value = '请等待约 1 分钟后再试，或继续手动填写'
          hintVariant.value = 'new'
          return
        }
        resultMode.value = 'warn'
        resultText.value = '匹配服务暂时不可用'
        hint.value =
          res.status === 404
            ? '当前页面未连上官网 API，请用 xiu-ci.com 打开联系页'
            : '请稍后重试或继续手动填写'
        hintVariant.value = 'new'
        return
      }
      const data = normalizeCompanyMatchPayload((await res.json()) as CompanyMatchPayload)
      if (seq !== matchSeq) return
      lastSyncedQuery = q
      applyUiFromPayload(data, q)
    } catch {
      if (seq !== matchSeq) return
      resultMode.value = 'warn'
      resultText.value = '无法连接匹配服务'
      hint.value =
        typeof location !== 'undefined' && location.protocol === 'file:'
          ? '本地预览无法匹配，请通过官网访问'
          : '网络异常，请稍后重试'
      hintVariant.value = 'new'
    } finally {
      if (seq === matchSeq) {
        matchInFlight = false
        matching.value = false
      }
    }
  }

  function scheduleCompanyMatch(getCompany: () => string) {
    if (matchTimer) clearTimeout(matchTimer)
    matchTimer = setTimeout(() => {
      matchTimer = null
      const q = getCompany().trim()
      if (q.length < 2) return
      if (q === lastSyncedQuery && cache.value) {
        applyUiFromPayload(cache.value, q)
        return
      }
      if (matchInFlight) return
      void runMatch(q)
    }, 400)
  }

  /** 防抖结束后读取输入框最新全文，避免只搜到先输入的「成都」 */
  function tryStartCompanyMatch(getCompany: () => string) {
    if (getCompany().trim().length < 2) return
    scheduleCompanyMatch(getCompany)
  }

  /** 对齐 contact-intake.js 公司输入 */
  function onCompanyInput(value: string, getCompany: () => string) {
    const q = value.trim()
    const hidden = document.getElementById('intake-ai-company') as HTMLInputElement | null
    if (hidden) hidden.value = value

    if (q !== lastSyncedQuery) {
      if (matchTimer) clearTimeout(matchTimer)
      matchTimer = null
      cache.value = null
      lastSyncedQuery = ''
      resolvedName.value = ''
      clearMatchList()
    }

    if (!matchUiUnlocked.value) {
      if (isWorkbench) {
        matchUiUnlocked.value = true
        if (q.length >= 2) {
          tryStartCompanyMatch(getCompany)
          return
        }
      } else {
        hint.value = q.length >= 2 ? HINT_FOCUS_INDUSTRY : ''
        hintVariant.value = ''
        return
      }
    }
    if (q.length >= 2 && q !== lastSyncedQuery) {
      tryStartCompanyMatch(getCompany)
      return
    }
    if (q.length >= 2) {
      hint.value = HINT_FOCUS_INDUSTRY
      hintVariant.value = ''
    } else {
      hint.value = ''
      hintVariant.value = ''
    }
  }

  function unlockMatchUi() {
    matchUiUnlocked.value = true
  }

  function onIndustryFocus(getCompany: () => string) {
    matchUiUnlocked.value = true
    tryStartCompanyMatch(getCompany)
  }

  function onIndustryInput() {
    // 对齐 systemEl input → showAiAssistHint('')
  }

  async function selectSuggestion(item: CompanyMatchItem, typedQuery: string) {
    const picked = formatCompanyDisplayName(item?.name)
    if (!picked) return
    resolvedName.value = picked
    resultMode.value = 'hidden'
    resultText.value = ''
    hint.value = isWorkbench ? '已选定公司，可插入对话' : '已选定公司，请继续填写系统类型'
    hintVariant.value = 'ok'
    showSuggestions.value = false
    suggestions.value = []
    lastSyncedQuery = typedQuery.trim()

    if (!isWorkbench) {
      const hidden = document.getElementById('intake-ai-company') as HTMLInputElement | null
      if (hidden) hidden.value = typedQuery.trim()
      const bridge = getBridge()
      if (bridge?.selectAiCompany) {
        bridge.selectAiCompany({ ...item, name: picked, exact: true })
      }
    }
  }

  function getCompanyForSubmit(typed: string) {
    return (resolvedName.value || typed).trim()
  }

  return {
    hint,
    hintVariant,
    resultMode,
    resultText,
    suggestions,
    showSuggestions,
    matching,
    matchUiUnlocked,
    resolvedName,
    resetUi,
    unlockMatchUi,
    onCompanyInput,
    onIndustryFocus,
    onIndustryInput,
    selectSuggestion,
    getCompanyForSubmit,
  }
}
