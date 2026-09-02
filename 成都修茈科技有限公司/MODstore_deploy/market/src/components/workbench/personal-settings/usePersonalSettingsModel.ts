/**
 * 个性化设置 · 表单模型与同步逻辑（由 PersonalSettings.vue 原单文件机械迁出，行为不变）。
 */
import { reactive, ref, watch } from 'vue'
import { defaultPersonalSettings, type PersonalSettings } from '../../../utils/personalSettings'

export interface PersonalSettingsProps {
  open: boolean
  modelValue: PersonalSettings
}

export type PersonalSettingsEmit = {
  (e: 'close'): void
  (e: 'update:modelValue', v: PersonalSettings): void
}

const themes = [
  { id: 'dark', label: '深色', icon: '🌙' },
  { id: 'light', label: '浅色', icon: '☀️' },
  { id: 'auto', label: '跟随系统', icon: '🖥️' },
]

const edgeVoices = [
  { id: 'zh-CN-XiaoxiaoNeural', label: '晓晓（女声，通用）' },
  { id: 'zh-CN-YunxiNeural', label: '云希（男声）' },
  { id: 'zh-CN-XiaoyiNeural', label: '晓伊（女声）' },
  { id: 'zh-CN-YunjianNeural', label: '云健（男声，资讯风）' },
  { id: 'zh-CN-XiaochenNeural', label: '晓辰（女声）' },
  { id: 'zh-CN-XiaomengNeural', label: '晓梦（女声）' },
]

export function usePersonalSettingsModel(props: PersonalSettingsProps, emit: PersonalSettingsEmit) {
  const model = reactive<PersonalSettings>({ ...defaultPersonalSettings() })
  const suggestionsRaw = ref('')
  const expandedSections = ref<Set<string>>(new Set(['theme']))

  function toggleSection(key: string) {
    const s = new Set(expandedSections.value)
    if (s.has(key)) s.delete(key)
    else s.add(key)
    expandedSections.value = s
  }

  function syncFromProps() {
    const v = props.modelValue || ({} as PersonalSettings)
    const def = defaultPersonalSettings()
    model.theme = (v.theme || 'light') as 'dark' | 'light' | 'auto'
    model.fontPx = Number.isFinite(Number(v.fontPx)) ? Number(v.fontPx) : 15
    model.memory = String(v.memory || '').slice(0, 600)
    model.suggestions = Array.isArray(v.suggestions) ? v.suggestions.slice(0, 6) : []
    model.ttsEngine =
      v.ttsEngine === 'edge-online' ? 'edge-online' : v.ttsEngine === 'auto' || v.ttsEngine === 'browser' ? 'auto' : def.ttsEngine
    model.ttsEdgeVoice =
      typeof v.ttsEdgeVoice === 'string' && v.ttsEdgeVoice.trim()
        ? v.ttsEdgeVoice.trim().slice(0, 120)
        : def.ttsEdgeVoice
    model.ttsVoiceName = typeof v.ttsVoiceName === 'string' ? v.ttsVoiceName.slice(0, 256) : def.ttsVoiceName
    const rr = Number(v.ttsRate)
    model.ttsRate = Number.isFinite(rr) ? Math.max(0.6, Math.min(1.6, rr)) : def.ttsRate
    model.voiceSpeechMode =
      v.voiceSpeechMode === 'cascade' || v.voiceSpeechMode === 's2s' || v.voiceSpeechMode === 'unified'
        ? v.voiceSpeechMode
        : def.voiceSpeechMode
    suggestionsRaw.value = model.suggestions.join('\n')
  }

  watch(
    () => props.modelValue,
    () => syncFromProps(),
    { immediate: true, deep: true },
  )

  function onSuggestionsBlur() {
    const lines = String(suggestionsRaw.value || '')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 6)
    model.suggestions = lines
    suggestionsRaw.value = lines.join('\n')
    emitChange()
  }

  function emitChange() {
    const ttsRate = Math.max(0.6, Math.min(1.6, Number(model.ttsRate) || 1))
    model.ttsRate = ttsRate
    const ttsEngine = model.ttsEngine === 'edge-online' ? 'edge-online' : 'auto'
    const allowedEdge = new Set(edgeVoices.map((e) => e.id))
    const ttsEdgeVoice = allowedEdge.has(model.ttsEdgeVoice) ? model.ttsEdgeVoice : defaultPersonalSettings().ttsEdgeVoice
    const voiceSpeechMode =
      model.voiceSpeechMode === 'cascade' ||
      model.voiceSpeechMode === 's2s' ||
      model.voiceSpeechMode === 'unified'
        ? model.voiceSpeechMode
        : defaultPersonalSettings().voiceSpeechMode
    emit('update:modelValue', {
      ...model,
      ttsEngine,
      ttsEdgeVoice,
      memory: model.memory.slice(0, 600),
      ttsVoiceName: String(model.ttsVoiceName || '').slice(0, 256),
      ttsRate,
      voiceSpeechMode,
    })
  }

  function resetMemory() {
    model.memory = ''
    emitChange()
  }

  function onSave() {
    emitChange()
    emit('close')
  }

  return {
    themes,
    edgeVoices,
    model,
    suggestionsRaw,
    expandedSections,
    toggleSection,
    onSuggestionsBlur,
    emitChange,
    resetMemory,
    onSave,
  }
}
