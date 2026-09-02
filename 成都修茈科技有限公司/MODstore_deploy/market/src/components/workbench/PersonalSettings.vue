<template>
  <Transition name="ps-fade">
    <div v-if="open" class="ps-mask" role="dialog" aria-modal="true" aria-labelledby="ps-title" @click.self="$emit('close')">
      <div class="ps-card">
        <header class="ps-head">
          <div class="ps-head-left">
            <svg class="ps-head-icon" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
              <circle cx="10" cy="5" r="3"/><path d="M3 18c0-3.87 3.13-7 7-7s7 3.13 7 7"/>
            </svg>
            <h2 id="ps-title" class="ps-title">个性化设置</h2>
          </div>
          <button type="button" class="ps-close" aria-label="关闭" @click="$emit('close')">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
              <line x1="3" y1="3" x2="13" y2="13"/><line x1="13" y1="3" x2="3" y2="13"/>
            </svg>
          </button>
        </header>

        <div class="ps-body">
          <section class="ps-section">
            <h3 class="ps-section-title" @click="toggleSection('theme')">
              <svg class="ps-section-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round">
                <circle cx="8" cy="8" r="3.5"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41"/>
              </svg>
              主题
              <svg class="ps-section-chevron" :class="{ 'ps-section-chevron--open': expandedSections.has('theme') }" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>
            </h3>
            <div v-show="expandedSections.has('theme')" class="ps-section-body">
            <div class="ps-row">
              <label v-for="t in themes" :key="t.id" class="ps-chip" :class="{ 'ps-chip--on': model.theme === t.id }">
                <input
                  v-model="model.theme"
                  type="radio"
                  :value="t.id"
                  class="ps-sr-only"
                  @change="emitChange"
                />
                <span class="ps-chip-icon">{{ t.icon }}</span>
                <span class="ps-chip-text">{{ t.label }}</span>
              </label>
            </div>
            </div>
          </section>

          <section class="ps-section">
            <h3 class="ps-section-title" @click="toggleSection('font')">
              <svg class="ps-section-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round">
                <path d="M2 12h12M2 8h12M2 4h12"/>
              </svg>
              字号 <span class="ps-section-badge">{{ model.fontPx }}px</span>
              <svg class="ps-section-chevron" :class="{ 'ps-section-chevron--open': expandedSections.has('font') }" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>
            </h3>
            <div v-show="expandedSections.has('font')" class="ps-section-body">
            <div class="ps-range-wrap">
              <span class="ps-range-label">A</span>
              <input
                v-model.number="model.fontPx"
                type="range"
                min="13"
                max="20"
                step="1"
                class="ps-range"
                @change="emitChange"
              />
              <span class="ps-range-label ps-range-label--lg">A</span>
            </div>
            </div>
          </section>

          <section class="ps-section">
            <h3 class="ps-section-title" @click="toggleSection('tts')">
              <svg class="ps-section-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round">
                <path d="M8 1v6"/><path d="M5 4a3 3 0 016 0v2a3 3 0 01-6 0V4z"/><path d="M2 10v1a6 6 0 0012 0v-1"/>
              </svg>
              朗读
              <svg class="ps-section-chevron" :class="{ 'ps-section-chevron--open': expandedSections.has('tts') }" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>
            </h3>
            <div v-show="expandedSections.has('tts')" class="ps-section-body">
            <p class="ps-hint">快速朗读：分句预合成，首句就绪即播（对标豆包/GPT 出声速度）。</p>
            <label class="ps-field-label">语音对话模式</label>
            <div class="ps-row">
              <label class="ps-chip" :class="{ 'ps-chip--on': model.voiceSpeechMode === 'unified' }">
                <input v-model="model.voiceSpeechMode" class="ps-sr-only" type="radio" value="unified" @change="emitChange" />
                <span class="ps-chip-text">电话式统一（推荐）</span>
              </label>
              <label class="ps-chip" :class="{ 'ps-chip--on': model.voiceSpeechMode === 's2s' }">
                <input v-model="model.voiceSpeechMode" class="ps-sr-only" type="radio" value="s2s" @change="emitChange" />
                <span class="ps-chip-text">实时语音 S2S</span>
              </label>
              <label class="ps-chip" :class="{ 'ps-chip--on': model.voiceSpeechMode === 'cascade' }">
                <input v-model="model.voiceSpeechMode" class="ps-sr-only" type="radio" value="cascade" @change="emitChange" />
                <span class="ps-chip-text">标准级联</span>
              </label>
            </div>
            <p class="ps-hint">电话式统一：单连接流式听写 + 提前开答 + 播报可打断（对标豆包打电话）；需开启自动朗读且选微软云端。</p>
            <div class="ps-row">
              <label class="ps-chip" :class="{ 'ps-chip--on': model.ttsEngine !== 'edge-online' }">
                <input v-model="model.ttsEngine" class="ps-sr-only" type="radio" value="auto" @change="emitChange" />
                <span class="ps-chip-text">MiMo → Edge</span>
              </label>
              <label class="ps-chip" :class="{ 'ps-chip--on': model.ttsEngine === 'edge-online' }">
                <input v-model="model.ttsEngine" class="ps-sr-only" type="radio" value="edge-online" @change="emitChange" />
                <span class="ps-chip-text">仅 Edge 神经音</span>
              </label>
            </div>
            <p class="ps-hint">默认优先小米 MiMo 神经音，失败再回退微软 Edge；不再使用浏览器系统 TTS。</p>
            <template v-if="model.ttsEngine === 'edge-online'">
              <label class="ps-field-label" for="ps-tts-edge-voice">Edge 音色</label>
              <select id="ps-tts-edge-voice" v-model="model.ttsEdgeVoice" class="ps-select" @change="emitChange">
                <option v-for="ev in edgeVoices" :key="ev.id" :value="ev.id">{{ ev.label }}</option>
              </select>
            </template>
            <template v-else>
              <label class="ps-field-label" for="ps-tts-edge-voice-fb">Edge 回退音色</label>
              <select id="ps-tts-edge-voice-fb" v-model="model.ttsEdgeVoice" class="ps-select" @change="emitChange">
                <option v-for="ev in edgeVoices" :key="ev.id" :value="ev.id">{{ ev.label }}</option>
              </select>
            </template>
              <label class="ps-field-label ps-field-label--spaced" for="ps-tts-rate">语速 <span class="ps-section-badge">{{ model.ttsRate.toFixed(1) }}×</span></label>
            <div class="ps-range-wrap">
              <span class="ps-range-label">0.6×</span>
              <input
                id="ps-tts-rate"
                v-model.number="model.ttsRate"
                type="range"
                min="0.6"
                max="1.6"
                step="0.1"
                class="ps-range"
                @change="emitChange"
              />
              <span class="ps-range-label">1.6×</span>
            </div>
            </div>
          </section>

          <section class="ps-section">
            <h3 class="ps-section-title" @click="toggleSection('memory')">
              <svg class="ps-section-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round">
                <path d="M8 2v2M8 12v2M2 8h2M12 8h2"/><circle cx="8" cy="8" r="2.5"/><path d="M4 4l1.5 1.5M10.5 10.5L12 12M4 12l1.5-1.5M10.5 4.5L12 3"/>
              </svg>
              长期记忆
              <svg class="ps-section-chevron" :class="{ 'ps-section-chevron--open': expandedSections.has('memory') }" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>
            </h3>
            <div v-show="expandedSections.has('memory')" class="ps-section-body">
            <textarea
              v-model="model.memory"
              class="ps-textarea"
              rows="4"
              placeholder="输入记忆内容…"
              spellcheck="false"
              @blur="emitChange"
            />
            <div class="ps-row ps-row--between">
              <button type="button" class="ps-btn ps-btn--ghost" @click="resetMemory">清空</button>
              <span class="ps-counter" :class="{ 'ps-counter--warn': model.memory.length > 500 }">{{ model.memory.length }}/600</span>
            </div>
            </div>
          </section>

          <section class="ps-section">
            <h3 class="ps-section-title" @click="toggleSection('suggestions')">
              <svg class="ps-section-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round">
                <path d="M6 2l6 6-6 6"/>
              </svg>
              推荐问题模板
              <svg class="ps-section-chevron" :class="{ 'ps-section-chevron--open': expandedSections.has('suggestions') }" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>
            </h3>
            <div v-show="expandedSections.has('suggestions')" class="ps-section-body">
            <textarea
              v-model="suggestionsRaw"
              class="ps-textarea"
              rows="4"
              placeholder="每行一条快捷提问"
              spellcheck="false"
              @blur="onSuggestionsBlur"
            />
            </div>
          </section>
        </div>

        <footer class="ps-foot">
          <button type="button" class="ps-btn ps-btn--ghost" @click="$emit('close')">取消</button>
          <button type="button" class="ps-btn ps-btn--primary" @click="onSave">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M2 8l3 3 7-7"/></svg>
            保存
          </button>
        </footer>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：表单模型 / 同步 / 提交逻辑在 ./personal-settings/，样式在 ./personal-settings/personalSettings.css。
import { onBeforeUnmount, ref, watch } from 'vue'
import type { PersonalSettings } from '../../utils/personalSettings'
import { usePersonalSettingsModel } from './personal-settings/usePersonalSettingsModel'

const props = defineProps<{
  open: boolean
  modelValue: PersonalSettings
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:modelValue', v: PersonalSettings): void
}>()

const {
  themes, edgeVoices, model, suggestionsRaw, expandedSections,
  toggleSection, onSuggestionsBlur, emitChange, resetMemory, onSave,
} = usePersonalSettingsModel(props, emit)

const voiceList = ref<Array<{ name: string; label: string }>>([])

function loadVoices() {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    voiceList.value = []
    return
  }
  const synth = window.speechSynthesis
  const all = synth.getVoices()
  const zh = all
    .filter((v) => /^zh|cmn|yue/i.test(v.lang))
    .map((v) => ({ name: v.name, label: `${v.name} (${v.lang})` }))
  const en = all.filter((v) => /^en/i.test(v.lang)).slice(0, 6).map((v) => ({ name: v.name, label: `${v.name} (${v.lang})` }))
  voiceList.value = [...zh, ...en]
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    loadVoices()
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.onvoiceschanged = loadVoices
    }
  },
)

onBeforeUnmount(() => {
  if (typeof window !== 'undefined' && 'speechSynthesis' in window && window.speechSynthesis.onvoiceschanged === loadVoices) {
    window.speechSynthesis.onvoiceschanged = null
  }
})
</script>

<style scoped src="./personal-settings/personalSettings.css"></style>
