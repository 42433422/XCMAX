<script setup lang="ts">
import { LLM_CATEGORY_ORDER } from '../../../../composables/llmCatalogModelHelpers'
import { MODULE_META } from '../../../../composables/useWorkbenchManifest'
import { AUTO_EMPLOYEE_LLM_SENTINEL } from '../../../../domain/llm/defaultEmployeeLlm'
import { useWorkbenchStore } from '../../../../stores/workbench'
import type { RightRailActionsApi } from '../../../../composables/useRightRailActions'
import type { RightRailFieldsApi } from '../../../../composables/useRightRailFields'
import type { RightRailLlmCatalogApi } from '../../../../composables/useRightRailLlmCatalog'

/**
 * RightRail 属性面板（自 RightRail.vue 原样迁移）。
 * props 传入父级持有的域 API 对象（属性均为稳定 ref / 纯函数），
 * 解构后与父级共享同一 ref 实例，状态常驻父级、跨 tab 切换不丢失。
 */
const props = defineProps<{
  fields: RightRailFieldsApi
  llm: RightRailLlmCatalogApi
  actions: RightRailActionsApi
}>()

const store = useWorkbenchStore()

const {
  selectedNodeData,
  identityName,
  identityId,
  identityVersion,
  identityDesc,
  systemPrompt,
  roleName,
  rolePersona,
  roleTone,
  modelProvider,
  modelName,
  temperature,
  workflowId,
  skills,
  setPath,
} = props.fields

const {
  llmCatalog,
  llmCatalogLoading,
  AUTO_LLM_ROW,
  catalogProviderPickerRows,
  employeeHasStructuredModels,
  employeeCategoryLabel,
  employeeModelsForCategory,
  employeeModelOptionLabel,
  onEmployeeLlmProviderPicked,
  refreshWorkbenchLlmCatalog,
  hasAuthToken,
} = props.llm

const {
  refineInstruction,
  refineResult,
  refineExplanation,
  refineLoading,
  refinePrompt,
  applyRefine,
  researchBrief,
  researchLoading,
  fetchResearch,
  ttsText,
  ttsLoading,
  previewTts,
} = props.actions
</script>

<template>
  <div v-if="selectedNodeData" class="rr-pane inspector-pane">
    <div class="inspector-header">
      <span class="inspector-icon" :style="{ background: selectedNodeData.meta.accent }">
        {{ selectedNodeData.meta.icon }}
      </span>
      <div>
        <div class="inspector-title">{{ selectedNodeData.label }}</div>
        <div class="inspector-sub">{{ selectedNodeData.meta.required ? '必填模块' : '可选模块' }}</div>
      </div>
    </div>

    <!-- Identity fields -->
    <div v-if="selectedNodeData.moduleKind === 'identity'" class="field-group">
      <label class="field-label">员工名称 *</label>
      <input v-model="identityName" class="field-input" placeholder="例如：客服助手" />

      <label class="field-label">员工 ID *</label>
      <input v-model="identityId" class="field-input" placeholder="例如：cs-agent-v1" />

      <label class="field-label">版本</label>
      <input v-model="identityVersion" class="field-input" placeholder="1.0.0" />

      <label class="field-label">描述</label>
      <textarea v-model="identityDesc" class="field-textarea" rows="3" placeholder="一句话描述员工的作用…" />
    </div>

    <!-- Prompt / cognition fields -->
    <div v-else-if="selectedNodeData.moduleKind === 'prompt'" class="field-group">
      <label class="field-label">角色名</label>
      <input v-model="roleName" class="field-input" placeholder="例如：小智" />

      <label class="field-label">人设描述</label>
      <input v-model="rolePersona" class="field-input" placeholder="例如：专业、高效、亲切" />

      <label class="field-label">语气风格</label>
      <select v-model="roleTone" class="field-select">
        <option value="professional">专业</option>
        <option value="formal">正式</option>
        <option value="friendly">友好</option>
        <option value="casual">随意</option>
      </select>

      <label class="field-label">
        System Prompt
        <button class="field-ai-btn" :disabled="refineLoading" @click="refinePrompt">
          {{ refineLoading ? '优化中…' : '✨ AI 优化' }}
        </button>
      </label>
      <textarea v-model="systemPrompt" class="field-textarea" rows="8" placeholder="描述员工的角色、职责、行为准则…" />

      <!-- Refine result preview -->
      <div v-if="refineResult" class="refine-result">
        <p class="refine-result__title">AI 建议（点击应用）</p>
        <p class="refine-result__exp">{{ refineExplanation }}</p>
        <textarea class="field-textarea" rows="5" readonly :value="refineResult" />
        <div class="refine-actions">
          <button class="btn-apply" @click="applyRefine">应用</button>
          <button class="btn-discard" @click="refineResult = ''">放弃</button>
        </div>
      </div>

      <label class="field-label">优化指令</label>
      <input v-model="refineInstruction" class="field-input" placeholder="例如：让语气更友好" />

      <label class="field-label">
        <span>模型（与资金页模型目录一致）</span>
        <button
          type="button"
          class="field-llm-refresh"
          :disabled="llmCatalogLoading"
          title="重新拉取各厂商 /models 缓存"
          @click="refreshWorkbenchLlmCatalog"
        >
          {{ llmCatalogLoading ? '…' : '刷新目录' }}
        </button>
      </label>
      <div class="field-row field-row--model">
        <select
          v-model="modelProvider"
          class="field-select"
          style="flex: 1; min-width: 0"
          :disabled="llmCatalogLoading"
          @change="onEmployeeLlmProviderPicked"
        >
          <option :value="AUTO_EMPLOYEE_LLM_SENTINEL">{{ AUTO_LLM_ROW.label }}</option>
          <option
            v-for="row in catalogProviderPickerRows"
            :key="'llm-prov-' + row.provider"
            :value="row.provider"
          >
            {{ row.label }}
          </option>
        </select>
        <select
          v-if="employeeHasStructuredModels && modelProvider !== AUTO_EMPLOYEE_LLM_SENTINEL"
          v-model="modelName"
          class="field-select field-select--model"
          style="flex: 2; min-width: 0"
        >
          <template v-for="cat in LLM_CATEGORY_ORDER" :key="cat">
            <optgroup v-if="employeeModelsForCategory(cat).length" :label="employeeCategoryLabel(cat)">
              <option v-for="row in employeeModelsForCategory(cat)" :key="row.id" :value="row.id">
                {{ employeeModelOptionLabel(row) }}
              </option>
            </optgroup>
          </template>
        </select>
        <input
          v-else-if="modelProvider !== AUTO_EMPLOYEE_LLM_SENTINEL"
          v-model="modelName"
          class="field-input"
          style="flex: 2; min-width: 0"
          placeholder="model_name（目录未加载或未返回列表时手填）"
        />
        <div
          v-else
          class="field-input field-input--readonly"
          style="flex: 2; min-width: 0; cursor: default"
          title="保存后执行时将按账户默认 LLM 与可用密钥自动解析厂商与模型"
        >
          运行时自动匹配
        </div>
      </div>
      <p v-if="llmCatalogLoading" class="field-hint">正在加载模型目录…</p>
      <p v-else-if="!llmCatalog && hasAuthToken" class="field-hint">
        未加载到目录：请点击「刷新目录」，或在「资金与记录」页先打开大模型区块完成加载。
      </p>

      <label class="field-label">温度 ({{ temperature }})</label>
      <input v-model="temperature" type="range" min="0" max="1" step="0.05" class="field-range" />
    </div>

    <!-- Workflow heart -->
    <div v-else-if="selectedNodeData.moduleKind === 'workflow_heart'" class="field-group">
      <label class="field-label">工作流 ID *</label>
      <select v-model="workflowId" class="field-select">
        <option :value="0">— 请选择 —</option>
        <!-- Fallback: manifest has a workflow_id that hasn't passed full sandbox yet -->
        <option
          v-if="workflowId > 0 && !store.allWorkflowOptions.some((wf) => Number((wf as Record<string, unknown>).id) === workflowId)"
          :value="workflowId"
        >
          #{{ workflowId }}（生成工作流，待沙箱验证）
        </option>
        <option
          v-for="wf in store.allWorkflowOptions"
          :key="(wf as Record<string, unknown>).id as number"
          :value="(wf as Record<string, unknown>).id"
        >
          #{{ (wf as Record<string, unknown>).id }} {{ (wf as Record<string, unknown>).name }}
        </option>
      </select>
      <p class="field-hint">
        仅显示已通过沙箱测试的工作流。若列表为空，请先在脚本工作流页面完成测试。
      </p>

      <!-- Research context helper -->
      <div class="research-section">
        <label class="field-label">研究上下文（可选）</label>
        <div class="field-row">
          <input v-model="researchBrief" class="field-input" placeholder="关键词，补充网络资料" style="flex:1" />
          <button class="field-btn" :disabled="researchLoading" @click="fetchResearch">
            {{ researchLoading ? '…' : '获取' }}
          </button>
        </div>
        <p v-if="store.researchContext" class="field-hint research-context">
          {{ store.researchContext.slice(0, 300) }}{{ store.researchContext.length > 300 ? '…' : '' }}
        </p>
      </div>
    </div>

    <!-- Skills -->
    <div v-else-if="selectedNodeData.moduleKind === 'skills'" class="field-group">
      <p class="field-hint">当前已配置 {{ skills.length }} 个技能</p>
      <div v-for="(sk, i) in skills" :key="i" class="skill-item">
        <span class="skill-name">{{ (sk as Record<string, unknown>).name ?? `技能 ${i+1}` }}</span>
      </div>
      <p v-if="!skills.length" class="field-hint">在 Agent 面板输入"推荐技能"指令，AI 会自动填充。</p>
    </div>

    <!-- Memory -->
    <div v-else-if="selectedNodeData.moduleKind === 'memory'" class="field-group">
      <p class="field-hint">已启用记忆模块。可在 manifest 中详细配置 short_term / long_term 参数。</p>
    </div>

    <!-- Voice -->
    <div v-else-if="selectedNodeData.moduleKind === 'voice'" class="field-group">
      <label class="field-label">TTS 试听</label>
      <div class="field-row">
        <input v-model="ttsText" class="field-input" placeholder="输入测试文字…" style="flex:1" />
        <button class="field-btn" :disabled="ttsLoading" @click="previewTts">
          {{ ttsLoading ? '…' : '▶ 试听' }}
        </button>
      </div>
    </div>

    <!-- Fallback for other modules -->
    <div v-else class="field-group">
      <p class="field-hint">{{ selectedNodeData.meta.label }} 模块已启用。JSON 编辑请展开高级配置。</p>
      <details class="field-advanced">
        <summary class="field-advanced-toggle">高级 JSON 配置</summary>
        <textarea
          class="field-textarea field-json"
          rows="10"
          :value="JSON.stringify(selectedNodeData.slice, null, 2)"
          @change="(e) => {
            try {
              const val = JSON.parse((e.target as HTMLTextAreaElement).value)
              const path = MODULE_META[selectedNodeData!.moduleKind].paths[0]
              setPath(path, val)
            } catch { /* ignore parse error */ }
          }"
        />
      </details>
    </div>
  </div>
</template>
