<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'
import IndustryPresetField from '../shared/IndustryPresetField.vue'
import EmployeeReadinessBar from '../shared/EmployeeReadinessBar.vue'
import EmployeeTable from '../shared/EmployeeTable.vue'
import ModChecklist from '../shared/ModChecklist.vue'

const {
  modData,
  modDescriptionLine,
  aiBlueprint,
  industryCard,
  apiSummary,
  workflowSandboxOk,
  modSandboxOk,
  suggestedSkills,
  suggestedPricing,
  handleRefineSystemPrompt,
  refinePromptLoading,
  refinePromptError,
  applyPricingSuggestion,
} = useModAuthoringContext()
</script>

<template>
  <section class="panel">
    <h2 class="panel-title">概览</h2>
    <p v-if="modDescriptionLine" class="overview-desc">{{ modDescriptionLine }}</p>
    <p v-else class="overview-desc muted small">未填写介绍，可在「配置」中补 <code class="mono">description</code>。</p>

    <IndustryPresetField />

    <EmployeeReadinessBar mode="expert" />

    <details v-if="aiBlueprint" class="dev-details">
      <summary class="dev-details-summary">制作报告</summary>
      <div class="ai-blueprint-panel ai-blueprint-panel--compact">
        <div v-if="industryCard" class="ai-blueprint-card">
          <strong>{{ industryCard.name || '通用' }}</strong>
        </div>
        <div class="ai-blueprint-card">
          <strong>API {{ apiSummary.nodes.length }}</strong>
          <span v-if="apiSummary.warnings.length" class="warn-inline">{{ apiSummary.warnings.length }} 项待处理</span>
        </div>
        <div class="ai-blueprint-card">
          <strong>{{ workflowSandboxOk ? '沙箱通过' : '沙箱待查' }}</strong>
        </div>
        <div class="ai-blueprint-card">
          <strong>{{ modSandboxOk ? 'Mod 通过' : 'Mod 待查' }}</strong>
        </div>
      </div>
    </details>

    <div v-if="suggestedSkills.length || suggestedPricing" class="ai-suggestions-inline">
      <button
        type="button"
        class="btn btn-sm btn-secondary"
        :disabled="refinePromptLoading"
        @click="handleRefineSystemPrompt"
      >
        {{ refinePromptLoading ? '优化中…' : '优化 Prompt' }}
      </button>
      <button v-if="suggestedPricing" type="button" class="btn btn-sm" @click="applyPricingSuggestion">复制定价</button>
      <p v-if="refinePromptError" class="flash flash-err small">{{ refinePromptError }}</p>
    </div>

    <EmployeeTable mode="expert" />
    <ModChecklist />
  </section>
</template>
