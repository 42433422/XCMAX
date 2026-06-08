<template>
  <div class="mf-view">
    <div class="mf-view__content">
      <div class="mf-welcome">
        <p class="mf-welcome__kicker">你好，admin</p>
        <h1 class="mf-welcome__title">今天有什么安排？</h1>
      </div>

      <nav class="mf-starters" aria-label="制作类型选择">
        <button
          v-for="s in starters"
          :key="s.key"
          type="button"
          class="mf-starter"
          :class="{ 'mf-starter--active': activeStarter === s.key }"
          @click="onSelectStarter(s.key)"
        >
          <div class="mf-starter__body">
            <span class="mf-starter__title">{{ s.title }}</span>
            <span class="mf-starter__sub">{{ s.desc }}</span>
          </div>
          <span class="mf-starter__arrow" aria-hidden="true">→</span>
        </button>
      </nav>

      <div v-if="activeIntent" class="mf-intent">
        <span class="mf-intent__title">{{ activeIntent.title }}</span>
        <span class="mf-intent__desc">{{ activeIntent.desc }}</span>
      </div>

      <div class="mf-input-bar">
        <textarea
          v-model="inputText"
          class="mf-input-bar__field"
          :placeholder="inputPlaceholder"
          rows="1"
          @keydown.enter.exact.prevent="onSend"
          @input="autoResize"
        />
        <button
          type="button"
          class="mf-input-bar__send"
          :disabled="!inputText.trim()"
          @click="onSend"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>

    <footer class="mf-foot">
      选择类型后输入想法：Enter 先进入需求规划（多轮问答与清单），确认后再在制作草稿中启动生成。
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

type StarterKey = 'mod' | 'employee' | 'skill'

interface Starter {
  key: StarterKey
  title: string
  desc: string
}

const starters: Starter[] = [
  { key: 'mod', title: '做 Mod', desc: '先建仓库 · 行业 JSON · 员工命名' },
  { key: 'employee', title: '做员工', desc: '提示词与工具 · 填入描述' },
  { key: 'skill', title: '生成 Skill 组', desc: '画布编排 · 先拆 Skill 再组合' },
]

const activeStarter = ref<StarterKey>('skill')
const inputText = ref('')

const activeIntent = computed(() => {
  const s = starters.find((x) => x.key === activeStarter.value)
  if (!s) return null
  return {
    title: s.title,
    desc:
      s.key === 'mod'
        ? '创建 Mod：先建仓库，再配置行业 JSON，最后命名员工。'
        : s.key === 'employee'
          ? '创建员工：编写提示词、挂载工具，填入描述即可。'
          : '生成 Skill 组：在画布上编排调度图，先拆 Skill 再组合。',
  }
})

const inputPlaceholder = computed(() => {
  const s = starters.find((x) => x.key === activeStarter.value)
  return s ? `描述你想${s.title}的内容…` : '输入你的想法…'
})

const emit = defineEmits<{
  send: [text: string, intent: StarterKey]
  'select-starter': [key: StarterKey]
}>()

function onSelectStarter(key: StarterKey) {
  activeStarter.value = key
  emit('select-starter', key)
}

function onSend() {
  const text = inputText.value.trim()
  if (!text) return
  emit('send', text, activeStarter.value)
  inputText.value = ''
}

function autoResize(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}
</script>

<style scoped>
.mf-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--wb-surface-sunken, rgba(0, 0, 0, 0.22));
}

.mf-view__content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: clamp(0.72rem, 1.4vw, 1rem);
  padding: var(--wb-main-padding-x, 24px);
  max-width: var(--wb-main-max-width, 768px);
  width: 100%;
  margin: 0 auto;
}

.mf-welcome {
  text-align: center;
  margin-bottom: clamp(0.6rem, 1.6vw, 1.2rem);
}

.mf-welcome__kicker {
  margin: 0 0 0.45rem;
  color: rgba(165, 180, 252, 0.75);
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.mf-welcome__title {
  margin: 0;
  color: var(--wb-text-primary, #f8fafc);
  font-size: clamp(2rem, 5vw, 3.2rem);
  line-height: 1.08;
  letter-spacing: -0.05em;
}

.mf-starters {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: clamp(0.65rem, 1.3vw, 0.9rem);
  width: 100%;
}

.mf-starter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  width: 100%;
  min-height: 5.35rem;
  padding: clamp(0.9rem, 0.8rem + 0.32vw, 1.05rem) clamp(1rem, 0.9rem + 0.3vw, 1.2rem);
  border-radius: var(--wb-card-radius, 12px);
  border: 1px solid var(--wb-card-border, rgba(255, 255, 255, 0.06));
  background: var(--wb-card-bg, rgba(255, 255, 255, 0.04));
  font: inherit;
  text-align: left;
  text-decoration: none;
  color: inherit;
  cursor: pointer;
  transition:
    transform var(--wb-transition-normal, 0.25s ease),
    background var(--wb-transition-fast, 0.15s ease),
    border-color var(--wb-transition-fast, 0.15s ease),
    box-shadow var(--wb-transition-normal, 0.25s ease);
}

.mf-starter:hover {
  transform: translateY(-4px);
  background: var(--wb-card-hover-bg, rgba(255, 255, 255, 0.08));
  border-color: var(--wb-card-hover-border, rgba(129, 140, 248, 0.3));
  box-shadow: var(--wb-card-hover-shadow, 0 8px 32px rgba(0, 0, 0, 0.3));
}

.mf-starter:focus-visible {
  outline: 2px solid var(--wb-accent-primary, rgba(255, 255, 255, 0.45));
  outline-offset: 2px;
}

.mf-starter--active {
  border-color: var(--wb-accent-primary, #818cf8);
  background: var(--wb-accent-soft, rgba(129, 140, 248, 0.22));
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.15);
}

.mf-starter--active:hover {
  transform: translateY(-4px);
  background: var(--wb-accent-soft, rgba(129, 140, 248, 0.28));
  border-color: var(--wb-accent-primary, #818cf8);
  box-shadow:
    0 0 0 1px rgba(129, 140, 248, 0.2),
    0 8px 32px rgba(0, 0, 0, 0.3);
}

.mf-starter__body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  min-width: 0;
  text-align: left;
}

.mf-starter__title {
  font-size: clamp(0.95rem, 0.9rem + 0.2vw, 1.05rem);
  font-weight: 600;
  color: var(--wb-text-secondary, rgba(255, 255, 255, 0.92));
}

.mf-starter__sub {
  font-size: clamp(0.8rem, 0.75rem + 0.15vw, 0.9rem);
  line-height: 1.35;
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.4));
}

.mf-starter__arrow {
  flex-shrink: 0;
  font-size: 1rem;
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.35));
  transition: color var(--wb-transition-fast, 0.15s ease);
}

.mf-starter:hover .mf-starter__arrow {
  color: rgba(255, 255, 255, 0.55);
}

.mf-starter--active .mf-starter__arrow {
  color: rgba(199, 210, 254, 0.85);
}

.mf-intent {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.45rem 0.85rem;
  border-radius: var(--wb-radius-md, 10px);
  background: var(--wb-accent-soft, rgba(129, 140, 248, 0.12));
  border: 1px solid rgba(129, 140, 248, 0.18);
  width: 100%;
}

.mf-intent__title {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--wb-accent-primary, #818cf8);
  white-space: nowrap;
}

.mf-intent__desc {
  font-size: 0.82rem;
  color: var(--wb-text-muted, rgba(226, 232, 240, 0.62));
  line-height: 1.4;
}

.mf-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 0.55rem;
  width: 100%;
  padding: 0.65rem 0.85rem;
  border-radius: var(--wb-input-radius, 24px);
  background: var(--wb-input-bg, #2f2f2f);
  border: 1px solid var(--wb-input-border, rgba(255, 255, 255, 0.08));
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.18);
  transition:
    border-color var(--wb-transition-fast, 0.15s ease),
    box-shadow var(--wb-transition-fast, 0.15s ease);
}

.mf-input-bar:focus-within {
  border-color: rgba(129, 140, 248, 0.4);
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.18),
    0 0 0 2px rgba(129, 140, 248, 0.12);
}

.mf-input-bar__field {
  flex: 1;
  min-height: 1.5rem;
  max-height: 8rem;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--wb-text-primary, #f8fafc);
  font: inherit;
  font-size: 1rem;
  line-height: 1.5;
}

.mf-input-bar__field::placeholder {
  color: rgba(255, 255, 255, 0.34);
}

.mf-input-bar__send {
  flex-shrink: 0;
  width: 2.25rem;
  height: 2.25rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  color: #121212;
  background: #fff;
  transform: translateZ(0);
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.mf-input-bar__send:hover:not(:disabled) {
  opacity: 0.92;
  transform: scale(1.03);
}

.mf-input-bar__send:disabled {
  opacity: 0.25;
  cursor: not-allowed;
}

.mf-foot {
  flex-shrink: 0;
  text-align: center;
  padding: 0.55rem var(--wb-main-padding-x, 24px);
  font-size: 0.75rem;
  line-height: 1.45;
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.32));
}

@media (max-width: 760px) {
  .mf-starters {
    grid-template-columns: 1fr;
  }
}

/* ── Light theme overrides ── */
html[data-workbench-theme='light'] .mf-view {
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .mf-welcome__kicker {
  color: rgba(0, 113, 227, 0.7);
}

html[data-workbench-theme='light'] .mf-welcome__title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .mf-starter {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .mf-starter:hover {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.1);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .mf-starter--active {
  border-color: #0071e3;
  background: rgba(0, 113, 227, 0.08);
  box-shadow: 0 0 0 1px rgba(0, 113, 227, 0.12);
}

html[data-workbench-theme='light'] .mf-starter--active:hover {
  background: rgba(0, 113, 227, 0.12);
  border-color: #0071e3;
  box-shadow: 0 0 0 1px rgba(0, 113, 227, 0.15), 0 4px 16px rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .mf-starter__title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .mf-starter__sub {
  color: #86868b;
}

html[data-workbench-theme='light'] .mf-starter__arrow {
  color: rgba(0, 0, 0, 0.2);
}

html[data-workbench-theme='light'] .mf-starter:hover .mf-starter__arrow {
  color: rgba(0, 0, 0, 0.4);
}

html[data-workbench-theme='light'] .mf-starter--active .mf-starter__arrow {
  color: rgba(0, 113, 227, 0.7);
}

html[data-workbench-theme='light'] .mf-intent {
  background: rgba(0, 113, 227, 0.06);
  border-color: rgba(0, 113, 227, 0.12);
}

html[data-workbench-theme='light'] .mf-intent__title {
  color: #0071e3;
}

html[data-workbench-theme='light'] .mf-intent__desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .mf-input-bar {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .mf-input-bar:focus-within {
  border-color: rgba(0, 113, 227, 0.4);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06), 0 0 0 2px rgba(0, 113, 227, 0.1);
}

html[data-workbench-theme='light'] .mf-input-bar__field {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .mf-input-bar__field::placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .mf-input-bar__send {
  color: #fff;
  background: #0071e3;
}

html[data-workbench-theme='light'] .mf-input-bar__send:hover:not(:disabled) {
  background: #0077ed;
}

html[data-workbench-theme='light'] .mf-input-bar__send:disabled {
  background: rgba(0, 0, 0, 0.08);
  color: #86868b;
}

html[data-workbench-theme='light'] .mf-foot {
  color: #86868b;
}
</style>
