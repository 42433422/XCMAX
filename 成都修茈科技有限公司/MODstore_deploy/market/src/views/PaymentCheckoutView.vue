<template>
  <div class="checkout-page">
    <div class="checkout-container">
      <h1 class="checkout-title">完成支付</h1>

      <div v-if="paidConfirmedFlash" role="status" class="confirm-banner confirm-banner--success">
        <strong>付款已确认</strong>
        <span class="confirm-banner-sub">支付状态已更新，你购买的方案已经生效。</span>
      </div>
      <div v-else-if="burstSyncActive && order?.status === 'pending'" role="status" class="confirm-banner confirm-banner--sync">
        <strong>正在确认支付结果…</strong>
        <span class="confirm-banner-sub">通常几秒即可完成，请稍候。</span>
      </div>
      <div v-else-if="order?.status === 'pending'" class="confirm-banner confirm-banner--hint">
        <strong>等待付款</strong>
        <span class="confirm-banner-sub"> 完成支付宝付款后返回本页，状态会自动更新。 </span>
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>加载订单信息...</p>
      </div>

      <div v-if="error" class="error-section">
        <div class="error-icon">!</div>
        <h2 class="error-title">加载失败</h2>
        <p class="error-desc">{{ error }}</p>
        <router-link to="/plans" class="btn btn-primary">返回套餐页</router-link>
      </div>

      <template v-else-if="order">
        <div v-if="transientWarning" role="status" class="transient-warning">
          {{ transientWarning }}
        </div>

        <!-- 订单信息 -->
        <div class="order-info">
          <div class="order-field">
            <span class="label">订单号</span>
            <span class="value">{{ order.out_trade_no }}</span>
          </div>
          <div class="order-field">
            <span class="label">商品</span>
            <span class="value">{{ order.subject }}</span>
          </div>
          <div class="order-field">
            <span class="label">金额</span>
            <span class="value price">¥{{ order.total_amount }}</span>
          </div>
          <div class="order-field">
            <span class="label">状态</span>
            <span :class="['value', 'status', `status-${order.status}`]">
              {{ statusText(order.status) }}
            </span>
          </div>
          <div v-if="order.pay_type" class="order-field">
            <span class="label">下单方式</span>
            <span class="value">{{ payTypeLabel(order.pay_type) }}</span>
          </div>
        </div>

        <!-- 浏览器跳转支付（alipay page/wap）：无二维码，需提示回站后自动对账 / 手动刷新 -->
        <div v-if="order.status === 'pending' && !qrCode" class="pending-redirect-section">
          <p class="pending-redirect-title">等待付款</p>
          <p class="pending-redirect-desc">请在支付宝完成付款后返回本页，我们会自动更新结果。如果状态没有变化，请点击“更新支付结果”。</p>
          <div class="pending-redirect-actions">
            <button type="button" class="btn btn-primary" :disabled="refreshing" @click="manualRefreshStatus">
              {{ refreshing ? '正在更新…' : '更新支付结果' }}
            </button>
            <button type="button" class="btn btn-ghost" :disabled="refreshing" @click="retryPayment">重新打开支付宝</button>
          </div>
          <p class="pending-redirect-foot">长时间未更新？请确认当前登录账号与下单账号一致，或凭订单号联系客服。</p>
        </div>

        <!-- 二维码展示（precreate 模式） -->
        <div v-if="qrCode && order.status === 'pending'" class="qr-section">
          <p class="qr-hint">使用支付宝扫码付款</p>
          <div class="qr-wrapper">
            <img v-if="qrImageUrl" class="qr-img" :src="qrImageUrl" width="280" height="280" alt="支付宝支付二维码" />
          </div>
          <p v-if="isExpired" class="qr-expired-hint">
            订单已超时未支付。
            <button type="button" class="btn-retry" @click="retryPayment">重新支付</button>
            <router-link :to="planSelectionRoute" class="link-muted">或返回方案页</router-link>
          </p>
          <p v-else class="qr-waiting">付款完成后会自动更新</p>
        </div>

        <!-- 已支付成功 -->
        <div v-if="order.status === 'paid'" class="success-section">
          <div class="success-icon">✓</div>
          <h2 class="success-title">支付成功</h2>
          <p v-if="isCustomDeliveryOrder" class="success-desc">定制交付收款已确认，生产员工将自动开始本次新增开发。</p>
          <p v-else-if="isAccountLicenseOrder" class="success-desc">你的 XCAGI 方案已生效，现在可以回到桌面端登录使用。</p>
          <p v-else class="success-desc">你购买的内容已到账，可以开始使用。</p>
          <p v-if="isAccountLicenseOrder" class="success-desc success-desc--desktop">现在可以回到 XCAGI 桌面端，使用这个账号登录。</p>
          <div class="success-actions">
            <router-link v-if="isCustomDeliveryOrder" to="/deliveries" class="btn btn-primary">返回我的交付</router-link>
            <router-link to="/wallet" class="btn btn-primary">查看订单与账户</router-link>
            <router-link :to="{ name: 'wallet-purchased' }" class="btn btn-ghost">查看已购内容</router-link>
            <router-link :to="planSelectionRoute" class="btn btn-ghost">继续选购</router-link>
          </div>
          <p class="refund-hint">
            如需退款，可
            <router-link :to="{ name: 'refunds', query: { order_no: order.out_trade_no } }" class="refund-link"> 提交退款申请 </router-link>
            ，处理进度会显示在钱包资金账户中。
          </p>
        </div>

        <!-- 支付失败 -->
        <div v-if="order.status === 'failed'" class="failed-section">
          <p>支付失败</p>
          <router-link :to="planSelectionRoute" class="btn btn-primary">重新下单</router-link>
        </div>

        <!-- 已关闭 -->
        <div v-if="order.status === 'closed'" class="closed-section">
          <p>订单已关闭</p>
          <button type="button" class="btn btn-primary" @click="retryPayment">重新支付</button>
          <router-link :to="planSelectionRoute" class="btn btn-ghost">返回方案页</router-link>
        </div>
      </template>

      <div v-else class="not-found">
        <p>订单不存在</p>
        <router-link to="/plans" class="btn btn-ghost">返回套餐页</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./payment-checkout/，样式在 ./payment-checkout/payment-checkout.css。
import { useRoute, useRouter } from 'vue-router'
import { usePaymentCheckout } from './payment-checkout/usePaymentCheckout'

const route = useRoute()
const router = useRouter()

const {
  order,
  loading,
  error,
  transientWarning,
  qrCode,
  refreshing,
  burstSyncActive,
  paidConfirmedFlash,
  isAccountLicenseOrder,
  isCustomDeliveryOrder,
  planSelectionRoute,
  qrImageUrl,
  isExpired,
  orderParamId,
  fetchOrder,
  pollOrder,
  statusText,
  payTypeLabel,
  manualRefreshStatus,
  retryPayment,
  refetchVisiblePending,
  looksLikeAlipayReturnQuery,
} = usePaymentCheckout({ route, router })
</script>

<style scoped src="./payment-checkout/payment-checkout.css"></style>
