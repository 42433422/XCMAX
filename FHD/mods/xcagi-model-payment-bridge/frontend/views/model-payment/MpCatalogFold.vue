<script setup lang="ts">
import type { ModelPaymentCtx } from './assemble'

// 拆分自 ModelPaymentView.vue 模板（原第 152–198 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ModelPaymentCtx }>()

const {
  llmProviders, catalogCategorySummary, llmCatalogMessage, llmCatalogLoading,
  modelsByCategory, providerState, providerModelCount, providerInitials,
} = props.tm
</script>

<template>
      <details class="mp-fold">
        <summary class="mp-fold-title">
          模型支持
          <span v-if="llmProviders.length" class="mp-fold-badge">{{ llmProviders.length }} 家供应商</span>
          <span v-if="catalogCategorySummary" class="mp-fold-badge">{{ catalogCategorySummary }}</span>
        </summary>
        <p v-if="llmCatalogMessage" class="mp-sync-message">{{ llmCatalogMessage }}</p>
        <div v-if="llmCatalogLoading && !llmProviders.length" class="mp-loading muted">正在同步模型目录...</div>
        <div v-else-if="modelsByCategory.length" class="mp-cat-list">
          <section
            v-for="bucket in modelsByCategory"
            :key="bucket.category"
            class="mp-cat-block"
          >
            <header class="mp-cat-head">
              <strong>{{ bucket.label }}</strong>
              <small>{{ bucket.models.length }} 个</small>
            </header>
            <ul class="mp-cat-models">
              <li v-for="m in bucket.models.slice(0, 12)" :key="`${m.provider}/${m.id}`">
                <span class="mp-cat-model-id">{{ m.provider }}/{{ m.id }}</span>
                <span v-if="m.runtime_selectable" class="mp-cat-tag">可路由</span>
                <span v-if="m.chat_compatible" class="mp-cat-tag mp-cat-tag--chat">对话</span>
                <span v-if="m.priceText" class="mp-cat-price">{{ m.priceText }}</span>
              </li>
            </ul>
            <p v-if="bucket.models.length > 12" class="muted mp-cat-more">
              另有 {{ bucket.models.length - 12 }} 个未展开
            </p>
          </section>
        </div>
        <div v-else-if="llmProviders.length" class="mp-llm-grid mp-llm-grid--scroll" role="list">
          <article
            v-for="provider in llmProviders"
            :key="provider.provider"
            class="mp-llm-tile"
            :class="`mp-llm-tile--${providerState(provider)}`"
            role="listitem"
            :title="provider.error || `${provider.label || provider.provider} · ${providerModelCount(provider)} 个模型`"
          >
            <span class="mp-llm-icon" aria-hidden="true">{{ providerInitials(provider) }}</span>
            <strong>{{ provider.label || provider.provider }}</strong>
            <small>{{ providerModelCount(provider) }} 个模型</small>
          </article>
        </div>
        <div v-else class="mp-loading muted">暂无可展示模型目录；可点击顶部「刷新」或登录后重试。</div>
      </details>
</template>

<style scoped src="./model-payment.css"></style>
