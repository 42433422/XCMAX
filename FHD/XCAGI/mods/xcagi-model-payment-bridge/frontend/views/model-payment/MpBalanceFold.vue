<script setup lang="ts">
import type { ModelPaymentCtx } from './assemble'

// 拆分自 ModelPaymentView.vue 模板（原第 39–89 行）；模板逐字迁移，行为不变。
const props = defineProps<{ tm: ModelPaymentCtx }>()

const {
  walletUrlHandoff, marketBalanceHint, marketBalanceText, marketOverview,
  marketMembershipLabel, marketMembershipReferenceText, marketExperienceText,
  marketByokText, marketEmptyHint,
} = props.tm
</script>

<template>
      <details class="mp-fold" open>
        <summary class="mp-fold-title">账户余额</summary>
      <div class="card mp-panel mp-status mp-balance">
        <div class="mp-panel-head">
          <span class="mp-panel-icon mp-balance-icon" aria-hidden="true">¥</span>
          <div class="mp-balance-text">
            <div class="card-header mp-panel-title">
              账户余额（本机汇总）
              <a
                :href="walletUrlHandoff"
                target="_blank"
                rel="noopener noreferrer"
                class="mp-balance-link"
              >
                修茈钱包
                <i class="fa fa-external-link" aria-hidden="true"></i>
              </a>
            </div>
            <p class="muted mp-panel-desc">
              {{ marketBalanceHint }}
            </p>
          </div>
          <div class="mp-balance-amount">
            <span class="mp-balance-currency">¥</span>
            <span class="mp-balance-num">{{ marketBalanceText }}</span>
            <span class="mp-balance-unit">CNY</span>
          </div>
        </div>
        <div v-if="marketOverview" class="mp-market-quota">
          <div>
            <span>会员</span>
            <strong>{{ marketMembershipLabel }}</strong>
          </div>
          <div>
            <span>累计权益参考</span>
            <strong>{{ marketMembershipReferenceText }}</strong>
          </div>
          <div>
            <span>经验</span>
            <strong>{{ marketExperienceText }}</strong>
          </div>
          <div>
            <span>BYOK</span>
            <strong>{{ marketByokText }}</strong>
          </div>
        </div>
        <p v-else class="muted mp-market-empty">
          {{ marketEmptyHint }}
        </p>
      </div>
      </details>
</template>

<style scoped src="./model-payment.css"></style>
