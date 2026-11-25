<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElPopover } from 'element-plus/es/components/popover/index'
import { ElSlider } from 'element-plus/es/components/slider/index'
import './xiaocLife.css'
import { xiaocLevelLabels, xiaocStateLabel } from '../../application/xiaocLifeApi'
import { useXiaoCLife } from '../../composables/useXiaoCLife'

const props = defineProps<{ owner: number; light?: boolean; compact?: boolean }>()
const emit = defineEmits<{ (e: 'open-life'): void }>()
const life = useXiaoCLife(() => props.owner)
const selection = ref(1)
const expanded = ref(false)
let compactSession = 0
const triggerRef = ref<HTMLButtonElement | null>(null)
const contentRef = ref<HTMLElement | null>(null)
const marks = { 1: 'L1', 2: 'L2', 3: 'L3', 4: 'L4', 5: 'L5', 6: 'L6' }
const label = computed(() =>
  life.state ? `L${life.state.level} · ${xiaocLevelLabels[life.state.level] ?? '模式待核实'}` : life.loading ? '正在读取自主模式' : '自主模式待核实',
)
const activity = computed(() =>
  life.error
    ? '状态待同步'
    : life.state?.stopped
      ? '自主活动已停止'
      : life.state?.paused
        ? '自主活动已暂停'
        : life.state?.activity?.summary || xiaocStateLabel(life.state?.status ?? ''),
)
const canApply = computed(() => !!life.state && !life.saving && !life.error && selection.value !== life.state.level)
const modeDescriptions: Readonly<Record<number, string>> = {
  1: '专注对话、理解与建议。',
  2: '在既有权限内处理明确任务。',
  3: '自主推进任务，关注执行与结果核验。',
  4: '按已有授权持续推进企业工作。',
  5: '在已有预算内开展探索与能力改进。',
  6: '在明确授权内推进长期目标与复盘。',
}
const previewLabel = computed(() => `L${selection.value} · ${xiaocLevelLabels[selection.value] ?? '模式待核实'}`)
const popoverAttrs = computed(() => ({
  visible: expanded.value,
  placement: 'top-end' as const,
  fallbackPlacements: ['top-start', 'bottom-end', 'bottom-start'],
  width: 300,
  offset: 10,
  showArrow: false,
  teleported: true,
  persistent: true,
  role: 'dialog' as const,
  transition: 'xiaoc-autonomy-motion',
  popperClass: 'xiaoc-autonomy-popover',
}))
watch(
  [() => life.state?.level, () => life.state?.revision, () => props.owner],
  ([level]) => { selection.value = level ?? 1 },
  { immediate: true },
)
function isLevel(value: number | number[]): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 6
}
function selectLevel(value: number | number[]) {
  if (isLevel(value)) selection.value = value
}

async function changeLevel(value: number | number[]) {
  if (!isLevel(value) || !life.state || life.error || life.saving) return
  if (props.compact) {
    selection.value = value
    return
  }
  if (value === life.state.level) return
  await life.save({ level: value })
  selection.value = life.state?.level ?? 1
}

function closeCompact(restoreFocus = false) {
  if (expanded.value) compactSession += 1
  expanded.value = false
  selection.value = life.state?.level ?? 1
  if (restoreFocus) triggerRef.value?.focus({ preventScroll: true })
}
function toggleCompact() {
  if (expanded.value) closeCompact()
  else {
    compactSession += 1
    selection.value = life.state?.level ?? 1
    expanded.value = true
  }
}
function insideCompact(event: Event) {
  const path = event.composedPath()
  return [triggerRef.value, contentRef.value].some(element => element !== null && path.includes(element))
}
function onOutside(event: Event) {
  if (!expanded.value || insideCompact(event)) return
  // The panel is non-modal: do not steal focus from the next target.
  closeCompact()
}
function onEscape(event: KeyboardEvent) {
  if (!expanded.value || event.key !== 'Escape' || event.defaultPrevented || !insideCompact(event)) return
  event.stopPropagation()
  event.preventDefault()
  closeCompact(true)
}
function openLife() {
  // The composer may be hidden while the activity view is shown. Close its teleported surface first.
  closeCompact()
  emit('open-life')
}
function focusContent() {
  if (expanded.value) contentRef.value?.focus({ preventScroll: true })
}
onMounted(() => {
  document.addEventListener('pointerdown', onOutside, true)
  document.addEventListener('focusin', onOutside, true)
  document.addEventListener('keydown', onEscape, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onOutside, true)
  document.removeEventListener('focusin', onOutside, true)
  document.removeEventListener('keydown', onEscape, true)
})
watch(() => props.owner, () => closeCompact())
watch(() => props.compact, (compact) => { if (!compact) closeCompact() })
async function applyLevel() {
  const state = life.state
  if (!state || !canApply.value) return
  const session = compactSession
  const owner = props.owner
  const saved = await life.save({ level: selection.value }, state.revision)
  if (session !== compactSession || owner !== props.owner) return
  selection.value = life.state?.level ?? 1
  if (saved && expanded.value) closeCompact(true)
}
</script>

<template>
  <component
    :is="compact ? ElPopover : 'div'"
    v-bind="compact ? popoverAttrs : {}"
    @after-enter="focusContent"
  >
    <template v-if="compact" #reference>
      <button
        ref="triggerRef"
        type="button"
        class="xiaoc-life-disclosure__trigger"
        :class="{ 'xiaoc-life-disclosure__trigger--light': light, 'xiaoc-life-disclosure__trigger--open': expanded }"
        v-bind="{ 'data-xiaoc-autonomy-trigger': '' }"
        aria-haspopup="dialog"
        :aria-expanded="expanded"
        :title="life.error ? '自主任务设置：状态待同步' : '自主任务设置（全企业）'"
        @click="toggleCompact"
      >
        <span>自主任务</span>
        <svg viewBox="0 0 12 12" width="12" height="12" fill="none" aria-hidden="true">
          <path d="m3 4.5 3 3 3-3" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.4" />
        </svg>
      </button>
    </template>
  <section
    ref="contentRef"
    class="xiaoc-life-control"
    :tabindex="compact ? -1 : undefined"
    v-bind="{ 'data-xiaoc-control-plane': '' }"
    :class="{ 'xiaoc-life-control--light': light, 'xiaoc-life-control--compact': compact }"
    aria-label="企业小 C 自主模式"
    :aria-busy="life.loading || life.saving"
  >
    <div class="xiaoc-life-control__head">
      <div class="xiaoc-life-control__heading">
        <strong>{{ compact ? '自主任务' : label }}</strong>
      </div>
      <span>全企业生效</span>
      <div v-if="!compact" class="xiaoc-life-control__actions">
      <button v-if="life.state?.stopped" type="button" :disabled="life.saving || !!life.error" @click="life.save({ stopped: false, paused: false })">
        启动自主活动
      </button>
      <template v-else-if="life.state">
        <button type="button" :disabled="life.saving || !!life.error" @click="life.save({ paused: !life.state.paused })">
          {{ life.state.paused ? '恢复自主活动' : '暂停自主活动' }}
        </button>
        <button type="button" :disabled="life.saving || !!life.error" @click="life.save({ stopped: true })">停止自主活动</button>
      </template>
      </div>
    </div>
    <div v-if="compact" class="xiaoc-life-control__preview" aria-live="polite" aria-atomic="true">
      <strong>{{ life.state ? (selection === life.state.level ? previewLabel : '预选 ' + previewLabel) : label }}</strong>
      <span v-if="life.state">{{ modeDescriptions[selection] }}</span>
      <span v-if="life.state" class="xiaoc-life-control__applied">{{ life.error ? '上次读取的设置，当前状态待核实' : selection === life.state.level ? '已应用' : '当前已应用 ' + label }}</span>
    </div>
    <ElSlider

      :model-value="selection"
      :min="1"
      :max="6"
      :step="1"
      :marks="marks"
      show-stops
      :show-tooltip="!compact"
      :disabled="!life.state || life.saving || !!life.error"
      :format-tooltip="(value: number) => `L${value} · ${xiaocLevelLabels[value]}`"
      v-bind="{ ariaLabel: '小 C 全企业自主等级', 'data-autonomy-preview': compact ? selection : undefined }"
      @update:model-value="selectLevel"
      @change="changeLevel"
    />
    <div class="xiaoc-life-control__foot">
      <span role="status">{{ life.error ? activity : life.state ? activity : '尚未读取运行状态' }}</span>
      <button type="button" @click="openLife">目标与预算</button>
    </div>
    <div v-if="compact" class="xiaoc-life-control__actions">
    <button v-if="life.state?.stopped" type="button" :disabled="life.saving || !!life.error" @click="life.save({ stopped: false, paused: false })">
      启动自主活动
    </button>
    <template v-else-if="life.state">
      <button type="button" :disabled="life.saving || !!life.error" @click="life.save({ paused: !life.state.paused })">
        {{ life.state.paused ? '恢复自主活动' : '暂停自主活动' }}
      </button>
      <button type="button" :disabled="life.saving || !!life.error" @click="life.save({ stopped: true })">停止自主活动</button>
    </template>
    </div>
    <div v-if="life.state?.state_version !== undefined" class="xiaoc-life-control__foot">
      <span :title="life.state.identity_id">状态版本 {{ life.state.state_version }} · 授权版本 {{ life.state.revision }}</span>
      <span v-if="life.state.activity?.phase">{{ life.state.activity.phase }}</span>
      <span v-if="life.state.activity?.checkpoint_phase">
        {{ life.state.activity.checkpoint_phase === 'reflect' ? '已保存复盘回执' : '已保存执行回执' }}
      </span>
    </div>
    <div v-if="life.state?.blockers.length" class="xiaoc-life-control__error" role="status">
      {{ life.state.blockers.join('；') }}
    </div>
    <div v-if="life.error" class="xiaoc-life-control__error" role="alert">
      {{ life.error }} <button type="button" :disabled="life.loading || life.saving" @click="life.refresh()">刷新</button>
    </div>
    <div v-if="compact" class="xiaoc-life-control__confirm">
      <span>切换影响全企业，不扩大授权。</span>
      <button type="button" :disabled="!canApply" @click="applyLevel">{{ life.saving ? '保存中…' : '确认切换' }}</button>
    </div>
  </section>
  </component>
</template>

<style scoped>
.xiaoc-life-disclosure__trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  gap: 5px;
  min-height: 32px;
  margin: 3px 1px 3px 0;
  padding: 5px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #bcb9b2;
  font: inherit;
  font-size: 0.75rem;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease), color var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease), transform var(--wb-transition-normal, var(--xc-token-motion-standard-ms) ease-out);
}
.xiaoc-life-disclosure__trigger:hover,
.xiaoc-life-disclosure__trigger--open { background: #ffffff0d; color: #f2efe8; }
.xiaoc-life-disclosure__trigger--light { color: #716d65; }
.xiaoc-life-disclosure__trigger--light:hover,
.xiaoc-life-disclosure__trigger--light.xiaoc-life-disclosure__trigger--open { background: #24201808; color: #302e29; }
.xiaoc-life-disclosure__trigger:active { transform: scale(.97); }
.xiaoc-life-disclosure__trigger:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
.xiaoc-life-disclosure__trigger svg { opacity: 0.72; transition: transform var(--wb-transition-normal, var(--xc-token-motion-standard-ms) ease-out); }
.xiaoc-life-disclosure__trigger--open svg { transform: rotate(180deg); }

:global(.xiaoc-autonomy-popover.el-popper) {
  max-width: calc(100vw - 24px);
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  border-radius: 14px;
  box-shadow: none;
}
/* Popper owns positioning. Animate the inner surface, never its position transform. */
:global(.xiaoc-autonomy-motion-enter-active) { transition: opacity var(--wb-transition-normal, var(--xc-token-motion-standard-ms) ease-out); }
:global(.xiaoc-autonomy-motion-leave-active) { transition: opacity var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease); }
:global(.xiaoc-autonomy-motion-enter-from),
:global(.xiaoc-autonomy-motion-leave-to) { opacity: 0; }
:global(.xiaoc-autonomy-motion-enter-active .xiaoc-life-control--compact) {
  transition: transform var(--wb-transition-normal, var(--xc-token-motion-standard-ms) ease-out);
}
:global(.xiaoc-autonomy-motion-leave-active .xiaoc-life-control--compact) { transition: transform var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease); }
:global(.xiaoc-autonomy-motion-enter-from .xiaoc-life-control--compact),
:global(.xiaoc-autonomy-motion-leave-to .xiaoc-life-control--compact) { transform: translateY(4px) scale(.985); }

.xiaoc-life-control {
  --life-muted: #aeb9ca;
  --life-fg: #e9eff8;
  --life-border: #343c49;
  --life-error: #ffba9d;
  flex-shrink: 0;
  padding: 10px 18px 8px;
  border-bottom: 1px solid var(--life-border);
  color: var(--life-fg);
  font-size: 0.76rem;
  --el-text-color-regular: var(--life-muted);
}
.xiaoc-life-control--light {
  --life-muted: #46556b;
  --life-fg: #18283d;
  --life-border: #d9e0eb;
  --life-error: #8a311d;
}
.xiaoc-life-control__head,
.xiaoc-life-control__foot,
.xiaoc-life-control__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.xiaoc-life-control__actions { display: contents; }
.xiaoc-life-control__head > span { color: var(--life-muted); font-size: 0.7rem; }
.xiaoc-life-control__head button,
.xiaoc-life-control__foot button { margin-left: auto; flex-shrink: 0; }
.xiaoc-life-control :deep(.el-slider) {
  margin-bottom: 20px;
  --el-slider-height: 4px;
  --el-slider-button-size: 13px;
}
.xiaoc-life-control__foot > span {
  min-width: 0;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.xiaoc-life-control button {
  color: inherit;
  background: transparent;
  border: 0;
  padding: 2px 0;
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.xiaoc-life-control button:disabled { cursor: default; opacity: 0.5; }
.xiaoc-life-control__error { color: var(--life-error); margin-top: 6px; }

.xiaoc-life-control--compact {
  --life-fg: #eeeae2;
  --life-muted: #aaa69e;
  --life-border: #ffffff14;
  --life-surface: #292826;
  --life-accent: #d2b08e;
  --life-track: #ffffff20;
  --life-hover: #ffffff0a;
  --life-button-fg: #29231d;
  box-sizing: border-box;
  width: 100%;
  max-height: min(480px, 72vh);
  max-height: min(480px, 72dvh);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 16px;
  border: 1px solid var(--life-border);
  border-radius: 14px;
  background: var(--life-surface);
  box-shadow: 0 2px 6px #0002, 0 12px 32px #0004;
  font-size: 0.78rem;
  line-height: 1.5;
  transform-origin: bottom right;
}
.xiaoc-life-control--compact.xiaoc-life-control--light {
  --life-fg: #34312b;
  --life-muted: #79746b;
  --life-border: #e8e4dc;
  --life-error: #8a311d;
  --life-surface: #fdfcf9;
  --life-accent: #9a7353;
  --life-track: #e6e0d6;
  --life-hover: #24201807;
  --life-button-fg: #fff;
  box-shadow: 0 2px 6px #29201808, 0 12px 32px #29201816;
}
.xiaoc-life-control--compact:focus { outline: none; }
.xiaoc-life-control--compact .xiaoc-life-control__head { justify-content: space-between; gap: 6px; }
.xiaoc-life-control__heading { min-width: 0; }
.xiaoc-life-control--compact .xiaoc-life-control__heading strong { display: block; font-size: 0.95rem; font-weight: 600; letter-spacing: -0.015em; }
.xiaoc-life-control--compact .xiaoc-life-control__actions { display: flex; gap: 4px; flex-basis: 100%; }
.xiaoc-life-control--compact .xiaoc-life-control__actions button { margin: 0; color: var(--life-muted); }
.xiaoc-life-control--compact :deep(.el-slider) {
  --el-slider-height: 4px;
  --el-slider-button-size: 14px;
  --el-slider-main-bg-color: var(--life-accent);
  --el-slider-runway-bg-color: var(--life-track);
  --el-slider-stop-bg-color: var(--life-track);
  --el-slider-border-radius: 999px;
  box-sizing: border-box;
  width: auto;
  min-height: 36px;
  margin: 0 10px 16px;
  touch-action: pan-y;
}
.xiaoc-life-control--compact :deep(.el-slider__button) {
  background: var(--life-accent);
  border: 2px solid var(--life-surface);
  box-shadow: 0 0 0 1px var(--life-accent), 0 2px 5px #0002;
  transition: transform var(--wb-transition-normal, var(--xc-token-motion-standard-ms) ease-out), box-shadow var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease);
}
.xiaoc-life-control--compact :deep(.el-slider:not(.is-disabled) .el-slider__button-wrapper:hover .el-slider__button) {
  transform: scale(1.10);
}
.xiaoc-life-control--compact :deep(.el-slider:not(.is-disabled) .el-slider__button-wrapper.dragging .el-slider__button) {
  transform: scale(1.16);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--life-accent) 18%, transparent);
}
.xiaoc-life-control--compact :deep(.el-slider__button-wrapper:focus-visible) { outline: 2px solid var(--life-accent); outline-offset: 1px; border-radius: 50%; }
.xiaoc-life-control--compact :deep(.el-slider__stop) { width: 4px; height: 4px; background: var(--life-muted); opacity: .6; }
.xiaoc-life-control--compact :deep(.el-slider__marks-text) {
  color: var(--life-muted);
  font-size: 0.68rem;
  font-variant-numeric: tabular-nums;
  transition: color var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease);
}
.xiaoc-life-control--compact :deep([data-autonomy-preview="1"] .el-slider__marks-text:nth-child(1)),
.xiaoc-life-control--compact :deep([data-autonomy-preview="2"] .el-slider__marks-text:nth-child(2)),
.xiaoc-life-control--compact :deep([data-autonomy-preview="3"] .el-slider__marks-text:nth-child(3)),
.xiaoc-life-control--compact :deep([data-autonomy-preview="4"] .el-slider__marks-text:nth-child(4)),
.xiaoc-life-control--compact :deep([data-autonomy-preview="5"] .el-slider__marks-text:nth-child(5)),
.xiaoc-life-control--compact :deep([data-autonomy-preview="6"] .el-slider__marks-text:nth-child(6)) {
  color: var(--life-fg);
  font-weight: 600;
}
@supports selector(:has(*)) {
  /* Follow the pointer directly; ease only discrete clicks and keyboard changes. */
  .xiaoc-life-control--compact :deep(.el-slider:not(:has(.el-slider__button-wrapper.dragging)) .el-slider__button-wrapper) {
    transition: left var(--wb-transition-normal, var(--xc-token-motion-standard-ms) ease-out);
  }
  .xiaoc-life-control--compact :deep(.el-slider:not(:has(.el-slider__button-wrapper.dragging)) .el-slider__bar) {
    transition: width var(--wb-transition-normal, var(--xc-token-motion-standard-ms) ease-out);
  }
}
.xiaoc-life-control__preview {
  display: grid;
  grid-template-rows: auto minmax(2.8em, auto) auto;
  gap: 3px;
  min-width: 0;
  color: var(--life-muted);
}
.xiaoc-life-control__preview strong { color: var(--life-fg); font-size: .98rem; font-weight: 600; letter-spacing: -.015em; }
.xiaoc-life-control__applied { color: var(--life-muted); font-size: .68rem; }
.xiaoc-life-control--compact .xiaoc-life-control__foot { gap: 8px; font-size: 0.72rem; }
.xiaoc-life-control--compact .xiaoc-life-control__foot > span { white-space: normal; overflow-wrap: anywhere; }
.xiaoc-life-control--compact button {
  padding: 4px 6px;
  border-radius: 6px;
  text-decoration: none;
  transition: background-color var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease), opacity var(--wb-transition-fast, var(--xc-token-motion-feedback-ms) ease);
}
.xiaoc-life-control--compact button:hover:not(:disabled) { background: var(--life-hover); }
.xiaoc-life-control--compact button:focus-visible { outline: 2px solid var(--life-accent); outline-offset: 1px; }
.xiaoc-life-control__confirm {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
  padding-top: 10px;
  border-top: 1px solid var(--life-border);
}
.xiaoc-life-control__confirm span { flex: 1; color: var(--life-muted); font-size: 0.68rem; }
.xiaoc-life-control__confirm button {
  flex-shrink: 0;
  padding: 6px 10px;
  background: var(--life-accent);
  color: var(--life-button-fg);
  font-weight: 500;
}
.xiaoc-life-control__confirm button:hover:not(:disabled) { background: var(--life-accent); opacity: 0.88; }
.xiaoc-life-control__confirm button:disabled { background: var(--life-track); color: var(--life-muted); opacity: 0.7; }
@media (pointer: coarse) {
  .xiaoc-life-disclosure__trigger { min-height: 44px; }
  .xiaoc-life-control--compact button { min-height: 44px; min-width: 44px; }
  .xiaoc-life-control--compact :deep(.el-slider) { min-height: 44px; }
  .xiaoc-life-control--compact :deep(.el-slider__button-wrapper) { width: 44px; height: 44px; top: -20px; }
}
@media (prefers-reduced-motion: reduce) {
  .xiaoc-life-disclosure__trigger, .xiaoc-life-disclosure__trigger svg,
  .xiaoc-life-control--compact, .xiaoc-life-control--compact button,
  .xiaoc-life-control--compact :deep(.el-slider__button),
  .xiaoc-life-control--compact :deep(.el-slider__button-wrapper),
  .xiaoc-life-control--compact :deep(.el-slider__bar),
  .xiaoc-life-control--compact :deep(.el-slider__marks-text) { transition: none !important; }
  .xiaoc-life-disclosure__trigger:active,
  .xiaoc-life-control--compact :deep(.el-slider .el-slider__button-wrapper:hover .el-slider__button),
  .xiaoc-life-control--compact :deep(.el-slider .el-slider__button-wrapper.dragging .el-slider__button) { transform: none !important; }
  :global(.xiaoc-autonomy-motion-enter-active),
  :global(.xiaoc-autonomy-motion-leave-active),
  :global(.xiaoc-autonomy-motion-enter-active .xiaoc-life-control--compact),
  :global(.xiaoc-autonomy-motion-leave-active .xiaoc-life-control--compact) { transition: none !important; }
  :global(.xiaoc-autonomy-motion-enter-from .xiaoc-life-control--compact),
  :global(.xiaoc-autonomy-motion-leave-to .xiaoc-life-control--compact) { transform: none; }
}
</style>
