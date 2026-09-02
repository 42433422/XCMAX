<template>
  <div v-if="open" class="vp-mask" role="dialog" aria-modal="true" aria-labelledby="vp-title" @click.self="$emit('close')">
    <div class="vp-card">
      <header class="vp-head">
        <h2 id="vp-title" class="vp-title">语音电话</h2>
        <button type="button" class="vp-x" aria-label="关闭" @click="$emit('close')">×</button>
      </header>

      <p class="vp-state" :class="`vp-state--${state}`" aria-live="polite">{{ stateLabel }}</p>

      <div class="vp-orb-wrap">
        <button
          type="button"
          class="vp-orb"
          :class="`vp-orb--${state}`"
          :aria-label="state === 'idle' ? '开始通话' : '挂断'"
          @click="onOrbClick"
        >
          <span class="vp-orb__core" aria-hidden="true" />
          <span class="vp-orb__ring" aria-hidden="true" />
        </button>
      </div>

      <div class="vp-transcript" aria-live="polite">
        <article
          v-for="(m, i) in messages"
          :key="`vp-${i}`"
          class="vp-msg"
          :class="m.role === 'user' ? 'vp-msg--user' : 'vp-msg--assistant'"
        >
          <span class="vp-msg__role">{{ m.role === 'user' ? '你' : 'AI' }}</span>
          <p class="vp-msg__body">{{ m.content }}</p>
        </article>
        <p v-if="!messages.length" class="vp-empty">点中间圆球开始说话；说完停顿 1 秒会自动发送，AI 回完会朗读出来。</p>
      </div>

      <div class="vp-foot">
        <label class="vp-voice-pick">
          <span>音色</span>
          <select v-model="voiceName" class="vp-select">
            <option value="">默认</option>
            <option v-for="v in voiceList" :key="v.name" :value="v.name">{{ v.label }}</option>
          </select>
        </label>
        <label class="vp-voice-pick">
          <span>语速 {{ rate.toFixed(1) }}x</span>
          <input v-model.number="rate" type="range" min="0.6" max="1.6" step="0.1" />
        </label>
        <button type="button" class="vp-btn vp-btn--ghost" @click="onClear">清空记录</button>
        <button type="button" class="vp-btn vp-btn--ghost" @click="onMute">{{ muted ? '取消静音' : '静音 AI' }}</button>
      </div>

      <p v-if="error" class="vp-error" role="alert">{{ error }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useStreamingTts, ttsConfigFromPersonalSettings } from '../../composables/useStreamingTts'
import { loadPersonalSettings } from '../../utils/personalSettings'

export interface VoiceMessage {
  role: 'user' | 'assistant'
  content: string
}

const props = defineProps<{
  open: boolean
  /** 由父组件实现：把用户语音文本送去模型并返回回复（可异步）。 */
  onTurn: (userText: string, history: VoiceMessage[]) => Promise<string>
}>()

const _emit = defineEmits<{
  (e: 'close'): void
}>()

type State = 'idle' | 'listening' | 'thinking' | 'speaking'
const state = ref<State>('idle')
const error = ref('')
const messages = ref<VoiceMessage[]>([])
const muted = ref(false)
const rate = ref(1.0)
const voiceName = ref('')
const voiceList = ref<Array<{ name: string; label: string }>>([])

interface SpeechRecognitionResultLike {
  0?: { transcript?: string }
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<SpeechRecognitionResultLike>
}

interface SpeechRecognitionLike {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: { error?: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike
type SpeechWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

let rec: SpeechRecognitionLike | null = null
let synth: SpeechSynthesis | null = null
let interim = ''

const streamingTts = useStreamingTts(() => {
  const ps = loadPersonalSettings()
  return {
    ...ttsConfigFromPersonalSettings(ps),
    rate: rate.value,
    browserVoiceName: voiceName.value || ps.ttsVoiceName,
  }
})

const stateLabel = computed(() => {
  if (state.value === 'listening') return '我在听…说完停顿即可'
  if (state.value === 'thinking') return '思考中…'
  if (state.value === 'speaking') return 'AI 正在朗读，再点一下中断'
  return '点击圆球开始通话'
})

function loadVoices() {
  if (!synth) return
  const all = synth.getVoices()
  const zh = all.filter((v) => /^zh|cmn|yue/i.test(v.lang)).map((v) => ({ name: v.name, label: `${v.name} (${v.lang})` }))
  const en = all.filter((v) => /^en/i.test(v.lang)).slice(0, 4).map((v) => ({ name: v.name, label: `${v.name} (${v.lang})` }))
  voiceList.value = [...zh, ...en]
}

function _pickVoice(): SpeechSynthesisVoice | null {
  if (!synth) return null
  const all = synth.getVoices()
  if (voiceName.value) {
    const m = all.find((v) => v.name === voiceName.value)
    if (m) return m
  }
  return all.find((v) => /^zh/i.test(v.lang)) || all[0] || null
}

function speak(text: string): Promise<void> {
  if (muted.value || !text) return Promise.resolve()
  state.value = 'speaking'
  return streamingTts.speak(text).finally(() => {
    if (state.value === 'speaking') state.value = 'idle'
  })
}

function createRecognition(): SpeechRecognitionLike | null {
  const w = window as SpeechWindow
  const Ctor = w?.SpeechRecognition || w?.webkitSpeechRecognition
  if (!Ctor) return null
  const r = new Ctor()
  r.lang = 'zh-CN'
  r.interimResults = true
  r.continuous = false
  return r
}

function startListening() {
  error.value = ''
  if (!rec) {
    rec = createRecognition()
    if (!rec) {
      error.value = '当前浏览器不支持语音识别（建议 Chrome / Edge）。'
      state.value = 'idle'
      return
    }
  }
  interim = ''
  state.value = 'listening'
  rec.onresult = (e: SpeechRecognitionEventLike) => {
    let txt = ''
    for (let i = e.resultIndex; i < e.results.length; i += 1) {
      txt += e.results[i][0]?.transcript || ''
    }
    interim = txt.trim()
  }
  rec.onerror = (e: { error?: string }) => {
    error.value = e?.error ? `语音识别失败：${e.error}` : '语音识别失败'
    state.value = 'idle'
  }
  rec.onend = () => {
    if (interim) {
      void onUserSaid(interim)
    } else if (state.value === 'listening') {
      state.value = 'idle'
    }
  }
  try {
    rec.start()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
    state.value = 'idle'
  }
}

function stopAll() {
  try { rec?.stop?.() } catch { /* ignore */ }
  streamingTts.stop()
}

async function onUserSaid(text: string) {
  if (!text) {
    state.value = 'idle'
    return
  }
  const trimmed = text.trim()
  if (!trimmed) {
    state.value = 'idle'
    return
  }
  messages.value = [...messages.value, { role: 'user', content: trimmed }]
  state.value = 'thinking'
  let reply = ''
  try {
    reply = (await props.onTurn(trimmed, messages.value.slice())) || ''
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
    state.value = 'idle'
    return
  }
  reply = reply.trim() || '（AI 没有给出回复）'
  messages.value = [...messages.value, { role: 'assistant', content: reply }]
  await speak(reply)
  state.value = 'idle'
}

function onOrbClick() {
  if (state.value === 'idle') {
    startListening()
    return
  }
  if (state.value === 'speaking') {
    streamingTts.stop()
    state.value = 'idle'
    return
  }
  if (state.value === 'listening') {
    try { rec?.stop?.() } catch { /* ignore */ }
    return
  }
}

function onClear() {
  messages.value = []
}

function onMute() {
  muted.value = !muted.value
  if (muted.value) {
    streamingTts.stop()
    if (state.value === 'speaking') state.value = 'idle'
  }
}

onMounted(() => {
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    synth = window.speechSynthesis
    loadVoices()
    if (synth) synth.onvoiceschanged = loadVoices
  } else {
    error.value = '当前浏览器不支持语音合成。'
  }
})

onBeforeUnmount(() => {
  stopAll()
})

watch(
  () => props.open,
  (v) => {
    if (!v) {
      stopAll()
      state.value = 'idle'
    }
  },
)
</script>

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./VoicePhoneModal.css，模板与逻辑保持原样。 -->
<style scoped src="./VoicePhoneModal.css"></style>
