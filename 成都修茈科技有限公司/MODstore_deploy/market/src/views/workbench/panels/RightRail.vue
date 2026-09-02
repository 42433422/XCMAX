<script setup lang="ts">
import { inject, ref, type Ref } from 'vue'
import { DEFAULT_MODULE_ORDER, MODULE_META } from '../../../composables/useWorkbenchManifest'
import { useWorkbenchStore } from '../../../stores/workbench'
import { useFieldAi } from '../../../composables/useFieldAi'
import { useManifestDiff } from '../../../composables/useManifestDiff'
import { useRightRailFields } from '../../../composables/useRightRailFields'
import { useRightRailLlmCatalog } from '../../../composables/useRightRailLlmCatalog'
import { useRightRailActions } from '../../../composables/useRightRailActions'
import { useRightRailPublish } from '../../../composables/useRightRailPublish'
import RightRailInspectorPane from './right-rail/RightRailInspectorPane.vue'
import RightRailPublishPane from './right-rail/RightRailPublishPane.vue'

const store = useWorkbenchStore()
const fieldAi = useFieldAi()
const manifestDiff = useManifestDiff()

/** 嵌入模式下顶栏隐藏，由 Run 面板等处调用同一套保存逻辑 */
const injectSaveEmployee = inject<(() => Promise<void>) | undefined>('workbenchSaveEmployee', undefined)
/** 无 Provider 时占位，避免嵌入外误显保存按钮时禁用状态异常 */
const injectSaving = inject<Ref<boolean>>('workbenchSaving', ref(false))
const injectSaveMsg = inject<Ref<string>>('workbenchSaveMsg', ref(''))

// ── 域逻辑（自原 script 按域原样迁移至 composables，状态仍常驻本组件作用域） ──

const fields = useRightRailFields({ store })

const llm = useRightRailLlmCatalog({
  modelProvider: fields.modelProvider,
  modelName: fields.modelName,
  selectedNodeData: fields.selectedNodeData,
})

const actions = useRightRailActions({
  store,
  fieldAi,
  manifest: fields.manifest,
  getPath: fields.getPath,
  setPath: fields.setPath,
  systemPrompt: fields.systemPrompt,
  roleName: fields.roleName,
})

const publish = useRightRailPublish({ store, runResult: actions.runResult })

const { mode, selectedNodeData } = fields
const { runInput, runResult, runLoading, runEmployee, presentModuleKinds, addModule, dragModuleStart } = actions

// ── 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定，需在 setup 顶层保留同名绑定 ──
/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定 */
const { identityName, temperature, modelProvider } = fields
const {
  refreshWorkbenchLlmCatalog, catalogProviderPickerRows, employeeHasStructuredModels,
  employeeCategoryLabel, employeeModelsForCategory, employeeModelOptionLabel,
  onEmployeeLlmProviderPicked,
} = llm
const { refinePrompt, refineResult, applyRefine, researchBrief, fetchResearch, previewTts } = actions
const {
  publishState, publishError, benchResult, auditAnimPhase,
  startBenchTest, publishEmployee, downloadPack,
  syncState, syncError, syncCurrentStep, syncElapsedSec, syncStepMeta,
  syncStepFromElapsed, syncRoughOverallPct, startSyncTest,
} = publish
/* eslint-enable @typescript-eslint/no-unused-vars */

// ── 变更对比面板的值格式化（纯展示函数） ────────────────────────────────────

function formatDiffVal(val: unknown): string {
  if (val === undefined || val === null || val === '') return '(空)'
  if (typeof val === 'string') {
    return val.length > 120 ? val.slice(0, 120) + '…' : val
  }
  return JSON.stringify(val)
}
</script>

<template>
  <div class="right-rail">
    <!-- Mode tabs -->
    <div class="rr-tabs">
      <button
        class="rr-tab"
        :class="{ 'rr-tab--active': mode === 'node' }"
        :disabled="!store.selectedNode"
        @click="store.inspectorMode = 'node'"
      >
        属性
      </button>
      <button
        class="rr-tab"
        :class="{ 'rr-tab--active': mode === 'library' }"
        @click="store.inspectorMode = 'library'"
      >
        模块库
      </button>
      <button
        class="rr-tab"
        :class="{ 'rr-tab--active': mode === 'run' }"
        @click="store.inspectorMode = 'run'"
      >
        运行
      </button>
      <button
        class="rr-tab rr-tab--publish"
        :class="{ 'rr-tab--active': mode === 'publish' }"
        @click="store.inspectorMode = 'publish'"
      >
        上架
      </button>
      <button
        v-if="manifestDiff.hasBaseline.value"
        class="rr-tab rr-tab--diff"
        :class="{ 'rr-tab--active': mode === 'diff' }"
        @click="store.inspectorMode = 'diff'"
      >
        变更
        <span v-if="manifestDiff.diffCount.value > 0" class="rr-diff-badge">
          {{ manifestDiff.diffCount.value }}
        </span>
      </button>
    </div>

    <!-- ── Inspector (node selected) ─────────────────────────────── -->
    <RightRailInspectorPane
      v-if="mode === 'node' && selectedNodeData"
      :fields="fields"
      :llm="llm"
      :actions="actions"
    />

    <!-- ── No node selected + library ────────────────────────────── -->
    <div v-else-if="mode === 'library'" class="rr-pane library-pane">
      <p class="library-title">模块库</p>
      <p class="library-sub">拖放模块到画布，或点击添加</p>
      <div class="library-grid">
        <div
          v-for="kind in DEFAULT_MODULE_ORDER"
          :key="kind"
          class="library-item"
          :class="{ 'library-item--present': presentModuleKinds.has(kind) }"
          :draggable="!presentModuleKinds.has(kind)"
          @dragstart="(e) => dragModuleStart(kind, e)"
          @click="() => !presentModuleKinds.has(kind) && addModule(kind)"
        >
          <span class="library-item__icon" :style="{ background: MODULE_META[kind].accent }">
            {{ MODULE_META[kind].icon }}
          </span>
          <div class="library-item__info">
            <span class="library-item__name">{{ MODULE_META[kind].label }}</span>
            <span class="library-item__state">
              {{ presentModuleKinds.has(kind) ? '已添加' : MODULE_META[kind].required ? '必填' : '可拖入' }}
            </span>
          </div>
        </div>
      </div>

      <!-- Dirty indicator -->
      <div v-if="store.dirty" class="dirty-hint">
        ● 有未保存的修改
      </div>
    </div>

    <!-- ── Run panel ─────────────────────────────────────────────── -->
    <div v-else-if="mode === 'run'" class="rr-pane run-pane">
      <p class="run-title">试运行员工</p>
      <p class="run-sub">
        需要先保存员工并获得 ID
        <template v-if="injectSaveEmployee">（嵌入视图请使用下方「保存员工配置」）</template>
      </p>

      <button
        v-if="injectSaveEmployee"
        type="button"
        class="run-btn run-btn--save"
        :disabled="injectSaving"
        @click="() => injectSaveEmployee?.()"
      >
        {{ injectSaving ? '保存中…' : '保存员工配置' }}
      </button>
      <p v-if="injectSaveMsg" class="run-save-msg" :class="{ 'run-save-msg--ok': injectSaveMsg.startsWith('配置') }">
        {{ injectSaveMsg }}
      </p>

      <label class="field-label">任务描述</label>
      <textarea v-model="runInput" class="field-textarea" rows="4" placeholder="描述你想让员工执行的任务…" />

      <button
        class="run-btn"
        :disabled="runLoading || !store.target.id"
        @click="runEmployee"
      >
        {{ runLoading ? '运行中…' : '▶ 执行' }}
      </button>

      <div v-if="!store.target.id" class="run-hint">
        当前员工尚未保存。全屏工作台可用顶部「保存」；此处可点「保存员工配置」，或通过上传打包 / 发布上架获得员工 ID。
      </div>

      <pre v-if="runResult" class="run-result">{{ runResult }}</pre>

      <!-- Current agent run status if present -->
      <div v-if="store.currentRun" class="current-run-summary">
        <p class="field-label">最近一次 Agent 运行</p>
        <span class="agent-run__status" :class="`agent-run__status--${store.currentRun.status}`">
          {{ store.currentRun.status === 'running' ? '运行中' : store.currentRun.status === 'done' ? '完成' : '失败' }}
        </span>
        <p class="run-brief">{{ store.currentRun.brief }}</p>
      </div>
    </div>

    <!-- ── Publish / listing panel ───────────────────────────────── -->
    <RightRailPublishPane
      v-else-if="mode === 'publish'"
      :pub="publish"
      :target-id="store.target.id"
    />

    <!-- Empty state when no node selected in node mode -->
    <div v-else-if="mode === 'node' && !selectedNodeData" class="rr-pane empty-pane">
      <p class="empty-hint">点击画布中的模块节点以编辑属性</p>
    </div>

    <!-- ── Diff panel ─────────────────────────────────────────────── -->
    <div v-else-if="mode === 'diff'" class="rr-pane diff-pane">
      <p class="diff-title">变更对比</p>
      <p class="diff-sub">当前配置与加载时的快照对比</p>

      <div v-if="!manifestDiff.hasDiff.value" class="diff-empty">
        <span class="diff-empty__icon">✓</span>
        <p>与基准版本无差异</p>
      </div>

      <div v-else class="diff-list">
        <div
          v-for="entry in manifestDiff.diffs.value"
          :key="entry.path"
          class="diff-entry"
        >
          <div class="diff-entry__label">{{ entry.label }}</div>
          <div class="diff-entry__row">
            <div class="diff-entry__side diff-entry__side--before">
              <span class="diff-entry__side-tag">原</span>
              <span class="diff-entry__val">{{ formatDiffVal(entry.before) }}</span>
            </div>
            <span class="diff-entry__arrow">→</span>
            <div class="diff-entry__side diff-entry__side--after">
              <span class="diff-entry__side-tag">现</span>
              <span class="diff-entry__val">{{ formatDiffVal(entry.after) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./RightRail.css"></style>
