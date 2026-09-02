<template>
  <div class="plans-page">
    <Teleport to="body">
      <div
        v-if="svipEntryRevealOverlay"
        class="svip-reveal-overlay"
        role="dialog"
        aria-label="欢迎加入超级会员"
      >
        <div class="svip-reveal-shimmer" />
        <div class="svip-reveal-content">
          <p class="svip-reveal-star" aria-hidden="true">✦</p>
          <h2 class="svip-reveal-h2">欢迎加入超级会员</h2>
          <p class="svip-reveal-p">更多进阶线已开放，下方为你展示可选档位</p>
        </div>
      </div>
    </Teleport>
    <div class="page-header">
      <h1 class="page-title">会员购买</h1>
      <p v-if="hasSvipTier" class="page-desc">
        可在此继续升级、查看各档权益
      </p>
    </div>

    <div v-if="errorMsg" ref="errorBannerRef" class="error-msg error-msg--prominent" role="alert">{{ errorMsg }}</div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else class="plans-grid">
      <div
        v-for="plan in visiblePlans"
        :key="plan.id"
        class="plan-card"
        :class="[
          'plan-card',
          isCurrent(plan) ? 'plan-card--current' : '',
          isBelowMyPlan(plan) ? 'plan-card--lower-tier' : '',
          `plan-card--${tierOf(plan)}`,
          hideSvipLadderTiers && isSvipLadderPlan(plan) ? 'plan-card--pre-reveal' : '',
          svipLadderRevealPop && isSvipLadderPlan(plan) ? 'plan-card--reveal-pop' : '',
        ]"
        :style="
          svipLadderRevealPop && isSvipLadderPlan(plan) ? { animationDelay: svipLadderStaggerDelay(plan) } : {}
        "
      >
        <div class="plan-header">
          <div class="plan-title-row">
            <h2 class="plan-name">{{ plan.name }}</h2>
            <span v-if="isCurrent(plan)" class="plan-badge plan-badge--current">当前等级</span>
            <span
              v-else-if="isBelowMyPlan(plan)"
              class="plan-badge plan-badge--superseded"
            >已高于此档</span>
          </div>
          <div class="plan-price">
            <span class="price-symbol">¥</span>
            <span class="price-value">{{ plan.price.toFixed(2) }}</span>
          </div>
          <p class="plan-desc">{{ plan.description }}</p>
        </div>

        <ul class="plan-features">
          <li v-for="(feature, i) in plan.features" :key="i">{{ feature }}</li>
        </ul>

        <button
          class="btn btn-primary"
          :disabled="checkingOut || isCurrent(plan) || isBelowMyPlan(plan)"
          @click="handleBuy(plan)"
        >
          <span v-if="checkingOut && checkingOutId === plan.id">处理中...</span>
          <span v-else-if="isCurrent(plan)">已是此等级</span>
          <span v-else-if="isBelowMyPlan(plan)">不可购买更低档</span>
          <span v-else>立即购买</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：套餐加载 / 档位 / 揭晓动画 / 结账逻辑在 ./payment-plans/，
// 卡片样式在 ./payment-plans/paymentPlans.css（scoped），全屏揭晓层样式在 ./payment-plans/svipReveal.css（非 scoped）。
import { usePaymentPlans } from './payment-plans/usePaymentPlans'

/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const {
  loading, checkingOut, checkingOutId, errorMsg, errorBannerRef,
  svipEntryRevealOverlay, hideSvipLadderTiers, svipLadderRevealPop,
  hasSvipTier, planTierOrder, visiblePlans, myPlan,
  isCurrent, isBelowMyPlan, isSvipLadderPlan, svipLadderStaggerDelay, tierOf,
  loadPlans, handleBuy,
} = usePaymentPlans()
/* eslint-enable @typescript-eslint/no-unused-vars */
</script>

<style scoped src="./payment-plans/paymentPlans.css"></style>
<style src="./payment-plans/svipReveal.css"></style>
