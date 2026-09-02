<template>
  <div class="page-view mp-root" id="view-model-payment">
    <!-- 离线/数据来源提示条 -->
    <div v-if="isOffline" class="mp-status-banner mp-status-banner--offline">
      <span class="mp-status-dot"></span>
      <span class="mp-status-text">离线模式 - 显示本地缓存数据</span>
      <button class="mp-status-btn" @click="retryConnection">重新连接</button>
    </div>
    <div v-else-if="dataSource === 'cache'" class="mp-status-banner mp-status-banner--cached">
      <span class="mp-status-dot"></span>
      <span class="mp-status-text">缓存模式 - {{ cacheAgeText }}</span>
    </div>

    <div class="page-content">
      <div class="page-header mp-hero">
        <div class="mp-hero-text">
          <h2>模型服务</h2>
          <p class="muted header-sub">
            余额与充值走修茈市场；本页汇总展示，支付在
            <a :href="walletUrlHandoff" target="_blank" rel="noopener noreferrer">钱包</a>
            /
            <a :href="plansUrlHandoff" target="_blank" rel="noopener noreferrer">套餐</a>
            完成。
          </p>
        </div>
        <div class="mp-hero-actions">
          <a class="mp-hero-btn mp-hero-btn--primary" :href="walletUrlHandoff" target="_blank" rel="noopener noreferrer">
            打开修茈钱包
          </a>
          <a class="mp-hero-btn" :href="plansUrlHandoff" target="_blank" rel="noopener noreferrer">会员套餐</a>
          <button type="button" class="mp-hero-btn" :disabled="isRefreshing" @click="forceRefreshAll()">
            {{ isRefreshing ? '同步中…' : '刷新' }}
          </button>
        </div>
      </div>

      <p v-if="marketSyncWarning" class="mp-sync-warning" role="status">{{ marketSyncWarning }}</p>

      <MpBalanceFold :tm="mp" />

      <details class="mp-fold">
        <summary class="mp-fold-title">快捷充值（跳转修茈钱包）</summary>
        <div class="mp-recharge-grid mp-recharge-grid--compact">
          <a
            v-for="item in rechargeLinks"
            :key="item.amount"
            class="mp-recharge-card"
            :href="item.url"
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
// 原超大 SFC 已拆分至 ./model-payment/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import { useRouter } from 'vue-router';
import MpBalanceFold from './model-payment/MpBalanceFold.vue'
import MpPlansFold from './model-payment/MpPlansFold.vue'
import MpCatalogFold from './model-payment/MpCatalogFold.vue'
import { assembleMpModelPayment } from './model-payment/assemble'

const router = useRouter();

const mp = assembleMpModelPayment()

const {
  isOffline, dataSource, cacheAgeText, retryConnection,
  walletUrlHandoff, plansUrlHandoff, isRefreshing, forceRefreshAll,
  marketSyncWarning, rechargeLinks,
} = mp
</script>

<style scoped src="./model-payment/model-payment.css"></style>
