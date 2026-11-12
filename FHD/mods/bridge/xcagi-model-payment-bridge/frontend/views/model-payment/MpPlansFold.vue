<script setup lang="ts">
import type { ModelPaymentCtx } from './assemble'

// 拆分自 ModelPaymentView.vue 模板（原第 108–150 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ModelPaymentCtx }>()

const { membershipPlans, openMarketPlan } = props.tm
</script>

<template>
      <details class="mp-fold">
        <summary class="mp-fold-title">修茈会员套餐（{{ membershipPlans.length }} 档，点击跳转购买）</summary>
        <div class="mp-plans mp-plans--compact">
          <article
            v-for="(p, idx) in membershipPlans"
            :key="p.id"
            class="mp-plan"
            :class="['mp-plan--t' + (idx % 3), { 'is-selected': p.recommended }]"
            role="button"
            tabindex="0"
            :aria-label="`打开修茈市场购买 ${p.title}`"
            @click="openMarketPlan(p)"
            @keydown.enter.prevent="openMarketPlan(p)"
          >
            <div class="mp-plan-topbar" aria-hidden="true" />
            <div class="mp-plan-head">
              <h3 class="mp-plan-title">{{ p.title }}</h3>
              <div class="mp-plan-head-tags">
                <span v-if="p.badge" class="mp-badge">{{ p.badge }}</span>
              </div>
            </div>
            <p class="mp-desc">{{ p.description }}</p>
            <div class="mp-price-block">
              <span class="mp-price-currency">¥</span>
              <span class="mp-price-num">{{ p.price }}</span>
              <span class="mp-price-unit">CNY</span>
            </div>
            <ul class="mp-feature-list">
              <li v-for="feature in p.features" :key="feature">{{ feature }}</li>
            </ul>
            <div class="mp-actions">
              <button
                type="button"
                class="mp-pay mp-pay--ali mp-pay--full"
                @click.stop="openMarketPlan(p)"
              >
                <span class="mp-pay-ico mp-pay-ico-ali" aria-hidden="true">修</span>
                <span>去修茈市场购买</span>
              </button>
            </div>
          </article>
        </div>
      </details>
</template>

<style scoped src="./model-payment.css"></style>
