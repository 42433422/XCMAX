<template>
  <div class="page-view mp-root" :class="{ 'mp-root--embedded': embedded }" id="view-model-payment">
    <div v-if="isOffline" class="mp-status-banner mp-status-banner--offline">
      <span class="mp-status-dot"></span>
      <span class="mp-status-text">离线模式 - 显示本地缓存数据</span>
      <button class="mp-status-btn" @click="retryConnection">重新连接</button>
    </div>
    <div v-else-if="dataSource === 'cache'" class="mp-status-banner mp-status-banner--cached">
      <span class="mp-status-dot"></span>
      <span class="mp-status-text">缓存模式 - {{ cacheAgeText }}</span>
    </div>

    <div class="page-content" :class="{ 'mp-page-content--embedded': embedded }">
      <div class="page-header mp-hero">
        <div v-if="!embedded" class="mp-hero-text">
          <h2>模型服务</h2>
        </div>
        <div class="mp-hero-actions" :class="{ 'mp-hero-actions--embedded': embedded }">
          <a class="mp-hero-btn mp-hero-btn--primary" :href="walletUrl" @click.prevent="openMarketUrl(walletUrl)" target="_blank" rel="noopener noreferrer">
            {{ MODEL_SERVICE_WALLET.label }}
          </a>
          <a class="mp-hero-btn" :href="plansUrl" @click.prevent="openMarketUrl(plansUrl)" target="_blank" rel="noopener noreferrer">{{ MODEL_SERVICE_PLANS.label }}</a>
          <button type="button" class="mp-hero-btn" :disabled="isRefreshing" @click="forceRefreshAll()">
            {{ isRefreshing ? '同步中…' : '刷新' }}
          </button>
        </div>
      </div>

      <p v-if="marketSyncWarning" class="mp-sync-warning" role="status">{{ marketSyncWarning }}</p>

      <p v-if="handoffError" class="mp-sync-warning" role="alert">{{ handoffError }}</p>

      <MpBalanceFold :tm="mp" />

      <details class="mp-fold">
        <summary class="mp-fold-title">{{ MODEL_PAYMENT_SECTIONS.recharge.label }}</summary>
        <div class="mp-recharge-grid mp-recharge-grid--compact">
          <a
            v-for="item in rechargeLinks"
            :key="item.amount"
            class="mp-recharge-card"
            :href="item.url"
            @click.prevent="openMarketUrl(item.url)"
            target="_blank"
            rel="noopener noreferrer"
          >
            <strong>¥{{ item.amount }}</strong>
            <span>{{ item.label }}</span>
          </a>
        </div>
      </details>

      <MpPlansFold :tm="mp" />
      <MpCatalogFold :tm="mp" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { MODEL_PAYMENT_SECTIONS, MODEL_SERVICE_PLANS, MODEL_SERVICE_WALLET } from '@/constants/modelServiceNavigation'
import MpBalanceFold from './model-payment/MpBalanceFold.vue'
import MpPlansFold from './model-payment/MpPlansFold.vue'
import MpCatalogFold from './model-payment/MpCatalogFold.vue'
import { assembleMpModelPayment } from './model-payment/assemble'

defineProps<{ embedded?: boolean }>()

const mp = assembleMpModelPayment()

const {
  isOffline, dataSource, cacheAgeText, retryConnection,
  walletUrl, plansUrl, isRefreshing, forceRefreshAll,
  marketSyncWarning, rechargeLinks, openMarketUrl, handoffError,
} = mp
</script>

<style scoped src="./model-payment/model-payment.css"></style>
