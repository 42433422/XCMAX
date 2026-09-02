<script setup lang="ts">
// 拆分自 CatalogDetailView.vue 模板（原第 201–230 行）；模板逐字迁移，事件改为 emits，行为不变。
import type { ReviewsPayload } from './catalogDetailTypes'

defineProps<{
  reviewsData: ReviewsPayload
  reviewsLoading: boolean
  reviewsErr: string
  hasToken: boolean
  purchased: boolean
  userHasReview: boolean
  reviewRating: number
  reviewContent: string
  reviewSubmitting: boolean
}>()

defineEmits<{
  (e: 'update:reviewRating', v: number): void
  (e: 'update:reviewContent', v: string): void
  (e: 'submit'): void
}>()
</script>

<template>
  <div class="detail-section reviews-section">
    <h2 class="section-title">评价</h2>
    <p v-if="reviewsData.total > 0" class="reviews-summary">平均 {{ reviewsData.average_rating }} 分 · 共 {{ reviewsData.total }} 条</p>
    <div v-if="reviewsLoading" class="loading">加载评价...</div>
    <div v-else-if="reviewsErr" class="flash flash-err">{{ reviewsErr }}</div>
    <ul v-else class="review-list">
      <li v-for="r in reviewsData.reviews" :key="r.id" class="review-item">
        <div class="review-head">
          <strong>{{ r.user_name }}</strong>
          <span class="review-stars">{{ '★'.repeat(r.rating) }}{{ '☆'.repeat(5 - r.rating) }}</span>
          <span class="review-date">{{ r.created_at }}</span>
        </div>
        <p v-if="r.content" class="review-body">{{ r.content }}</p>
      </li>
    </ul>
    <div v-if="hasToken && purchased && !userHasReview" class="review-form">
      <h3 class="review-form-title">写评价</h3>
      <label class="label">评分（1–5）</label>
      <select
        :value="reviewRating"
        class="input"
        @change="$emit('update:reviewRating', Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-for="n in 5" :key="n" :value="n">{{ n }} 分</option>
      </select>
      <label class="label">内容（可选）</label>
      <textarea
        :value="reviewContent"
        class="input textarea"
        rows="3"
        maxlength="4000"
        placeholder="使用体验、建议等"
        @input="$emit('update:reviewContent', ($event.target as HTMLTextAreaElement).value)"
      />
      <button type="button" class="btn btn-primary-solid" :disabled="reviewSubmitting" @click="$emit('submit')">
        {{ reviewSubmitting ? '提交中...' : '提交评价' }}
      </button>
    </div>
    <p v-else-if="hasToken && purchased && userHasReview" class="review-note">您已评价过该商品。</p>
    <p v-else-if="hasToken && !purchased" class="review-note">购买后可发表评价。</p>
  </div>
</template>

<style scoped src="./catalog-detail.css"></style>
