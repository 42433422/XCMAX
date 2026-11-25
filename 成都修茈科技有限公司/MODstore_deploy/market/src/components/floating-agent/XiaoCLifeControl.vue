<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElSlider } from 'element-plus/es/components/slider/index'
import './xiaocLife.css'
import { xiaocLevelLabels, xiaocStateLabel } from '../../application/xiaocLifeApi'
import { useXiaoCLife } from '../../composables/useXiaoCLife'

const props = defineProps<{ owner: number; light?: boolean; compact?: boolean }>()
defineEmits<{ (e: 'open-life'): void }>()
const life = useXiaoCLife(() => props.owner)
const selection = ref(1)
const disclosure = ref<HTMLElement | null>(null)
const marks = { 1: 'L1', 2: 'L2', 3: 'L3', 4: 'L4', 5: 'L5', 6: 'L6' }
const label = computed(() =>
  life.state ? `L${life.state.level} · ${xiaocLevelLabels[life.state.level] ?? '模式待核实'}` : '正在读取自主模式',
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
const compactLabel = computed(() =>
  life.error ? '自治待核实' : life.state ? (xiaocLevelLabels[life.state.level] ?? '模式待核实') : '读取自治…',
)
const canApply = computed(() => !!life.state && !life.saving && !life.error && selection.value !== life.state.level)
watch(
  [() => life.state?.level, () => life.state?.revision, () => props.owner],
  ([level]) => { selection.value = level ?? 1 },
  { immediate: true },
)
function selectLevel(value: number | number[]) {
  if (typeof value === 'number') selection.value = value
}

async function changeLevel(value: number | number[]) {
  if (typeof value !== 'number' || !life.state) return
  if (props.compact) {
    selection.value = value
    return
  }
  if (value === life.state.level) return
  await life.save({ level: value })
  selection.value = life.state?.level ?? 1
}

function closeCompact() {
  if (!(disclosure.value instanceof HTMLDetailsElement)) return
  disclosure.value.open = false
  selection.value = life.state?.level ?? 1
}
function onToggle() {
  if (disclosure.value instanceof HTMLDetailsElement && !disclosure.value.open) {
    selection.value = life.state?.level ?? 1
  }
}
function onEscape(event: KeyboardEvent) {
  if (!(disclosure.value instanceof HTMLDetailsElement) || !disclosure.value.open) return
  event.stopPropagation()
  closeCompact()
  disclosure.value.querySelector('summary')?.focus()
}
function onFocusOut(event: FocusEvent) {
  if (event.relatedTarget instanceof Node && !disclosure.value?.contains(event.relatedTarget)) closeCompact()
}
async function applyLevel() {
  const state = life.state
  if (!state || !canApply.value) return
  const saved = await life.save({ level: selection.value }, state.revision)
  selection.value = life.state?.level ?? 1
  if (saved) {
    closeCompact()
    disclosure.value?.querySelector('summary')?.focus()
  }
}
</script>

<template>
  <component
    :is="compact ? 'details' : 'div'"
    ref="disclosure"
    :class="{ 'xiaoc-life-disclosure': compact, 'xiaoc-life-disclosure--light': light }"
    @toggle="onToggle"
    @keydown.esc="onEscape"
    @focusout="onFocusOut"
  >
    <summary v-if="compact" class="xiaoc-life-disclosure__trigger" :title="'全企业自治设置：' + compactLabel">
      <span>{{ compactLabel }}</span>
      <svg viewBox="0 0 12 12" width="12" height="12" fill="none" aria-hidden="true">
        <path d="m3 4.5 3 3 3-3" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.4" />
      </svg>
    </summary>
  <section
    class="xiaoc-life-control"
    v-bind="{ 'data-xiaoc-control-plane': '' }"
    :class="{ 'xiaoc-life-control--light': light, 'xiaoc-life-control--compact': compact }"
    aria-label="企业小 C 自主模式"
    :aria-busy="life.loading || life.saving"
  >
    <div class="xiaoc-life-control__head">
      <strong>{{ label }}</strong>
      <span>全企业生效</span>
      <button v-if="life.state?.stopped" type="button" :disabled="life.saving" @click="life.save({ stopped: false, paused: false })">
        启动自主活动
      </button>
      <template v-else-if="life.state">
        <button type="button" :disabled="life.saving" @click="life.save({ paused: !life.state.paused })">
          {{ life.state.paused ? '恢复自主活动' : '暂停自主活动' }}
        </button>
        <button type="button" :disabled="life.saving" @click="life.save({ stopped: true })">停止自主活动</button>
      </template>
    </div>
    <ElSlider
      :model-value="selection"
      :min="1"
      :max="6"
      :step="1"
      :marks="marks"
      show-stops
      :disabled="!life.state || life.saving || (compact && !!life.error)"
      :format-tooltip="(value: number) => `L${value} · ${xiaocLevelLabels[value]}`"
      v-bind="{ ariaLabel: '小 C 全企业自主等级' }"
      @update:model-value="selectLevel"
      @change="changeLevel"
    />
    <div v-if="compact" class="xiaoc-life-control__confirm">
      <span>切换影响全企业；不会授予额外预算或权限。</span>
      <button type="button" :disabled="!canApply" @click="applyLevel">确认切换</button>
    </div>
    <div class="xiaoc-life-control__foot">
      <span role="status">{{ life.state ? activity : '尚未读取运行状态' }}</span>
      <button type="button" @click="$emit('open-life')">目标与预算</button>
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
  </section>
  </component>
</template>

<style scoped>
.xiaoc-life-disclosure {
  position: relative;
  flex: 0 0 auto;
  color: #aeb9ca;
  font-size: 0.75rem;
}
.xiaoc-life-disclosure--light { color: #46556b; }
.xiaoc-life-disclosure__trigger {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 8px 5px;
  cursor: pointer;
  list-style: none;
  white-space: nowrap;
}
.xiaoc-life-disclosure__trigger::-webkit-details-marker { display: none; }
.xiaoc-life-disclosure__trigger:focus-visible { outline: 2px solid currentColor; border-radius: 6px; }
.xiaoc-life-disclosure[open] .xiaoc-life-disclosure__trigger svg { transform: rotate(180deg); }
.xiaoc-life-disclosure .xiaoc-life-control--compact {
  position: absolute;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 30;
  width: min(270px, calc(100vw - 72px));
  max-height: min(320px, 55vh);
  overflow-y: auto;
  box-sizing: border-box;
  border: 1px solid var(--life-border);
  border-radius: 12px;
  padding: 12px 14px;
  background: #202632;
  box-shadow: 0 8px 24px #0003;
}
.xiaoc-life-disclosure--light .xiaoc-life-control--compact { background: #fff; }
.xiaoc-life-control__confirm { display: flex; gap: 8px; align-items: center; margin: 0 0 8px; }
.xiaoc-life-control__confirm span { flex: 1; color: var(--life-muted); }
.xiaoc-life-control__confirm button { flex-shrink: 0; }
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
.xiaoc-life-control__foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.xiaoc-life-control__head > span {
  color: var(--life-muted);
  font-size: 0.7rem;
}
.xiaoc-life-control__head button,
.xiaoc-life-control__foot button {
  margin-left: auto;
  flex-shrink: 0;
}
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
.xiaoc-life-control button:disabled {
  cursor: default;
  opacity: 0.5;
}
.xiaoc-life-control__error {
  color: var(--life-error);
  margin-top: 6px;
}
</style>
