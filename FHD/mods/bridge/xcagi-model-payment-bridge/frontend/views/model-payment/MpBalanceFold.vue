<script setup lang="ts">
import { MODEL_PAYMENT_SECTIONS } from '@/constants/modelServiceNavigation'
import type { ModelPaymentCtx } from './assemble'

const props = defineProps<{ tm: ModelPaymentCtx }>()
const {
  walletUrl, openMarketUrl, marketBalanceHint, marketBalanceText, marketOverview,
  marketMembershipLabel, marketMembershipReferenceText, marketExperienceText, marketByokText,
} = props.tm
</script>

<template>
  <details class="mp-fold" open>
    <summary class="mp-fold-title">{{ MODEL_PAYMENT_SECTIONS.balance.label }}</summary>
    <div class="card mp-panel mp-balance">
      <div class="mp-panel-head">
        <div class="mp-balance-text">
          <a class="mp-balance-link" :href="walletUrl" @click.prevent="openMarketUrl(walletUrl)" target="_blank" rel="noopener noreferrer">修茈钱包</a>
          <p class="muted mp-panel-desc">{{ marketBalanceHint }}</p>
        </div>
        <div class="mp-balance-amount">
          <span class="mp-balance-currency">¥</span>
          <span class="mp-balance-num">{{ marketBalanceText }}</span>
          <span class="mp-balance-unit">CNY</span>
        </div>
      </div>
      <dl v-if="marketOverview" class="mp-market-quota">
        <div v-for="(value, label) in { 会员: marketMembershipLabel, 累计权益参考: marketMembershipReferenceText, 经验: marketExperienceText, BYOK: marketByokText }" :key="label">
          <dt>{{ label }}</dt><dd><strong>{{ value }}</strong></dd>
        </div>
      </dl>
    </div>
  </details>
</template>

<style scoped src="./model-payment.css"></style>
