<script setup lang="ts">
// 拆分自 CatalogDetailView.vue 模板（原第 76–105 行）；模板逐字迁移，事件改为 emits，行为不变。
import type { RouteLocationRaw } from 'vue-router'

defineProps<{
  open: boolean
  complaintType: string
  complaintReason: string
  complaintSubmitting: boolean
  customerLink: RouteLocationRaw
}>()

defineEmits<{
  (e: 'update:complaintType', v: string): void
  (e: 'update:complaintReason', v: string): void
  (e: 'submit'): void
  (e: 'close'): void
}>()
</script>

<template>
  <div v-if="open" class="detail-section complaint-panel">
    <div class="complaint-panel__head">
      <h2 class="section-title">投诉与申诉</h2>
      <button type="button" class="btn btn-secondary complaint-panel__close" @click="$emit('close')">收起</button>
    </div>
    <p class="section-desc">涉及抄袭、联动/IP 风险、授权争议、无法下载或权益异常时，可先提交记录，再进入 AI 客服补充证据材料。</p>
    <div class="complaint-form">
      <select
        :value="complaintType"
        class="input"
        @change="$emit('update:complaintType', ($event.target as HTMLSelectElement).value)"
      >
        <option value="plagiarism">疑似抄袭</option>
        <option value="ip_risk">联动/IP 风险</option>
        <option value="license">授权或商业使用争议</option>
        <option value="delivery">购买/下载/权益异常</option>
        <option value="appeal">作者申诉</option>
        <option value="other">其他问题</option>
      </select>
      <textarea
        :value="complaintReason"
        class="input textarea"
        rows="3"
        maxlength="4000"
        placeholder="请说明问题、证据链接或希望处理的结果"
        @input="$emit('update:complaintReason', ($event.target as HTMLTextAreaElement).value)"
      />
      <div class="complaint-actions">
        <button type="button" class="btn btn-primary-solid" :disabled="complaintSubmitting" @click="$emit('submit')">
          {{ complaintSubmitting ? '提交中...' : '提交投诉/申诉' }}
        </button>
        <router-link :to="customerLink" class="btn btn-secondary">进入 AI 客服补充材料</router-link>
      </div>
    </div>
  </div>
</template>

<style scoped src="./catalog-detail.css"></style>
