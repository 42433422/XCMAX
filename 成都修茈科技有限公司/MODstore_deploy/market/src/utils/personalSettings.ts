/**
 * 个性化设置（主题 / 字号 / 长期记忆 / 推荐 prompt / 朗读 TTS）持久化与默认值。
 */

export interface PersonalSettings {
  theme: 'dark' | 'light' | 'auto'
  fontPx: number
  memory: string
  suggestions: string[]
  /** 朗读引擎：`edge-online` 为微软在线神经音（经服务端 edge-tts）；`browser` 为本机合成 */
  ttsEngine: 'edge-online' | 'browser'
  /** Edge 神经语音 ID，如 zh-CN-XiaoxiaoNeural */
  ttsEdgeVoice: string
  /** 浏览器朗读音色：`SpeechSynthesisVoice.name`，空字符串表示自动（优先中文） */
  ttsVoiceName: string
  /** 朗读语速：浏览器为 utterance.rate；云端为相对倍率映射到 Edge rate% */
  ttsRate: number
  /**
   * 语音对话管线：`cascade` = ASR→LLM→客户端 TTS；`s2s` = 单 WebSocket（LLM+服务端 TTS 编排，更接近豆包）
   */
  voiceSpeechMode: 'cascade' | 's2s' | 'unified'
}

const KEY = 'workbench_personal_settings_v1'

const DEFAULT_SUGGESTIONS = [
  '帮我把今天的工作拆成步骤',
  '帮我分析一个自动化流程',
  '帮我写一段客户沟通话术',
]

export function defaultPersonalSettings(): PersonalSettings {
  return {
    theme: 'dark',
    fontPx: 15,
    memory: '',
    suggestions: DEFAULT_SUGGESTIONS.slice(),
    ttsEngine: 'edge-online',
    ttsEdgeVoice: 'zh-CN-XiaoxiaoNeural',
    ttsVoiceName: '',
    ttsRate: 1,
    /** 单 WebSocket：流式 ASR + LLM + TTS，更接近豆包式「打电话」 */
    voiceSpeechMode: 'unified',
  }
}

export function loadPersonalSettings(): PersonalSettings {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return defaultPersonalSettings()
    const obj = JSON.parse(raw) || {}
    const def = defaultPersonalSettings()
    const rawTtsRate = Number(obj.ttsRate)
    const ttsRate = Number.isFinite(rawTtsRate) ? Math.max(0.6, Math.min(1.6, rawTtsRate)) : def.ttsRate
    const ttsVoiceName = typeof obj.ttsVoiceName === 'string' ? obj.ttsVoiceName.slice(0, 256) : def.ttsVoiceName
    const ttsEngine =
      obj.ttsEngine === 'browser' || obj.ttsEngine === 'edge-online' ? obj.ttsEngine : def.ttsEngine
    const ttsEdgeVoice =
      typeof obj.ttsEdgeVoice === 'string' && obj.ttsEdgeVoice.trim()
        ? obj.ttsEdgeVoice.trim().slice(0, 120)
        : def.ttsEdgeVoice
    let voiceSpeechMode =
      obj.voiceSpeechMode === 'cascade' ||
      obj.voiceSpeechMode === 's2s' ||
      obj.voiceSpeechMode === 'unified'
        ? obj.voiceSpeechMode
        : def.voiceSpeechMode
    // 旧默认 s2s：升级到 unified（单连接流式 ASR，电话式体验更好）
    if (obj.voiceSpeechMode === 's2s') voiceSpeechMode = 'unified'
    return {
      theme: obj.theme === 'light' || obj.theme === 'auto' ? obj.theme : 'dark',
      fontPx: Number.isFinite(Number(obj.fontPx)) ? Math.max(13, Math.min(20, Number(obj.fontPx))) : def.fontPx,
      memory: typeof obj.memory === 'string' ? obj.memory.slice(0, 600) : '',
      suggestions: Array.isArray(obj.suggestions) && obj.suggestions.length
        ? obj.suggestions.filter((x: unknown) => typeof x === 'string' && (x as string).trim()).slice(0, 6)
        : def.suggestions,
      ttsEngine,
      ttsEdgeVoice,
      ttsVoiceName,
      ttsRate,
      voiceSpeechMode,
    }
  } catch {
    return defaultPersonalSettings()
  }
}

export function savePersonalSettings(v: PersonalSettings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(v))
  } catch {
    /* ignore */
  }
}

export function resolveWorkbenchTheme(theme: 'dark' | 'light' | 'auto'): 'dark' | 'light' {
  if (theme === 'light') return 'light'
  if (theme === 'auto') {
    const prefersLight =
      typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: light)').matches
    return prefersLight ? 'light' : 'dark'
  }
  return 'dark'
}

export function applyThemeToDocument(theme: 'dark' | 'light' | 'auto'): void {
  if (typeof document === 'undefined') return
  const html = document.documentElement
  if (!html) return
  html.dataset.workbenchTheme = resolveWorkbenchTheme(theme)
}

/** 首屏前应用主题，避免侧栏导航在 CSS 变量就绪前闪紫色。 */
export function bootstrapWorkbenchThemeFromStorage(): void {
  applyThemeToDocument(loadPersonalSettings().theme)
}
