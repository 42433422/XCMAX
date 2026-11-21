<script setup lang="ts">
// 拆分自 CatalogDetailView.vue 模板（原第 6–59 行）；模板逐字迁移，事件改为 emits，行为不变。
import { getArtifactLabel, complianceStatusLabel, ipRiskLabel, licenseScopeLabel, originTypeLabel, type CatalogItemDetail } from './catalogDetailTypes'

defineProps<{
  item: CatalogItemDetail
  productAvatarLetter: string
  qualityVisible: boolean
  qualityOverallGrade: string
  qualityOverallScore: string
  buying: boolean
  delisting: boolean
  isAdmin: boolean
}>()

defineEmits<{
  (e: 'download'): void
  (e: 'buy'): void
  (e: 'delist'): void
}>()
</script>

<template>
  <header class="detail-hero">
    <div class="detail-hero__main">
      <div class="detail-hero__avatar" aria-hidden="true">{{ productAvatarLetter }}</div>
      <div class="detail-hero__body">
        <div class="detail-hero__title-row">
          <h1 class="detail-hero__title">{{ item.name }}</h1>
          <span
            v-if="qualityVisible && qualityOverallGrade"
            class="detail-hero__grade"
            :class="'detail-hero__grade--' + qualityOverallGrade.toLowerCase()"
            :title="qualityOverallScore + ' 分'"
          >
            {{ qualityOverallGrade }}级 · {{ qualityOverallScore }}
          </span>
        </div>
        <p class="detail-hero__meta">
          <code class="detail-hero__pkg">{{ item.pkg_id }}</code>
          <span class="detail-hero__dot">·</span>
          v{{ item.version }}
          <span class="detail-hero__dot">·</span>
          {{ item.industry || '通用' }}
          <span class="detail-hero__dot">·</span>
          {{ getArtifactLabel(item.artifact) }}
        </p>
        <div class="detail-hero__tags">
          <span class="info-chip">{{ item.license_scope_label || licenseScopeLabel(item.license_scope) }}</span>
          <span class="info-chip">来源：{{ originTypeLabel(item.origin_type) }}</span>
          <span class="info-chip">风险：{{ ipRiskLabel(item.ip_risk_level) }}</span>
          <span class="info-chip" :class="{ warn: item.compliance_status && item.compliance_status !== 'approved' }">
            {{ complianceStatusLabel(item.compliance_status) }}
          </span>
        </div>
      </div>
    </div>
    <div class="detail-hero__cta">
      <div class="detail-hero__price" :class="{ free: item.price <= 0 }">
        {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
      </div>
      <div class="detail-hero__buttons">
        <template v-if="item.purchased">
          <button type="button" class="btn btn-success" @click="$emit('download')">下载</button>
          <span class="owned-badge">已拥有</span>
        </template>
        <template v-else>
          <button type="button" class="btn btn-primary-solid btn-cta-buy" @click="$emit('buy')" :disabled="buying">
            {{ buying ? '购买中...' : '购买' }}
          </button>
        </template>
        <button v-if="isAdmin" type="button" class="btn btn-danger" :disabled="delisting" @click="$emit('delist')">
          {{ delisting ? '下架中...' : '下架' }}
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped src="./catalog-detail.css"></style>
