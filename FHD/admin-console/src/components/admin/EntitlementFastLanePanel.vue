<template>
  <section class="entitlement-fast-lane" aria-label="权益快速通道">
    <header>
      <div>
        <p>ENTITLEMENT FAST LANE</p>
        <h3>权益快速通道</h3>
        <span>直接绑定账号授权或会员等级，不生成订单、支付、钱包或交易流水。</span>
      </div>
      <button type="button" class="fast-lane-status" :disabled="busy || !account" @click="loadStatus">
        查询当前权益
      </button>
    </header>

    <div class="fast-lane-form">
      <label>
        <span>账号</span>
        <input
          v-model.trim="account"
          list="fast-lane-account-options"
          type="text"
          placeholder="用户 ID、用户名或邮箱"
          autocomplete="off"
        />
        <datalist id="fast-lane-account-options">
          <option v-for="user in users" :key="user.id" :value="user.username">
            {{ user.email || `ID ${user.id}` }}
          </option>
        </datalist>
      </label>

      <label>
        <span>套餐 / 权益等级</span>
        <select v-model="planId" :disabled="busy || loadingCatalog">
          <option value="" disabled>{{ loadingCatalog ? '正在加载…' : '请选择套餐' }}</option>
          <optgroup label="XCAGI 账号授权">
            <option v-for="plan in accountLicensePlans" :key="plan.id" :value="plan.id">
              {{ plan.title }} · {{ plan.license_type === 'permanent' ? '永久' : `${plan.duration_days || 30} 天` }}
            </option>
          </optgroup>
          <optgroup label="VIP / SVIP 会员权益">
            <option v-for="plan in membershipPlans" :key="plan.id" :value="plan.id">
              {{ plan.title }} · {{ plan.id }}
            </option>
          </optgroup>
        </select>
      </label>

      <label v-if="selectedPlan?.catalog === 'membership'">
        <span>有效天数</span>
        <input v-model.number="durationDays" type="number" min="1" max="3650" />
      </label>

      <label class="fast-lane-reason">
        <span>审计原因</span>
        <input
          v-model.trim="reason"
          type="text"
          maxlength="2000"
          placeholder="必填，至少 4 个字；例：创始人确认客户授权"
        />
      </label>

      <div class="fast-lane-actions">
        <button type="button" class="is-primary" :disabled="busy" @click="mutate('assign')">
          {{ busyAction === 'assign' ? '绑定中…' : '绑定 / 替换权益' }}
        </button>
        <button type="button" class="is-danger" :disabled="busy" @click="mutate('revoke')">
          {{ busyAction === 'revoke' ? '撤销中…' : '撤销所选权益' }}
        </button>
      </div>
    </div>

    <p v-if="errorMessage" class="fast-lane-message is-error" role="alert">{{ errorMessage }}</p>
    <div v-else-if="result" class="fast-lane-result" aria-live="polite">
      <strong>{{ result.account?.username || account }} · 当前生效权益</strong>
      <span v-if="!result.active_plans?.length">暂无生效套餐</span>
      <ul v-else>
        <li v-for="plan in result.active_plans" :key="plan.user_plan_id">
          <b>{{ plan.title }}</b>
          <code>{{ plan.plan_id }}</code>
          <small>{{ plan.expires_at ? `到期 ${formatDate(plan.expires_at)}` : '永久有效' }}</small>
        </li>
      </ul>
      <small v-if="result.audit?.idempotency_key">
        审计键：<code>{{ result.audit.idempotency_key }}</code>
      </small>
    </div>

    <footer>
      <i class="fa fa-terminal" aria-hidden="true"></i>
      <span>终端同源快捷模式</span>
      <code>./scripts/admin_entitlement_fast_lane.py grant &lt;账号&gt; &lt;plan_id&gt; --actor &lt;管理员&gt; --reason "&lt;原因&gt;"</code>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  xcmaxAdminApi,
  type EntitlementFastLanePlan,
  type EntitlementFastLaneResult,
  type MarketAdminUser,
} from '@/api/xcmaxAdmin'
import { appAlert, appConfirm } from '@/utils/appDialog'

const emit = defineEmits<{ changed: [] }>()
const users = ref<MarketAdminUser[]>([])
const plans = ref<EntitlementFastLanePlan[]>([])
const account = ref('')
const planId = ref('')
const durationDays = ref(30)
const reason = ref('')
const result = ref<EntitlementFastLaneResult | null>(null)
const errorMessage = ref('')
const loadingCatalog = ref(false)
const busyAction = ref<'' | 'status' | 'assign' | 'revoke'>('')
const busy = computed(() => Boolean(busyAction.value))
const accountLicensePlans = computed(() => plans.value.filter((plan) => plan.catalog === 'account_license'))
const membershipPlans = computed(() => plans.value.filter((plan) => plan.catalog === 'membership'))
const selectedPlan = computed(() => plans.value.find((plan) => plan.id === planId.value))

function unwrap(raw: unknown): Record<string, unknown> {
  const body = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  return body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : body
}

function newIdempotencyKey(action: 'assign' | 'revoke'): string {
  const token = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `fast-lane-ui-${action}-${token}`
}

async function loadCatalog() {
  loadingCatalog.value = true
  errorMessage.value = ''
  const usersRequest = xcmaxAdminApi.listUsers(200, 0)
  try {
    const plansRaw = await xcmaxAdminApi.listEntitlementFastLanePlans()
    const plansBody = unwrap(plansRaw)
    plans.value = Array.isArray(plansBody.items) ? plansBody.items as EntitlementFastLanePlan[] : []
    if (!planId.value && plans.value.length) planId.value = plans.value[0].id
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loadingCatalog.value = false
  }
  void usersRequest.then((usersRaw) => {
    const usersBody = unwrap(usersRaw)
    users.value = Array.isArray(usersBody.users) ? usersBody.users as MarketAdminUser[] : []
  }).catch(() => {
    users.value = []
  })
}

async function loadStatus() {
  if (!account.value) return
  busyAction.value = 'status'
  errorMessage.value = ''
  try {
    result.value = unwrap(
      await xcmaxAdminApi.getEntitlementFastLaneAccount(account.value),
    ) as EntitlementFastLaneResult
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    busyAction.value = ''
  }
}

async function mutate(action: 'assign' | 'revoke') {
  if (!account.value) {
    await appAlert('请输入用户 ID、用户名或邮箱')
    return
  }
  if (!planId.value) {
    await appAlert('请选择要操作的套餐权益')
    return
  }
  if (reason.value.length < 4) {
    await appAlert('请填写至少 4 个字的审计原因')
    return
  }
  const verb = action === 'assign' ? '绑定 / 替换' : '撤销'
  const confirmed = await appConfirm(
    `${verb}账号「${account.value}」的「${selectedPlan.value?.title || planId.value}」？\n\n本操作不会生成订单、支付或钱包流水，但会永久写入审计记录。`,
    { title: '权益快速通道', confirmText: `确认${verb}` },
  )
  if (!confirmed) return
  busyAction.value = action
  errorMessage.value = ''
  try {
    const payload = {
      account: account.value,
      action,
      plan_id: planId.value,
      reason: reason.value,
      idempotency_key: newIdempotencyKey(action),
      ...(selectedPlan.value?.catalog === 'membership'
        ? { duration_days: durationDays.value }
        : {}),
    }
    result.value = unwrap(
      await xcmaxAdminApi.mutateEntitlementFastLane(payload),
    ) as EntitlementFastLaneResult
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    busyAction.value = ''
  }
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}

onMounted(loadCatalog)
</script>

<style scoped>
.entitlement-fast-lane { margin: 18px 0; padding: 18px; border: 1px solid rgba(65, 145, 255, .28); border-radius: 16px; background: linear-gradient(135deg, rgba(18, 38, 72, .94), rgba(17, 31, 55, .88)); box-shadow: 0 12px 34px rgba(5, 13, 27, .2); }
.entitlement-fast-lane > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.entitlement-fast-lane header p { margin: 0 0 4px; color: #6eb4ff; font-size: 11px; font-weight: 800; letter-spacing: .16em; }
.entitlement-fast-lane h3 { margin: 0 0 5px; color: #f5f9ff; font-size: 20px; }
.entitlement-fast-lane header span { color: #aebed4; font-size: 13px; }
.fast-lane-status, .fast-lane-actions button { min-height: 38px; border-radius: 9px; border: 1px solid rgba(112, 175, 255, .42); padding: 0 14px; color: #dcecff; background: rgba(57, 113, 190, .18); cursor: pointer; }
.fast-lane-form { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(230px, 1.2fr) 110px minmax(260px, 1.5fr) auto; gap: 12px; align-items: end; margin-top: 16px; }
.fast-lane-form label { display: grid; gap: 6px; color: #9fb1c9; font-size: 12px; }
.fast-lane-form input, .fast-lane-form select { width: 100%; min-height: 39px; box-sizing: border-box; border: 1px solid rgba(137, 169, 208, .3); border-radius: 9px; padding: 0 11px; color: #eef5ff; background: rgba(5, 16, 32, .52); }
.fast-lane-actions { display: flex; gap: 8px; }
.fast-lane-actions .is-primary { border-color: rgba(68, 193, 147, .55); background: rgba(38, 150, 111, .2); white-space: nowrap; }
.fast-lane-actions .is-danger { border-color: rgba(255, 112, 126, .5); background: rgba(168, 57, 75, .18); white-space: nowrap; }
button:disabled { cursor: not-allowed; opacity: .55; }
.fast-lane-message, .fast-lane-result { margin: 13px 0 0; border-radius: 10px; padding: 11px 13px; }
.fast-lane-message.is-error { color: #ffd5da; background: rgba(172, 49, 70, .2); }
.fast-lane-result { color: #cfe0f5; background: rgba(7, 19, 36, .46); }
.fast-lane-result ul { display: flex; flex-wrap: wrap; gap: 8px; margin: 9px 0; padding: 0; list-style: none; }
.fast-lane-result li { display: flex; gap: 8px; align-items: center; border: 1px solid rgba(100, 163, 236, .24); border-radius: 8px; padding: 7px 9px; }
.fast-lane-result code, footer code { color: #8dc9ff; }
.entitlement-fast-lane footer { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 13px; color: #91a6c0; font-size: 12px; }
.entitlement-fast-lane footer code { overflow-wrap: anywhere; }
@media (max-width: 1180px) { .fast-lane-form { grid-template-columns: repeat(2, minmax(0, 1fr)); } .fast-lane-actions { grid-column: 1 / -1; } }
@media (max-width: 720px) { .entitlement-fast-lane > header { flex-direction: column; } .fast-lane-form { grid-template-columns: 1fr; } .fast-lane-actions { grid-column: auto; flex-direction: column; } }
</style>
