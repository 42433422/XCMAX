<script setup lang="ts">
// 拆分自 HomeView.vue 模板（原第 271–299 行）；模板逐字迁移，事件改为 emits，行为不变。
import type { MarketItem } from './homeViewTypes'
import { truncate } from './homeViewTypes'

defineProps<{
  isLoggedIn: boolean
  loading: boolean
  items: MarketItem[]
}>()

defineEmits<{
  (e: 'open-upload'): void
}>()
</script>

<template>
  <section id="ai-market" class="section section--border-top">
    <div class="container">
      <div class="section-header">
        <h2 class="section-title">
          <router-link class="section-title-link" :to="{ name: 'ai-store' }">XC AGI · AI 市场</router-link>
        </h2>
        <p class="section-description">
          浏览和购买 AI 员工、提示词、Skill、TTS 声音模型与 MOD 素材，快速为你的业务系统添加能力。
          <router-link :to="{ name: 'ai-store' }" class="section-more-link">进入 AI 市场（按行业 / 类目 / 授权筛选）</router-link>
        </p>
        <button v-if="isLoggedIn" class="btn btn-primary" @click="$emit('open-upload')">上架素材</button>
      </div>

      <div v-if="loading" class="market-loading">加载中...</div>
      <div v-else-if="items.length" class="market-grid">
        <div v-for="item in items" :key="item.id" class="market-card">
          <h3 class="market-card-title">{{ item.name }}</h3>
          <p class="market-card-desc">{{ truncate(item.description, 60) }}</p>
          <div class="market-card-footer">
            <span class="market-card-price" :class="{ free: item.price <= 0 }">
              {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
            </span>
            <router-link :to="{ name: 'catalog-detail', params: { id: item.id } }" class="btn btn-sm">详情</router-link>
          </div>
        </div>
      </div>
      <div v-else class="market-empty">AI 市场暂无商品</div>
    </div>
  </section>
</template>

<style scoped src="./home-view.css"></style>
