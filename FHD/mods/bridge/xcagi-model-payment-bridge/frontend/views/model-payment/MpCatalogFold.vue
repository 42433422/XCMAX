<script setup lang="ts">
import { MODEL_PAYMENT_SECTIONS } from '@/constants/modelServiceNavigation'
import type { ModelPaymentCtx } from './assemble'

const props = defineProps<{ tm: ModelPaymentCtx }>()
const { llmProviders, llmCatalogMessage, llmCatalogLoading, modelsByCategory } = props.tm
</script>

<template>
  <details class="mp-fold">
    <summary class="mp-fold-title">{{ MODEL_PAYMENT_SECTIONS.catalog.label }}</summary>
    <p v-if="llmCatalogMessage" class="mp-sync-message" role="status">{{ llmCatalogMessage }}</p>
    <p v-if="llmCatalogLoading && !llmProviders.length" role="status">正在同步模型目录…</p>
    <div v-else-if="modelsByCategory.length" class="mp-cat-list">
      <section v-for="bucket in modelsByCategory" :key="bucket.category">
        <h3 class="mp-cat-head">{{ bucket.label }} <small>{{ bucket.models.length }} 个</small></h3>
        <ul class="mp-cat-models">
          <li v-for="m in bucket.models.slice(0, 12)" :key="`${m.provider}/${m.id}`">
            <span class="mp-cat-model-id">{{ m.provider }}/{{ m.id }}</span>
            <span v-if="m.runtime_selectable || m.chat_compatible" class="mp-cat-tag">{{ m.runtime_selectable ? '可路由' : '对话' }}</span>
            <span v-if="m.priceText" class="mp-cat-price">{{ m.priceText }}</span>
          </li>
        </ul>
        <p v-if="bucket.models.length > 12" class="muted mp-cat-more">另有 {{ bucket.models.length - 12 }} 个模型</p>
      </section>
    </div>
    <ul v-else-if="llmProviders.length">
      <li v-for="provider in llmProviders" :key="provider.provider">{{ provider.label || provider.provider }} · {{ provider.error ? '同步失败' : '暂无模型' }}</li>
    </ul>
    <p v-else class="muted">暂无模型目录</p>
  </details>
</template>

<style scoped src="./model-payment.css"></style>
