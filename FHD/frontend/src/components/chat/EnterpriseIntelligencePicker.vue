<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import { create, PipsMode, type API } from 'nouislider'
import 'nouislider/dist/nouislider.css'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch, DEFAULT_MOD_API_TIMEOUT_MS } from '@/utils/apiBase'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

type Snapshot = { owner_id: string; editable: boolean; level: number | null; revision: number }
const levels = ['辅助智能', '执行智能', '工作智能', '自治智能', '进化智能', '经营智能']
const descriptions = ['对话、分析与建议', '执行明确的任务，并主动建议下一步', '完成多步骤工作', '持续承担职责', '基于经验改进', '分析与推进经营目标']
const profile = useAccountProfileStore()
const owner = computed(() => profile.loaded && profile.tenantId && !profile.isAdminAccount && !profile.isImpersonating &&
  (profile.accountKind === 'enterprise' || profile.userRole.startsWith('tenant:')) ? `tenant:${profile.tenantId}` : '')
const snapshot = ref<Snapshot | null>(null)
const level = computed(() => snapshot.value?.level ?? null)
defineExpose({ level })
const saving = ref(false)
const error = ref('')
const open = ref(false)
const track = ref<HTMLElement | null>(null)
const slider = shallowRef<API | null>(null)
const preview = ref(1)
const editable = computed(() => snapshot.value?.editable === true && !saving.value)
const label = computed(() => level.value ? `L${level.value} · ${levels[level.value - 1]}` : '智能等级')
const endpoint = '/api/workspace/intelligence'
async function reload() {
  const scope = owner.value
  const epoch = productReadAccountEpoch.value
  snapshot.value = null
  error.value = ''
  if (!scope) return
  try {
    const response = await apiFetch(endpoint, { cache: 'no-store', timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS })
    if (!response.ok) throw new Error(String(response.status))
    const state = await response.json() as Snapshot
    if (state.owner_id !== scope) throw new Error('owner_changed')
    if (epoch === productReadAccountEpoch.value && owner.value === scope) snapshot.value = state
  } catch {
    if (epoch === productReadAccountEpoch.value && owner.value === scope) error.value = '企业智能等级读取失败'
  }
}

async function selectLevel(level: number) {
  const current = snapshot.value
  if (!current?.editable || saving.value || current.level === level || owner.value !== current.owner_id) return
  const epoch = productReadAccountEpoch.value
  const stillCurrent = () => epoch === productReadAccountEpoch.value && owner.value === current.owner_id
  saving.value = true
  error.value = ''
  try {
    const response = await apiFetch(endpoint, {
      method: 'PUT',
      timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level, expected_owner_id: current.owner_id, expected_revision: current.revision }),
    })
    if (!response.ok) throw new Error(String(response.status))
    const saved = await response.json() as Snapshot
    if (saved.owner_id !== current.owner_id || saved.level !== level || saved.revision !== current.revision + 1) {
      throw new Error('receipt_mismatch')
    }
    if (stillCurrent()) {
      snapshot.value = saved
    }
  } catch {
    if (!stillCurrent()) return
    await reload()
    if (stillCurrent() && snapshot.value?.level !== level) error.value ||= '档位未确认，请按当前显示重新选择'
  } finally {
    if (stillCurrent()) saving.value = false
  }
}

watch([owner, productReadAccountEpoch], () => {
  open.value = false
  saving.value = false
  void reload()
}, { immediate: true, flush: 'sync' })

watch(track, (target, _, onCleanup) => {
  if (!target) return
  const start = level.value ?? 1
  target.style.setProperty('--level-progress', String((start - 1) / (levels.length - 1)))
  const instance = create(target, {
    start,
    range: { min: 1, max: levels.length },
    step: 1,
    behaviour: 'tap-smooth-steps',
    animationDuration: 260,
    handleAttributes: [{ 'aria-label': '企业智能等级' }],
    ariaFormat: { to: value => `L${Math.round(value)} ${levels[Math.round(value) - 1]}` },
    pips: { mode: PipsMode.Steps, density: 20, format: { to: value => `L${value}` } },
  })
  const pips = target.querySelectorAll<HTMLElement>('.noUi-value')
  instance.on('update', (_values, handle, raw, _tap, positions) => {
    target.style.setProperty('--level-progress', String(positions[handle] / 100))
    preview.value = Math.round(raw[handle])
    for (const pip of pips) {
      pip.classList.toggle('enterprise-level-pip-selected', Number(pip.dataset.value) === preview.value)
    }
  })
  // noUiSlider's change event fires on release, taps and keyboard commits.
  instance.on('change', (_values, handle, raw) => { void selectLevel(Math.round(raw[handle])) })
  slider.value = instance
  onCleanup(() => {
    instance.destroy()
    slider.value = null
  })
}, { flush: 'post' })

watch([slider, level, editable], () => {
  const instance = slider.value
  if (!instance) return
  if (editable.value) instance.enable()
  else instance.disable()
  if (!saving.value && Math.round(Number(instance.get(true))) !== (level.value ?? 1)) instance.set(level.value ?? 1)
}, { flush: 'post' })
</script>

<template>
  <template v-if="owner">
    <PopoverRoot v-model:open="open">
      <PopoverTrigger as-child>
        <button type="button" class="enterprise-level-trigger" :disabled="!snapshot" :aria-label="`本企业智能等级 ${label}`">
          <span class="enterprise-level-meter" aria-hidden="true">
            <i v-for="(_, index) in levels" :key="index" :style="{ height: `${3 + index * 2}px` }" :data-filled="index < (level ?? 0)"></i>
          </span>
          {{ label }}
          <i class="fa fa-chevron-down enterprise-level-chevron" aria-hidden="true"></i>
        </button>
      </PopoverTrigger>
      <PopoverPortal>
        <PopoverContent style="z-index: 2200" side="top" align="end" :side-offset="12" :collision-padding="16" aria-label="企业智能等级">
          <div class="enterprise-level-panel" :data-readonly="!snapshot?.editable">
            <header class="enterprise-level-heading">
              <span>企业智能等级</span>
              <div class="enterprise-level-preview">
                <Transition name="level-preview">
                  <div :key="preview">
                    <strong>{{ levels[preview - 1] }}</strong>
                    <p>{{ descriptions[preview - 1] }}</p>
                  </div>
                </Transition>
              </div>
            </header>
            <div
              ref="track"
              class="enterprise-level-track"
              :data-level="preview"
              :data-pulsing="preview >= 3 || undefined"
            ></div>
            <p class="enterprise-level-status" role="status">
              <template v-if="error">{{ error }}</template>
              <template v-else-if="saving">正在保存…</template>
              <template v-else-if="!snapshot?.editable">仅企业主账号可修改</template>
              <template v-else-if="preview > 3">本环境未启用高阶自治运行</template>
            </p>
            <button v-if="level === null && editable" type="button" class="btn btn-sm btn-secondary" @click="selectLevel(preview)">应用 L{{ preview }}</button>
          </div>
        </PopoverContent>
      </PopoverPortal>
    </PopoverRoot>
    <button v-if="error && !open" type="button" class="toolbar-btn" @click="reload">重读智能等级</button>
  </template>
</template>

<style scoped>
.enterprise-level-trigger {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding-inline: 9px;
  border: 0;
  border-radius: var(--xc-radius-md);
  background: transparent;
  color: var(--xc-color-text);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 160ms ease, color 160ms ease;
}
.enterprise-level-trigger:hover:not(:disabled),
.enterprise-level-trigger[data-state='open'] { background: var(--xc-color-surface-3); }
.enterprise-level-trigger:disabled { cursor: default; opacity: .65; }
.enterprise-level-chevron {
  color: var(--xc-color-muted);
  font-size: 8px;
  transition: transform 180ms ease;
}
.enterprise-level-trigger[data-state='open'] .enterprise-level-chevron { transform: rotate(180deg); }
.enterprise-level-meter { display: inline-flex; align-items: end; gap: 1.5px; }
.enterprise-level-meter i {
  width: 2px;
  border-radius: 2px;
  background: var(--xc-color-border-strong);
  transition: background-color 200ms ease;
}
.enterprise-level-meter i[data-filled='true'] { background: var(--xc-color-primary); }

.enterprise-level-panel {
  width: min(322px, calc(100vw - 32px));
  padding: 16px 16px 5px;
  border: 1px solid var(--xc-color-border);
  border-radius: var(--xc-radius-xl);
  background: var(--xc-color-surface);
  box-shadow: var(--xc-shadow-xs), var(--xc-shadow-lg);
  transform-origin: var(--reka-popover-content-transform-origin);
  animation: level-panel-in 150ms ease-out;
}
.enterprise-level-heading { padding-inline: 3px; }
.enterprise-level-heading > span { color: var(--xc-color-text-secondary); font-size: 11px; }
.enterprise-level-preview { display: grid; min-height: 49px; }
.enterprise-level-preview > div { grid-area: 1 / 1; align-self: start; }
.enterprise-level-preview strong { display: block; color: var(--xc-color-text); font-size: 17px; font-weight: 650; }
.enterprise-level-preview p,
.enterprise-level-status { margin: 0; color: var(--xc-color-text-secondary); font-size: 12px; }
.enterprise-level-status { min-height: 22px; padding: 3px 3px 0; font-size: 11px; }
.level-preview-enter-active,
.level-preview-leave-active { transition: opacity 100ms ease; }
.level-preview-enter-from,
.level-preview-leave-to { opacity: 0; }

.enterprise-level-track {
  --level-fill: #f3dc85;
  --level-white: var(--xc-token-colors-neutral-light-n00);
  --level-end-gap: calc(100% / 12);
  --level-progress: 0;
  --level-duration: 260ms;
  --level-glide: var(--level-duration) cubic-bezier(.24, .68, .24, 1);
  height: 34px;
  margin-bottom: 20px;
  border: 0;
  border-radius: var(--xc-radius-full);
  background: var(--level-white);
  box-shadow: inset 0 0 0 1px var(--xc-color-border);
  cursor: pointer;
}
.enterprise-level-track:is([data-level='2'], [data-level='3']) { --level-fill: #bf8e10; }
.enterprise-level-track[data-level='4'] { --level-fill: var(--xc-token-desktop-enterprise-xc-color-danger); }
.enterprise-level-track[data-level='5'] { --level-fill: #75bcea; }
.enterprise-level-track[data-level='6'] { --level-fill: var(--xc-token-desktop-enterprise-xc-color-primary); }
.enterprise-level-track::before {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--level-white) 29%, transparent)) var(--level-fill);
  /* Clip the full-width gradient to the thumb so the color stops stay put. */
  clip-path: inset(0 calc((1 - var(--level-progress)) * (100% - 2 * var(--level-end-gap)) + var(--level-end-gap)) 0 0);
  transition: clip-path var(--level-glide), background-color var(--level-duration) ease-out;
  content: '';
  pointer-events: none;
}
.enterprise-level-track[data-pulsing]::before { animation: level-fill-pulse 1.8s ease-in-out infinite; }
.enterprise-level-track :deep(.noUi-base) {
  width: calc(100% - 2 * var(--level-end-gap));
  margin-inline: var(--level-end-gap);
}
.enterprise-level-track :deep(.noUi-base::before) {
  position: absolute;
  inset: 0 -10% -20px;
  content: '';
}
.enterprise-level-track :deep(.noUi-origin) { transition: transform var(--level-glide); }
.enterprise-level-track:has(:deep(.noUi-active))::before { transition-property: background-color; }
.enterprise-level-track:has(:deep(.noUi-active)) :deep(.noUi-origin) { transition: none; }
.enterprise-level-track :deep(.noUi-handle) {
  /* The noUi base spans five segment widths. The capsule occupies one segment minus its gutters. */
  top: 1px;
  right: calc(1px - 10%);
  width: calc(20% - 2px);
  height: 32px;
  border: 0;
  border-radius: var(--xc-radius-full);
  background: var(--level-white);
  box-shadow: inset 0 0 0 .5px var(--xc-color-border), var(--xc-shadow-xs), var(--xc-shadow-sm);
  cursor: grab;
  transition: background-color var(--level-duration) ease-out;
}
/* At L1 the short fill sits under the capsule, so the capsule carries the color. */
.enterprise-level-track[data-level='1'] :deep(.noUi-handle) {
  background-color: color-mix(in srgb, var(--level-fill) 54%, var(--level-white));
}
.enterprise-level-track :deep(.noUi-handle::before),
.enterprise-level-track :deep(.noUi-handle::after),
.enterprise-level-track :deep(.noUi-marker-horizontal) { display: none; }
.enterprise-level-track :deep(.noUi-active) { cursor: grabbing; }
.enterprise-level-track :deep(.noUi-handle:focus-visible),
.enterprise-level-trigger:focus-visible { outline: 2px solid var(--xc-color-primary); outline-offset: 2px; }
.enterprise-level-track :deep(.noUi-pips-horizontal) {
  inset: 100% var(--level-end-gap) auto;
  z-index: 6;
  width: auto;
  height: 20px;
  padding: 0;
  pointer-events: none;
}
.enterprise-level-track :deep(.noUi-value-horizontal) {
  top: 50%;
  transform: translate(-50%, -50%);
  color: var(--xc-color-text-secondary);
  font-size: 11px;
  font-weight: 550;
  font-variant-numeric: tabular-nums;
}
.enterprise-level-track :deep(.enterprise-level-pip-selected) { color: var(--xc-color-primary); font-weight: 700; }
.enterprise-level-panel[data-readonly='true'] .enterprise-level-track,
.enterprise-level-panel[data-readonly='true'] :deep(.noUi-handle) { cursor: default; }

@keyframes level-panel-in {
  from { opacity: 0; transform: translateY(3px); }
  to { opacity: 1; transform: none; }
}
@keyframes level-fill-pulse {
  0%, 100% { filter: brightness(1); }
  42% { filter: brightness(1.22); }
}
@media (prefers-reduced-motion: reduce) {
  .enterprise-level-panel,
  .enterprise-level-track[data-pulsing]::before { animation: none; }
  .enterprise-level-track { --level-duration: 0ms; }
  .enterprise-level-trigger,
  .enterprise-level-chevron,
  .enterprise-level-meter i,
  .level-preview-enter-active,
  .level-preview-leave-active { transition: none; }
}
</style>
