<script setup lang="ts">
// 拆分自 CatalogDetailView.vue 模板（原第 108–199 行）；模板逐字迁移，事件改为 emits，行为不变。
import EmployeeSixDimPanel from '../../components/workbench/EmployeeSixDimPanel.vue'
import type { SixDimensionReport } from '../../types/sixDimension'
import { securityLevelLabel, type CatalogItemDetail } from './catalogDetailTypes'

defineProps<{
  item: CatalogItemDetail
  itemCapabilities: { label: string; description: string }[]
  qualityPipelineLabel: string
  qualityVisible: boolean
  qualityLoading: boolean
  qualityReport: SixDimensionReport | null
  qualityError: string
  qualityValidateErrors: string[]
  qualityScoringLabel: string
  qualityLlmSummary: string
  qualityAuditedAt: string
  qualityFromCache: boolean
  qualityOverallScore: string
  isAdmin: boolean
}>()

defineEmits<{
  (e: 'load-quality', opts: boolean | { refresh?: boolean; llm?: boolean }): void
}>()
</script>

<template>
  <div class="detail-main-grid">
    <section class="detail-spec-col detail-panel">
      <h2 class="section-title">规格与能力</h2>
      <div v-if="qualityPipelineLabel" class="spec-runtime">
        <span class="spec-label">Runtime</span>
        <code>{{ qualityPipelineLabel }}</code>
      </div>
      <div v-if="itemCapabilities.length" class="spec-block">
        <h3 class="spec-subtitle">核心能力</h3>
        <ul class="capability-list">
          <li v-for="cap in itemCapabilities" :key="cap.label">
            <span class="cap-label">{{ cap.label }}</span>
            <span v-if="cap.description" class="cap-desc">{{ cap.description }}</span>
          </li>
        </ul>
      </div>
      <div class="spec-cards">
        <div class="spec-mini-card">
          <span class="spec-mini-label">行业适配</span>
          <span>{{ item.industry || '通用' }}</span>
        </div>
        <div class="spec-mini-card">
          <span class="spec-mini-label">安全等级</span>
          <span>{{ securityLevelLabel(item.security_level) }}</span>
        </div>
        <div class="spec-mini-card">
          <span class="spec-mini-label">版本</span>
          <span>v{{ item.version }}</span>
        </div>
      </div>
    </section>

    <section class="detail-quality-col detail-panel">
      <div class="quality-section-head">
        <h2 class="section-title">质量评估</h2>
        <p v-if="qualityVisible && qualityOverallScore" class="quality-section-score">
          综合 <strong>{{ qualityOverallScore }}</strong> 分
          <span v-if="qualityPipelineLabel" class="quality-section-pipe">{{ qualityPipelineLabel }}</span>
        </p>
      </div>
      <div v-if="!qualityVisible" class="quality-placeholder">
        <p>规则引擎快速评估不消耗 LLM；「LLM 深度评估」由六维质检员工（hex-quality-assessor）打分。</p>
        <div class="quality-placeholder-actions">
          <button type="button" class="btn btn-primary-solid" :disabled="qualityLoading" @click="$emit('load-quality', { refresh: false })">
            {{ qualityLoading ? '检测中...' : '查看六维评估' }}
          </button>
          <button type="button" class="btn btn-secondary" :disabled="qualityLoading" @click="$emit('load-quality', { llm: true })">
            {{ qualityLoading ? '评估中...' : 'LLM 深度评估' }}
          </button>
        </div>
      </div>
      <template v-else>
        <div v-if="qualityValidateErrors.length" class="flash flash-err quality-errors">
          <p v-for="(e, i) in qualityValidateErrors.slice(0, 5)" :key="i">{{ e }}</p>
        </div>
        <EmployeeSixDimPanel
          :report="qualityReport"
          :loading="qualityLoading"
          :error="qualityError"
          compact
          title=""
          :show-grade-scale="false"
        />
        <div class="quality-actions">
          <p v-if="qualityScoringLabel" class="quality-meta quality-meta--source">
            {{ qualityScoringLabel }}
          </p>
          <p v-if="qualityLlmSummary" class="quality-meta quality-llm-summary">
            {{ qualityLlmSummary }}
          </p>
          <p v-if="qualityAuditedAt" class="quality-meta">
            检测时间：{{ qualityAuditedAt }}
            <span v-if="qualityFromCache">（缓存）</span>
          </p>
          <div class="quality-action-buttons">
            <button type="button" class="btn btn-secondary" :disabled="qualityLoading" @click="$emit('load-quality', { llm: true })">
              LLM 深度评估
            </button>
            <button
              v-if="isAdmin"
              type="button"
              class="btn btn-secondary"
              :disabled="qualityLoading"
              @click="$emit('load-quality', { refresh: true })"
            >
              重新检测
            </button>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped src="./catalog-detail.css"></style>
