<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
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
const confirmation = ref<{ owner: number; level: number; revision: number } | null>(null)
let pointerSelecting = false
const triggerRef = ref<HTMLButtonElement | null>(null)
const contentRef = ref<HTMLElement | null>(null)
const marks = { 1: 'L1', 2: 'L2', 3: 'L3', 4: 'L4', 5: 'L5', 6: 'L6' }
const formatLevel = (level: number) => `L${level} · ${xiaocLevelLabels[level] ?? '模式待核实'}`
const label = computed(() =>
  life.state ? formatLevel(life.state.level) : life.loading ? '正在读取自主模式' : '自主模式待核实',
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
const staleConfirmation = computed(() => confirmation.value !== null
  && confirmation.value.revision !== life.state?.revision)
const popoverAttrs = computed(() => ({
  visible: expanded.value,
  placement: 'top-end' as const,
  fallbackPlacements: ['top-start', 'bottom-end', 'bottom-start'],
  width: 216,
  offset: 10,
  showArrow: false,
  teleported: true,
  zIndex: 11060,
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
    if (pointerSelecting) requestConfirmation(value)
    return
  }
  if (value === life.state.level) return
  await life.save({ level: value })
  selection.value = life.state?.level ?? 1
}

function closeCompact(restoreFocus = false) {
  pointerSelecting = false
  expanded.value = false
  selection.value = life.state?.level ?? 1
  if (restoreFocus) triggerRef.value?.focus({ preventScroll: true })
}
function toggleCompact() {
  if (confirmation.value) return
  if (expanded.value) closeCompact()
  else {
    if (life.error) void life.refresh()
    selection.value = life.state?.level ?? 1
    expanded.value = true
  }
}
function insideCompact(event: Event) {
  const path = event.composedPath()
  return [triggerRef.value, contentRef.value].some(element => element !== null && path.includes(element))
}
function onOutside(event: Event) {
  if (!expanded.value) return
  if (insideCompact(event)) {
    if (event.type === 'pointerdown' && contentRef.value && event.composedPath().includes(contentRef.value)) {
      pointerSelecting = true
    }
    return
  }
  // The panel is non-modal: do not steal focus from the next target.
  closeCompact()
}
function onTouchRelease(event: PointerEvent) {
  if (!pointerSelecting || event.pointerType !== 'touch') return
  pointerSelecting = false
  if (event.type === 'pointercancel') {
    selection.value = life.state?.level ?? 1
    return
  }
  // A track tap can update the Element Plus model before the touch ends
  // without a corresponding slider change event.
  requestAnimationFrame(() => requestConfirmation(selection.value))
}
function onCompactKey(event: KeyboardEvent) {
  if (!expanded.value || event.defaultPrevented || !insideCompact(event)) return
  pointerSelecting = false
  if (event.key === 'Enter' && event.target instanceof Element && event.target.matches('[role="slider"]')) {
    event.preventDefault()
    requestConfirmation(selection.value)
    return
  }
  if (event.key !== 'Escape') return
  event.stopPropagation()
  event.preventDefault()
  closeCompact(true)
}
function openLife() {
  emit('open-life')
}
function focusContent() {
  const content = contentRef.value
  if (!expanded.value || !content || content.contains(document.activeElement)) return
  const target = content.querySelector<HTMLElement>('[role="slider"]') ?? content
  target.focus({ preventScroll: true })
}
onMounted(() => {
  document.addEventListener('pointerdown', onOutside, true)
  document.addEventListener('pointerup', onTouchRelease, true)
  document.addEventListener('pointercancel', onTouchRelease, true)
  document.addEventListener('focusin', onOutside, true)
  document.addEventListener('keydown', onCompactKey, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onOutside, true)
  document.removeEventListener('pointerup', onTouchRelease, true)
  document.removeEventListener('pointercancel', onTouchRelease, true)
  document.removeEventListener('focusin', onOutside, true)
  document.removeEventListener('keydown', onCompactKey, true)
})
watch(() => props.owner, () => {
  closeCompact()
  confirmation.value = null
})
watch(() => props.compact, (compact) => {
  if (compact) return
  closeCompact()
  confirmation.value = null
})

function requestConfirmation(level: number) {
  const state = life.state
  if (!props.compact || !expanded.value || !state || level === state.level || life.error || life.saving) return
  closeCompact()
  confirmation.value = { owner: props.owner, level, revision: state.revision }
}

async function applyLevel() {
  const pending = confirmation.value
  if (!pending || pending.owner !== props.owner || staleConfirmation.value) return
  const saved = await life.save({ level: pending.level }, pending.revision)
  if (saved && confirmation.value === pending) confirmation.value = null
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
    :title="compact && life.error ? life.error : undefined"
  >
    <strong v-if="compact" class="xiaoc-life-control__value" aria-hidden="true">
      {{ life.state ? formatLevel(selection) : label }}
    </strong>
    <div v-else class="xiaoc-life-control__head">
      <strong>{{ label }}</strong>
      <span>全企业生效</span>
    </div>
    <ElSlider
      :model-value="selection"
      :min="1"
      :max="6"
      :step="1"
      :marks="compact ? undefined : marks"
      show-stops
      :show-tooltip="!compact"
      :disabled="!life.state || life.saving || !!life.error"
      :format-tooltip="formatLevel"
      :format-value-text="formatLevel"
      v-bind="{ ariaLabel: '小 C 全企业自主等级' }"
      @update:model-value="selectLevel"
      @change="changeLevel"
    />
    <div v-if="!compact && life.error" class="xiaoc-life-control__error" role="alert">
      {{ life.error }} <button type="button" :disabled="life.loading || life.saving" @click="life.refresh()">刷新</button>
    </div>
    <template v-if="!compact">
      <div class="xiaoc-life-control__foot">
        <span role="status">{{ life.error || life.state ? activity : '尚未读取运行状态' }}</span>
        <button type="button" @click="openLife">目标与预算</button>
      </div>
      <div v-if="life.state" class="xiaoc-life-control__actions">
        <button v-if="life.state.stopped" type="button" :disabled="life.saving || !!life.error" @click="life.save({ stopped: false, paused: false })">启动自主活动</button>
        <template v-else>
          <button type="button" :disabled="life.saving || !!life.error" @click="life.save({ paused: !life.state.paused })">{{ life.state.paused ? '恢复自主活动' : '暂停自主活动' }}</button>
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
      <div v-if="life.state?.blockers.length" class="xiaoc-life-control__error" role="status">{{ life.state.blockers.join('；') }}</div>
    </template>
  </section>
  </component>
  <ElDialog
    v-if="compact"
    :model-value="confirmation !== null"
    title="切换自主任务档位"
    width="min(350px, calc(100vw - 24px))"
    :z-index="12120"
    append-to-body
    :close-on-click-modal="false"
    :close-on-press-escape="!life.saving"
    :show-close="!life.saving"
    @update:model-value="confirmation = null"
    @closed="triggerRef?.focus({ preventScroll: true })"
  >
    <p v-if="confirmation">将全企业切换至 {{ formatLevel(confirmation.level) }}。</p>
    <p v-if="staleConfirmation || life.error" role="alert">{{ life.error || '档位已更新，请重新选择。' }}</p>
    <template #footer>
      <ElButton :disabled="life.saving" @click="confirmation = null">取消</ElButton>
      <ElButton type="primary" :loading="life.saving" :disabled="!!life.error || staleConfirmation" @click="applyLevel">确认切换</ElButton>
    </template>
  </ElDialog>
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
.xiaoc-life-control__head > span { color: var(--life-muted); font-size: 0.7rem; }
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
  box-sizing: border-box;
  width: 100%;
  padding: 8px 12px 2px;
  border: 1px solid var(--life-border);
  border-radius: 14px;
  background: var(--life-surface);
  box-shadow: 0 2px 6px #0002, 0 12px 32px #0004;
  transform-origin: bottom right;
}
.xiaoc-life-control--compact.xiaoc-life-control--light {
  --life-fg: #34312b;
  --life-muted: #665f55;
  --life-border: #e8e4dc;
  --life-error: #8a311d;
  --life-surface: #fdfcf9;
  --life-accent: #9a7353;
  --life-track: #e6e0d6;
  box-shadow: 0 2px 6px #29201808, 0 12px 32px #29201816;
}
.xiaoc-life-control--compact:focus { outline: none; }
.xiaoc-life-control__value {
  display: block;
  text-align: center;
  font-size: 0.8125rem;
  font-weight: 600;
}
.xiaoc-life-control--compact :deep(.el-slider) {
  --el-slider-height: 10px;
  --el-slider-button-size: 18px;
  --el-slider-button-wrapper-offset: -13px;
  --el-slider-main-bg-color: var(--life-accent);
  --el-slider-runway-bg-color: var(--life-track);
  --el-slider-border-radius: 999px;
  width: auto;
  min-height: 32px;
  margin: 0 8px;
  touch-action: pan-y;
}
.xiaoc-life-control--compact :deep(.el-slider__button) {
  background: #fff9ed;
  border: 1px solid var(--life-accent);
  box-shadow: 0 1px 4px #0004;
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
.xiaoc-life-control--compact :deep(.el-slider__stop) {
  width: 3px;
  height: 3px;
  top: 50%;
  transform: translate(-50%, -50%);
  background: var(--life-fg);
  opacity: 0.65;
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
@media (pointer: coarse) {
  .xiaoc-life-disclosure__trigger { min-height: 44px; }
  .xiaoc-life-control--compact :deep(.el-slider) {
    --el-slider-button-wrapper-size: 44px;
    --el-slider-button-wrapper-offset: -17px;
    min-height: 44px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .xiaoc-life-disclosure__trigger, .xiaoc-life-disclosure__trigger svg,
  .xiaoc-life-control--compact,
  .xiaoc-life-control--compact :deep(.el-slider__button),
  .xiaoc-life-control--compact :deep(.el-slider__button-wrapper),
  .xiaoc-life-control--compact :deep(.el-slider__bar) { transition: none !important; }
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
