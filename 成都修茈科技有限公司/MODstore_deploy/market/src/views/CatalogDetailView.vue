<template>
  <div class="catalog-detail">
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="err" class="flash flash-err">{{ err }}</div>
    <template v-else-if="item">
      <CatalogDetailHero
        :item="item"
        :product-avatar-letter="productAvatarLetter"
        :quality-visible="qualityVisible"
        :quality-overall-grade="qualityOverallGrade"
        :quality-overall-score="qualityOverallScore"
        :buying="buying"
        :delisting="delisting"
        :is-admin="authStore.isAdmin"
        @download="doDownload"
        @buy="doBuy"
        @delist="delistItem"
      />

      <CatalogCreatorProfile
        v-if="item"
        :author="item.author ?? null"
        :stats="item.creator_stats ?? null"
        :install-count="item.install_count"
        :industry="item.industry"
        :favorited="!!item.favorited"
        :following="authorFollowing"
        :fav-busy="favBusy"
        :is-self="isAuthorSelf"
        @follow="toggleAuthorFollow"
        @favorite="toggleFavorite"
        @complaint="openComplaintPanel"
      />

      <CatalogDetailComplaint
        :open="complaintPanelOpen"
        :complaint-type="complaintType"
        :complaint-reason="complaintReason"
        :complaint-submitting="complaintSubmitting"
        :customer-link="customerServiceLink('complaint')"
        @update:complaintType="complaintType = $event"
        @update:complaintReason="complaintReason = $event"
        @submit="submitComplaint"
        @close="complaintPanelOpen = false"
      />

      <!-- 员工包：规格 + 六维（懒加载） -->
      <CatalogDetailSpecsQuality
        v-if="item.artifact === 'employee_pack'"
        :item="item"
        :item-capabilities="itemCapabilities"
        :quality-pipeline-label="qualityPipelineLabel"
        :quality-visible="qualityVisible"
        :quality-loading="qualityLoading"
        :quality-report="qualityReport"
        :quality-error="qualityError"
        :quality-validate-errors="qualityValidateErrors"
        :quality-scoring-label="qualityScoringLabel"
        :quality-llm-summary="qualityLlmSummary"
        :quality-audited-at="qualityAuditedAt"
        :quality-from-cache="qualityFromCache"
        :quality-overall-score="qualityOverallScore"
        :is-admin="authStore.isAdmin"
        @load-quality="loadQuality"
      />

      <CatalogDetailReviews
        :reviews-data="reviewsData"
        :reviews-loading="reviewsLoading"
        :reviews-err="reviewsErr"
        :has-token="hasToken"
        :purchased="!!item.purchased"
        :user-has-review="!!item.user_has_review"
        :review-rating="reviewRating"
        :review-content="reviewContent"
        :review-submitting="reviewSubmitting"
        @update:reviewRating="reviewRating = $event"
        @update:reviewContent="reviewContent = $event"
        @submit="submitReview"
      />

      <!-- 员工状态 -->
      <div v-if="item.artifact === 'employee_pack' && item.purchased" class="detail-section">
        <h2 class="section-title">员工状态</h2>
        <div v-if="employeeStatus.loading" class="loading">加载中...</div>
        <div v-else-if="employeeStatus.error" class="flash flash-err">
          {{ employeeStatus.error }}
        </div>
        <div v-else-if="employeeStatus.data" class="status-grid">
          <div class="status-item">
            <span class="status-label">状态</span>
            <span class="status-value">{{ employeeStatus.data.status }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">总执行次数</span>
            <span class="status-value">{{ employeeTotalExecutions(employeeStatus.data) }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">成功率</span>
            <span class="status-value">{{ employeeSuccessRate(employeeStatus.data).toFixed(1) }}%</span>
          </div>
        </div>
      </div>

      <!-- 工作流配置 -->
      <div v-if="item.artifact === 'employee_pack' && item.purchased" class="detail-section">
        <h2 class="section-title">工作流配置</h2>
        <p class="section-desc">将此员工添加到工作流中，配置任务参数</p>
        <div class="workflow-config">
          <button class="btn btn-primary" @click="navigateToWorkflow">添加到工作流</button>
        </div>
      </div>

      <details v-if="item.artifact === 'employee_pack'" class="detail-fold">
        <summary class="detail-fold-summary">描述与使用示例</summary>
        <p v-if="item.description" class="desc desc--fold">{{ item.description }}</p>
        <div v-if="itemExamples.length">
          <div v-for="ex in itemExamples" :key="ex.title" class="example-card">
            <h3>{{ ex.title }}</h3>
            <p v-if="ex.description" class="example-desc">{{ ex.description }}</p>
            <pre class="example-code">{{ JSON.stringify(ex.input, null, 2) }}</pre>
          </div>
        </div>
        <div v-else class="example-card">
          <h3>调用示例</h3>
          <pre class="example-code">
{
  "action": "execute",
  "employee_id": "{{ item.pkg_id || 'employee' }}"
}</pre
          >
        </div>
      </details>
    </template>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./catalog-detail/，模板子组件在 ./catalog-detail/，样式在 ./catalog-detail/catalog-detail.css。
import { onMounted } from 'vue'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import CatalogCreatorProfile from '../components/catalog/CatalogCreatorProfile.vue'
import CatalogDetailComplaint from './catalog-detail/CatalogDetailComplaint.vue'
import CatalogDetailHero from './catalog-detail/CatalogDetailHero.vue'
import CatalogDetailReviews from './catalog-detail/CatalogDetailReviews.vue'
import CatalogDetailSpecsQuality from './catalog-detail/CatalogDetailSpecsQuality.vue'
import * as catalogDetailTypes from './catalog-detail/catalogDetailTypes'
import type { CatalogItemDetail } from './catalog-detail/catalogDetailTypes'
import { useCatalogActions } from './catalog-detail/useCatalogActions'
import { useCatalogDetail } from './catalog-detail/useCatalogDetail'

const authStore = useAuthStore()

// 顶层 const 保持 wrapper.vm 对拆分前绑定的可访问面一致。
const securityLevelLabel = catalogDetailTypes.securityLevelLabel
const getArtifactLabel = catalogDetailTypes.getArtifactLabel
const materialCategoryLabel = catalogDetailTypes.materialCategoryLabel
const licenseScopeLabel = catalogDetailTypes.licenseScopeLabel
const originTypeLabel = catalogDetailTypes.originTypeLabel
const ipRiskLabel = catalogDetailTypes.ipRiskLabel
const complianceStatusLabel = catalogDetailTypes.complianceStatusLabel
const employeeTotalExecutions = catalogDetailTypes.employeeTotalExecutions
const employeeSuccessRate = catalogDetailTypes.employeeSuccessRate
const readAuthorFollowSet = catalogDetailTypes.readAuthorFollowSet

const {
  catalogParamId, item, loading, err, hasToken,
  itemCapabilities, itemExamples, productAvatarLetter,
  reviewsLoading, reviewsErr, reviewsData, loadReviews,
  qualityLoading, qualityError, qualityVisible, qualityReport, qualityValidateErrors, qualityPipelineLabel,
  qualityAuditedAt, qualityFromCache, qualityLlmSummary, qualityScoringLabel, qualityOverallScore, qualityOverallGrade,
  loadQuality, employeeStatus, loadEmployeeStatus,
} = useCatalogDetail()

const {
  buying, delisting, favBusy,
  authorFollowing, isAuthorSelf, syncAuthorFollowing, toggleAuthorFollow,
  toggleFavorite, doBuy, doDownload, delistItem, navigateToWorkflow,
  reviewRating, reviewContent, reviewSubmitting, submitReview,
  complaintType, complaintReason, complaintSubmitting, complaintPanelOpen,
  openComplaintPanel, customerServiceLink, submitComplaint,
} = useCatalogActions({ item, catalogParamId, loadReviews, loadEmployeeStatus })

onMounted(async () => {
  hasToken.value = !!localStorage.getItem('modstore_token')
  try {
    item.value = (await api.catalogDetail(catalogParamId.value)) as CatalogItemDetail
    syncAuthorFollowing()
    await loadReviews()
    // 如果是员工包且已购买，加载员工状态
    if (item.value.artifact === 'employee_pack' && item.value.purchased) {
      await loadEmployeeStatus()
    }
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    loading.value = false
  }
})

defineExpose({ materialCategoryLabel })
</script>

<style scoped src="./catalog-detail/catalog-detail.css"></style>
