<template>
  <div>
    <h1 class="page-title">资金与记录</h1>

    <div
      class="balance-card"
      :class="{ 'balance-card--depleted': balance !== null && balance <= 0 }"
    >
      <div class="balance-label">当前余额</div>
      <div
        class="balance-value"
        :class="{
          'balance-updating': isUpdating,
          'balance-value--depleted': balance !== null && balance <= 0,
        }"
      >
        ¥{{ balance !== null ? balance.toFixed(2) : '--' }}
      </div>
      <div v-if="balanceError" class="flash flash-err" role="alert">
        {{ balanceError }}
        <span v-if="balance !== null">当前显示上次读取的余额，可能已过期。</span>
        <button type="button" class="btn btn-ghost" :disabled="financeLoading" @click="loadWalletOverview">重试读取余额</button>
      </div>
      <p v-else-if="financeLoading && balance === null" class="loading">正在读取余额…</p>
      <div v-if="balance !== null" class="balance-gauge" aria-hidden="true">
        <template v-if="(membershipReferenceYuan ?? 0) > 0">
          <div class="balance-gauge__track">
            <div
              class="balance-gauge__fill"
              :class="{ 'balance-gauge__fill--depleted': balance <= 0 }"
              :style="{ width: balanceGaugeFill + '%' }"
            />
          </div>
          <p class="balance-gauge__hint">
            会员随单「可用额度」参考线
            <strong>¥{{ (membershipReferenceYuan ?? 0).toFixed(0) }}</strong>
            ：多笔/升级时累加（退款会冲抵）；无流水时按当前有效套餐的对应整数额度。条长为当前余额相对本线，满格即达参考线。其它入金不计入本线，以实际扣费为准。
          </p>
        </template>
        <p v-else-if="membershipReferenceYuan !== null" class="balance-gauge__empty">
          暂无会员参考线：成为会员后，会按随单赠额与当前套餐价显示参考线；也可先
          <router-link to="/plans" class="inline-link">选套餐</router-link>。
        </p>
      </div>
    </div>
    <div class="card" v-if="myPlan || planError || planLoading">
      <h3 class="card-title">我的套餐</h3>
      <div v-if="planError" class="flash flash-err" role="alert">
        {{ planError }} <span v-if="myPlan">当前显示上次读取的套餐信息。</span>
        <button type="button" class="btn btn-ghost" :disabled="planLoading" @click="loadMyPlan">重试读取套餐</button>
      </div>
      <p v-else-if="planLoading && !myPlan" class="loading">正在读取套餐…</p>
      <template v-if="myPlan">
      <p class="recharge-intro">{{ myPlan.name }} · 到期 {{ formatDate(myPlan.expires_at) }}</p>
      <div class="quota-chips">
        <span v-for="q in myQuotas" :key="q.quota_type" class="quota-chip">
          {{ quotaLabel(q.quota_type) }} {{ q.remaining }}/{{ q.total }}
        </span>
      </div>
      <p class="plan-extra-links">
        <router-link :to="{ name: 'account', hash: '#api-keys' }" class="inline-link">API 密钥</router-link>
        <span class="plan-extra-sep">·</span>
        <router-link to="/analytics" class="inline-link">使用统计</router-link>
        <span class="plan-extra-sep">·</span>
        <router-link to="/refunds" class="inline-link">退款申请</router-link>
      </p>
      </template>
    </div>

    <div class="card recharge-card">
      <h3 class="card-title">支付宝充值</h3>
      <p class="recharge-intro">输入金额后跳转支付宝完成付款，到账后余额与交易记录会自动更新。</p>
      <div v-if="payErr" class="flash flash-err">{{ payErr }}</div>
      <div v-if="payHint" class="flash flash-ok">{{ payHint }}</div>
      <div class="recharge-form">
        <input
          class="input"
          type="number"
          v-model.number="payAmount"
          placeholder="金额（元）"
          min="0.01"
          step="0.01"
          :class="{ 'input-error': payAmount && payAmount <= 0 }"
          @input="validateAmount"
        />
        <input class="input" v-model="payNote" placeholder="备注（可选）" maxlength="50" />
        <button class="btn btn-primary-solid" type="button" :disabled="paying || !isValidAmount" @click="startAlipayRecharge">
          {{ paying ? '正在拉起支付…' : '支付宝充值' }}
        </button>
      </div>
      <p v-if="amountError" class="error-message">{{ amountError }}</p>
      <p class="recharge-hint">
        未能打开支付页面时，请稍后重试；仍无法支付时，请联系客服并提供操作时间与页面提示。套餐购买请前往
        <router-link to="/plans" class="inline-link">套餐页</router-link>。
      </p>
    </div>

    <div class="card finance-center-card">
      <div class="finance-head">
        <div>
          <h3 class="card-title">资金账户中心</h3>
          <p class="recharge-intro">订单付款会先进入钱包，再从钱包扣款；退款审核通过后退回钱包余额。</p>
        </div>
        <button type="button" class="btn btn-ghost" :disabled="financeLoading" @click="loadWalletOverview">
          {{ financeLoading ? '刷新中…' : financeError ? '重试' : '刷新' }}
        </button>
      </div>
      <div v-if="financeError" class="flash flash-err" role="alert">
        {{ financeError }} <span v-if="financeLoaded">当前显示上次加载的记录，可能已过期。</span>
      </div>
      <div class="finance-grid">
        <section class="finance-panel">
          <div class="finance-panel-head">
            <h4>最近订单</h4>
            <div class="finance-panel-head__actions">
              <button
                v-if="recentOrders.length"
                type="button"
                class="btn btn-ghost finance-dismiss-btn"
                :disabled="dismissOrdersLoading || financeLoading"
                @click="dismissNonActiveOrders"
              >
                {{ dismissOrdersLoading ? '处理中…' : '清理展示' }}
              </button>
              <router-link to="/orders" class="inline-link">全部订单</router-link>
            </div>
          </div>
          <p
            v-if="!financeLoading && !financeError && orderListTotal > RECENT_ORDERS_PANEL_LIMIT"
            class="finance-orders-omit"
          >
            本卡片仅显示最近 {{ RECENT_ORDERS_PANEL_LIMIT }} 单；当前列表共
            <strong>{{ orderListTotal }}</strong> 单，可点「全部订单」查看。点击「清理展示」可隐藏已关闭/失败/已退款等终态，仅保留待付、已付与退款中。
          </p>
          <div v-if="financeLoading && !recentOrders.length" class="loading">加载中...</div>
          <div v-else-if="recentOrders.length" class="finance-list">
            <button
              v-for="order in recentOrdersPanel"
              :key="order.out_trade_no"
              type="button"
              class="finance-row"
              @click="goOrder(order)"
            >
              <span>
                <strong>{{ order.subject }}</strong>
                <small>{{ order.out_trade_no }}</small>
              </span>
              <span class="finance-row-side">
                <b>¥{{ money(order.total_amount) }}</b>
                <small>{{ orderStatusText(order.status) }}</small>
              </span>
            </button>
          </div>
          <div v-else-if="financeLoaded && !financeError" class="empty-state">暂无订单</div>
          <div v-else-if="financeError" class="empty-state">订单暂时无法读取</div>
        </section>
        <section class="finance-panel">
          <div class="finance-panel-head">
            <h4>退款记录</h4>
            <router-link to="/refunds" class="inline-link">申请退款</router-link>
          </div>
          <div v-if="financeLoading && !recentRefunds.length" class="loading">加载中...</div>
          <div v-else-if="recentRefunds.length" class="finance-list">
            <div v-for="refund in recentRefunds" :key="refund.id" class="finance-row finance-row--static">
              <span>
                <strong>{{ refund.refund_no }}</strong>
                <small>{{ refund.order_no }}</small>
              </span>
              <span class="finance-row-side">
                <b>¥{{ money(refund.amount) }}</b>
                <small>{{ refundStatusText(refund.status) }}</small>
              </span>
            </div>
          </div>
          <div v-else-if="financeLoaded && !financeError" class="empty-state">暂无退款记录</div>
          <div v-else-if="financeError" class="empty-state">退款记录暂时无法读取</div>
        </section>
      </div>
    </div>

    <div class="card">
      <h3 class="card-title">交易记录</h3>
      <div v-if="txError" class="flash flash-err" role="alert">
        {{ txError }} <span v-if="txLoaded">当前显示上次加载的交易记录，可能已过期。</span>
        <button type="button" class="btn btn-ghost" :disabled="txLoading" @click="loadTransactions">重试读取交易</button>
      </div>
      <div v-if="txLoading && !transactions.length" class="loading">加载中...</div>
      <template v-else-if="transactions.length">
        <table class="tx-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>类型</th>
              <th>金额</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in visibleTransactions" :key="t.id">
              <td>{{ formatDate(t.created_at) }}</td>
              <td>{{ txnTypeLabel(t.type) }}</td>
              <td :class="t.amount > 0 ? 'amount-pos' : 'amount-neg'">
                {{ t.amount > 0 ? '+' : '' }}¥{{ t.amount.toFixed(2) }}
              </td>
              <td>
                {{ t.description }}
                <small v-if="t.order_no || t.refund_no" class="tx-ref">
                  {{ t.order_no ? `订单 ${t.order_no}` : '' }}
                  {{ t.refund_no ? `退款 ${t.refund_no}` : '' }}
                </small>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="transactions.length > RECENT_TX_PANEL_LIMIT" class="tx-more-wrap">
          <button type="button" class="btn btn-ghost" @click="txListExpanded = !txListExpanded">
            {{ txListExpanded ? '收起' : `展开其余 ${hiddenTxCount} 条` }}
          </button>
        </div>
      </template>
      <div v-else-if="txLoaded && !txError" class="empty-state">暂无交易记录</div>
    </div>

    <WalletLlmCard :llm="llm" :is-admin="isAdmin" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useWalletFinance } from '../composables/useWalletFinance'
import { useWalletLlm } from '../composables/useWalletLlm'
import WalletLlmCard from './wallet/WalletLlmCard.vue'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

// ── 域逻辑（自原 script 按域原样迁移至 composables） ────────────────────────

const finance = useWalletFinance()
const llm = useWalletLlm()

const {
  balance,
  membershipReferenceYuan,
  balanceGaugeFill,
  isUpdating,
  myPlan,
  myQuotas,
  quotaLabel,
  payErr,
  payHint,
  payAmount,
  payNote,
  paying,
  isValidAmount,
  validateAmount,
  startAlipayRecharge,
  amountError,
  financeLoading,
  financeError,
  financeLoaded,
  txError,
  txLoaded,
  balanceError,
  planError,
  planLoading,
  loadWalletOverview,
  recentOrders,
  orderListTotal,
  RECENT_ORDERS_PANEL_LIMIT,
  dismissOrdersLoading,
  dismissNonActiveOrders,
  recentOrdersPanel,
  goOrder,
  money,
  orderStatusText,
  recentRefunds,
  refundStatusText,
  txLoading,
  transactions,
  visibleTransactions,
  RECENT_TX_PANEL_LIMIT,
  txnTypeLabel,
  hiddenTxCount,
  txListExpanded,
  formatDate,
  // 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定
  /* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定 */
  loadBalance,
  loadTransactions,
  loadMyPlan,
  normalizeTransaction,
  /* eslint-enable @typescript-eslint/no-unused-vars */
} = finance

// ── 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定，需在 setup 顶层保留同名绑定 ──
/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定 */
const {
  catalog, llmStatusList, llmErr, llmNote,
  selectedProvider, selectedModel, iconLoadFailed,
  byokKey, byokBaseUrl, byokBulkPaste, byokImportDisabled,
  llmProviderFilter, catalogProvidersSorted, catalogSyncMeta,
  currentProviderBlock, selectedModelPricingDetail,
  categoryLabel, modelOptionLabel, providerTilePriceHint,
  modelsForCategory, providerTileMediaTags, formatCatalogFetchedAt,
  llmTileShowsImg, providerTileState, llmTileIconFailKey, providerTileTitle,
  llmByokCatalogDanger, llmInitials,
  selectProvider, persistPreferences,
  saveByok, importByokBulk, clearByok, refreshCatalog,
  syncSelectionFromServerPrefs, validateSelectionAfterRefresh, onVisibilityRefresh,
} = llm
/* eslint-enable @typescript-eslint/no-unused-vars */
</script>

<style scoped src="./WalletView.css"></style>
