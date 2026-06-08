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

const emit = defineEmits<{
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

let rec: any = null
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

function pickVoice(): SpeechSynthesisVoice | null {
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

function createRecognition(): any {
  const w = window as any
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
  rec.onresult = (e: any) => {
    let txt = ''
    for (let i = e.resultIndex; i < e.results.length; i += 1) {
      txt += e.results[i][0]?.transcript || ''
    }
    interim = txt.trim()
  }
  rec.onerror = (e: any) => {
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
  } catch (e: any) {
    error.value = e?.message || String(e)
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
  } catch (e: any) {
    error.value = e?.message || String(e)
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

<style scoped>
.vp-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(2, 6, 23, 0.85);
  display: grid;
  place-items: center;
  padding: 1rem;
  backdrop-filter: blur(6px);
}

.vp-card {
  width: min(36rem, 100%);
  padding: 1rem 1.3rem 1.2rem;
  background: rgba(15, 23, 42, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.95rem;
  color: #e2e8f0;
}

.vp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.45rem;
}

.vp-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
}

.vp-x {
  width: 2rem;
  height: 2rem;
  border-radius: 0.45rem;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(226, 232, 240, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.08);
  cursor: pointer;
  font-size: 1.1rem;
}

.vp-state {
  text-align: center;
  margin: 0.4rem 0 0.6rem;
  font-size: 0.85rem;
  color: rgba(203, 213, 225, 0.78);
}

.vp-state--listening { color: #5eead4; }
.vp-state--thinking { color: #fbbf24; }
.vp-state--speaking { color: #c7d2fe; }

.vp-orb-wrap {
  position: relative;
  display: grid;
  place-items: center;
  margin: 0.4rem auto 1rem;
  width: 12rem;
  aspect-ratio: 1;
}

.vp-orb {
  position: relative;
  width: 70%;
  aspect-ratio: 1;
  border: none;
  border-radius: 999px;
  background:
    radial-gradient(circle at 35% 28%, rgba(255, 255, 255, 0.85), transparent 12%),
    radial-gradient(circle, rgba(125, 211, 252, 0.85), rgba(59, 130, 246, 0.32) 45%, rgba(15, 23, 42, 0.05) 70%);
  cursor: pointer;
  box-shadow:
    0 0 36px rgba(56, 189, 248, 0.32),
    0 0 90px rgba(99, 102, 241, 0.2);
  animation: vpBreath 3s ease-in-out infinite;
}

.vp-orb__ring {
  position: absolute;
  inset: -10%;
  border-radius: 999px;
  border: 1px solid rgba(125, 211, 252, 0.35);
  animation: vpRing 4s linear infinite;
}

.vp-orb__core {
  position: absolute;
  inset: 22%;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.7), rgba(125, 211, 252, 0.16));
}

.vp-orb--listening {
  animation-duration: 1.1s;
  box-shadow:
    0 0 44px rgba(45, 212, 191, 0.55),
    0 0 120px rgba(56, 189, 248, 0.4);
}

.vp-orb--thinking {
  animation-duration: 2s;
  filter: hue-rotate(45deg);
}

.vp-orb--speaking {
  animation-duration: 0.8s;
  filter: hue-rotate(-25deg);
}

@keyframes vpBreath {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.06); }
}

@keyframes vpRing {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.vp-transcript {
  max-height: 14rem;
  overflow-y: auto;
  padding: 0.4rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.vp-msg {
  padding: 0.45rem 0.75rem;
  border-radius: 0.55rem;
  background: rgba(255, 255, 255, 0.06);
  font-size: 0.85rem;
  max-width: 88%;
}

.vp-msg--user {
  align-self: flex-end;
  background: rgba(129, 140, 248, 0.22);
}

.vp-msg__role {
  display: block;
  font-size: 0.66rem;
  color: rgba(203, 213, 225, 0.55);
  margin-bottom: 0.18rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.vp-msg__body {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.5;
}

.vp-empty {
  margin: 0.5rem 0 0;
  text-align: center;
  font-size: 0.78rem;
  color: rgba(203, 213, 225, 0.55);
}

.vp-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding-top: 0.6rem;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  margin-top: 0.4rem;
}

.vp-voice-pick {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: rgba(226, 232, 240, 0.85);
}

.vp-select {
  padding: 0.3rem 0.5rem;
  background: rgba(2, 6, 23, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  border-radius: 0.4rem;
}

.vp-btn {
  padding: 0.35rem 0.7rem;
  border-radius: 0.45rem;
  cursor: pointer;
  font-size: 0.78rem;
  border: 1px solid transparent;
}

.vp-btn--ghost {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(226, 232, 240, 0.85);
  border-color: rgba(255, 255, 255, 0.1);
}

.vp-btn--ghost:hover { background: rgba(255, 255, 255, 0.1); }

.vp-error {
  margin: 0.5rem 0 0;
  font-size: 0.78rem;
  color: rgba(252, 165, 165, 0.92);
}
</style>
