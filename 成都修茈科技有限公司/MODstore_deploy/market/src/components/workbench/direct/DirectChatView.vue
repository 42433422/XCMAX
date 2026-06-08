<template>
  <div class="wb-direct">
    <div class="wb-direct__scroll" ref="scrollRef">
      <div class="wb-direct__center">
        <div v-if="!hasMessages" class="wb-direct__welcome">
          <h2 class="wb-direct__greeting">有什么想问的？</h2>
          <p class="wb-direct__subtitle">选择一个话题开始，或直接输入你的问题</p>

          <div class="wb-direct__suggestions">
            <button
              v-for="card in suggestionCards"
              :key="card.label"
              type="button"
              class="wb-direct__card"
              @click="onSuggestionSelect(card.prompt)"
            >
              <span class="wb-direct__card-icon" v-html="card.icon" />
              <span class="wb-direct__card-label">{{ card.label }}</span>
              <span class="wb-direct__card-desc">{{ card.desc }}</span>
            </button>
          </div>
        </div>

        <div v-else class="wb-direct__messages">
          <!-- ChatMessageList placeholder -->
        </div>
      </div>
    </div>

    <div class="wb-direct__input-bar">
      <div class="wb-direct__input-wrapper">
        <button
          type="button"
          class="wb-direct__attach-btn"
          aria-label="添加附件"
          @click="emit('attach-file')"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
            <line x1="10" y1="4" x2="10" y2="16" />
            <line x1="4" y1="10" x2="16" y2="10" />
          </svg>
        </button>

        <textarea
          ref="textareaRef"
          v-model="inputText"
          class="wb-direct__textarea"
          :placeholder="'直接问问题，例如：帮我写一份门店日报自动化方案…'"
          rows="1"
          @input="autoResize"
          @keydown.enter.exact="onEnterSubmit"
        />

        <button
          type="button"
          class="wb-direct__send-btn"
          :class="{ 'wb-direct__send-btn--active': canSend }"
          :disabled="!canSend"
          aria-label="发送"
          @click="onSend"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M3 9L15 3L9 15L8 10L3 9Z" fill="currentColor" />
          </svg>
        </button>
      </div>

      <div class="wb-direct__input-footer">
        <div class="wb-direct__model-toggle">
          <button
            type="button"
            class="wb-direct__model-opt"
            :class="{ 'wb-direct__model-opt--active': modelMode === 'auto' }"
            @click="modelMode = 'auto'"
          >
            Auto
          </button>
          <button
            type="button"
            class="wb-direct__model-opt"
            :class="{ 'wb-direct__model-opt--active': modelMode === 'manual' }"
            @click="modelMode = 'manual'"
          >
            自选
          </button>
        </div>

        <button type="button" class="wb-direct__employee-btn">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="7" cy="4.5" r="2.5" />
            <path d="M2 13c0-2.76 2.24-5 5-5s5 2.24 5 5" />
          </svg>
          <span>选择员工</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'

const emit = defineEmits<{
  send: [text: string]
  'attach-file': []
  'new-chat': []
}>()

const hasMessages = ref(false)
const inputText = ref('')
const modelMode = ref<'auto' | 'manual'>('auto')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const scrollRef = ref<HTMLDivElement | null>(null)

const canSend = computed(() => inputText.value.trim().length > 0)

const suggestionCards = [
  {
    label: '帮我分析数据',
    desc: '上传表格或描述需求，快速获得洞察',
    prompt: '帮我分析数据',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="12" width="4" height="7" rx="1"/><rect x="9" y="8" width="4" height="11" rx="1"/><rect x="15" y="3" width="4" height="16" rx="1"/></svg>',
  },
  {
    label: '写一份方案',
    desc: '从大纲到完整方案，一键生成',
    prompt: '写一份方案',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-4-6z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="14" y2="13"/><line x1="8" y1="17" x2="14" y2="17"/></svg>',
  },
  {
    label: '总结文档要点',
    desc: '粘贴或上传文档，提炼核心要点',
    prompt: '总结文档要点',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/><line x1="8" y1="8" x2="14" y2="8"/><line x1="8" y1="11" x2="14" y2="11"/><line x1="8" y1="14" x2="12" y2="14"/></svg>',
  },
  {
    label: '生成代码片段',
    desc: '描述需求，自动生成可运行的代码',
    prompt: '生成代码片段',
    icon: '<svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="8 7 4 11 8 15"/><polyline points="14 7 18 11 14 15"/><line x1="12" y1="5" x2="10" y2="17"/></svg>',
  },
]

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

function onEnterSubmit(e: KeyboardEvent) {
  if (e.isComposing) return
  e.preventDefault()
  onSend()
}

function onSend() {
  const text = inputText.value.trim()
  if (!text) return
  hasMessages.value = true
  emit('send', text)
  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.style.height = 'auto'
    }
  })
}

function onSuggestionSelect(prompt: string) {
  inputText.value = prompt
  onSend()
}
</script>

<style scoped>
.wb-direct {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--wb-surface-sunken, rgba(0, 0, 0, 0.22));
}

/* ── Scroll area ── */
.wb-direct__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  justify-content: center;
}

.wb-direct__center {
  width: 100%;
  max-width: var(--wb-main-max-width, 768px);
  padding: var(--wb-main-padding-x, 24px);
}

/* ── Welcome ── */
.wb-direct__welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 260px);
  text-align: center;
  padding-bottom: 48px;
}

.wb-direct__greeting {
  font-size: 28px;
  font-weight: 700;
  color: var(--wb-text-primary, #f8fafc);
  margin: 0 0 8px;
  letter-spacing: -0.02em;
}

.wb-direct__subtitle {
  font-size: 14px;
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
  margin: 0 0 36px;
}

/* ── Suggestion grid ── */
.wb-direct__suggestions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
  max-width: 560px;
}

.wb-direct__card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 16px;
  border-radius: var(--wb-card-radius, 12px);
  background: var(--wb-card-bg, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--wb-card-border, rgba(255, 255, 255, 0.06));
  color: var(--wb-text-primary, #f8fafc);
  cursor: pointer;
  transition:
    transform var(--wb-transition-normal, 0.25s ease),
    background var(--wb-transition-fast, 0.15s ease),
    border-color var(--wb-transition-fast, 0.15s ease),
    box-shadow var(--wb-transition-normal, 0.25s ease);
  text-align: left;
  font-family: inherit;
  font-size: inherit;
  line-height: 1.5;
}

.wb-direct__card:hover {
  transform: translateY(-4px);
  background: var(--wb-card-hover-bg, rgba(255, 255, 255, 0.08));
  border-color: var(--wb-card-hover-border, rgba(129, 140, 248, 0.3));
  box-shadow: var(--wb-card-hover-shadow, 0 8px 32px rgba(0, 0, 0, 0.3));
}

.wb-direct__card:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus, 0 0 0 2px var(--wb-surface-elevated), 0 0 0 4px var(--color-focus-ring, rgba(96, 165, 250, 0.55)));
}

.wb-direct__card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--wb-accent-soft, rgba(129, 140, 248, 0.22));
  color: var(--wb-accent-primary, #818cf8);
  margin-bottom: 4px;
}

.wb-direct__card-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--wb-text-primary, #f8fafc);
}

.wb-direct__card-desc {
  font-size: 12px;
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
  line-height: 1.4;
}

/* ── Messages placeholder ── */
.wb-direct__messages {
  min-height: 200px;
}

/* ── Input bar ── */
.wb-direct__input-bar {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 var(--wb-main-padding-x, 24px) 16px;
}

.wb-direct__input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  width: 100%;
  max-width: var(--wb-main-max-width, 768px);
  padding: 10px 12px 10px 14px;
  border-radius: var(--wb-input-radius, 24px);
  background: var(--wb-input-bg, #2f2f2f);
  border: 1px solid var(--wb-input-border, rgba(255, 255, 255, 0.08));
  transition:
    border-color var(--wb-transition-fast, 0.15s ease),
    box-shadow var(--wb-transition-fast, 0.15s ease);
}

.wb-direct__input-wrapper:focus-within {
  border-color: var(--wb-accent-primary, #818cf8);
  box-shadow: 0 0 0 2px var(--wb-accent-soft, rgba(129, 140, 248, 0.22));
}

.wb-direct__attach-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
  cursor: pointer;
  transition:
    background var(--wb-transition-fast, 0.15s ease),
    color var(--wb-transition-fast, 0.15s ease);
  padding: 0;
}

.wb-direct__attach-btn:hover {
  background: var(--wb-surface-overlay, rgba(255, 255, 255, 0.06));
  color: var(--wb-text-primary, #f8fafc);
}

.wb-direct__attach-btn:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus, 0 0 0 2px var(--wb-surface-elevated), 0 0 0 4px var(--color-focus-ring, rgba(96, 165, 250, 0.55)));
}

.wb-direct__textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--wb-text-primary, #f8fafc);
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  font-family: inherit;
  padding: 4px 0;
  max-height: 200px;
  overflow-y: auto;
}

.wb-direct__textarea::placeholder {
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
}

.wb-direct__send-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: var(--wb-surface-overlay, rgba(255, 255, 255, 0.06));
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
  cursor: not-allowed;
  transition:
    background var(--wb-transition-fast, 0.15s ease),
    color var(--wb-transition-fast, 0.15s ease),
    transform var(--wb-transition-fast, 0.15s ease);
  padding: 0;
}

.wb-direct__send-btn--active {
  background: var(--wb-accent-primary, #818cf8);
  color: #fff;
  cursor: pointer;
}

.wb-direct__send-btn--active:hover {
  background: var(--wb-gradient-accent-hover, linear-gradient(135deg, #8b5cf6, #6366f1));
  transform: scale(1.05);
}

.wb-direct__send-btn:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus, 0 0 0 2px var(--wb-surface-elevated), 0 0 0 4px var(--color-focus-ring, rgba(96, 165, 250, 0.55)));
}

.wb-direct__send-btn:disabled {
  opacity: 0.5;
}

/* ── Input footer ── */
.wb-direct__input-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: var(--wb-main-max-width, 768px);
  padding: 8px 4px 0;
}

.wb-direct__model-toggle {
  display: flex;
  align-items: center;
  border-radius: 8px;
  background: var(--wb-surface-overlay, rgba(255, 255, 255, 0.06));
  overflow: hidden;
}

.wb-direct__model-opt {
  border: none;
  background: transparent;
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  cursor: pointer;
  transition:
    background var(--wb-transition-fast, 0.15s ease),
    color var(--wb-transition-fast, 0.15s ease);
  font-family: inherit;
}

.wb-direct__model-opt--active {
  background: var(--wb-accent-primary, #818cf8);
  color: #fff;
  border-radius: 6px;
}

.wb-direct__model-opt:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus, 0 0 0 2px var(--wb-surface-elevated), 0 0 0 4px var(--color-focus-ring, rgba(96, 165, 250, 0.55)));
}

.wb-direct__employee-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: transparent;
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  padding: 5px 10px;
  border-radius: 8px;
  transition:
    background var(--wb-transition-fast, 0.15s ease),
    color var(--wb-transition-fast, 0.15s ease);
  font-family: inherit;
}

.wb-direct__employee-btn:hover {
  background: var(--wb-surface-overlay, rgba(255, 255, 255, 0.06));
  color: var(--wb-text-primary, #f8fafc);
}

.wb-direct__employee-btn:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus, 0 0 0 2px var(--wb-surface-elevated), 0 0 0 4px var(--color-focus-ring, rgba(96, 165, 250, 0.55)));
}

/* ── Light theme overrides ── */
html[data-workbench-theme='light'] .wb-direct {
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .wb-direct__greeting {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-direct__subtitle {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct__card {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-direct__card:hover {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .wb-direct__card-icon {
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
}

html[data-workbench-theme='light'] .wb-direct__card-label {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-direct__card-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct__input-wrapper {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .wb-direct__input-wrapper:focus-within {
  border-color: #0071e3;
  box-shadow: 0 0 0 2px rgba(0, 113, 227, 0.15);
}

html[data-workbench-theme='light'] .wb-direct__attach-btn {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct__attach-btn:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-direct__textarea {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-direct__textarea::placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct__send-btn {
  background: rgba(0, 0, 0, 0.04);
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct__send-btn--active {
  background: #0071e3;
  color: #fff;
}

html[data-workbench-theme='light'] .wb-direct__send-btn--active:hover {
  background: #0077ed;
}

html[data-workbench-theme='light'] .wb-direct__model-toggle {
  background: rgba(0, 0, 0, 0.04);
}

html[data-workbench-theme='light'] .wb-direct__model-opt {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct__model-opt--active {
  background: #0071e3;
  color: #fff;
}

html[data-workbench-theme='light'] .wb-direct__employee-btn {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct__employee-btn:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}
</style>
