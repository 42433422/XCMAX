<template>
  <section class="enterprise-roster" aria-label="企业客户交付台账">
    <header class="enterprise-roster__head">
      <div>
        <p>ENTERPRISE CUSTOMER ROSTER</p>
        <h3>企业客户交付台账</h3>
        <span>所有企业级客户都在这里；是否定制只决定交付路径，不决定是否进入交付中心。</span>
      </div>
      <strong>{{ users.length }} 家</strong>
    </header>

    <div class="enterprise-roster__toolbar">
      <label>
        <i class="fa fa-search" aria-hidden="true"></i>
        <input v-model.trim="query" type="search" placeholder="搜索企业、账号或邮箱" />
      </label>
      <select v-model="lane" aria-label="按企业交付路径筛选">
        <option value="">全部路径</option>
        <option value="standard">标准企业交付</option>
        <option value="custom">定制交付</option>
      </select>
      <span>显示 {{ accounts.length }} / {{ users.length }} 家</span>
    </div>

    <div v-if="!accounts.length" class="enterprise-roster__empty">
      {{ users.length ? '没有符合筛选条件的企业客户' : '尚未读取到企业级客户' }}
    </div>

    <div v-else class="enterprise-roster__grid">
      <article v-for="account in accounts" :key="account.user.id" :class="`is-${account.lane}`">
        <span class="enterprise-roster__avatar">{{ account.name.slice(0, 1).toUpperCase() }}</span>
        <div class="enterprise-roster__identity">
          <strong>{{ account.name }}</strong>
          <span>{{ account.user.email || `账号：${account.user.username}` }}</span>
        </div>
        <div class="enterprise-roster__path">
          <strong>{{ account.lane === 'custom' ? '定制交付' : '标准企业交付' }}</strong>
          <span v-if="account.lane === 'custom'">
            {{ account.tickets.length }} 个工单 · 最新 {{ stageLabel(account.latestStage) }}
          </span>
          <span v-else>无需定制线 · 按企业标准包和安装回执闭环</span>
        </div>
        <button
          v-if="account.lane === 'custom'"
          type="button"
          @click="emit('open-custom', account.user)"
        >
          查看定制工单
        </button>
        <span v-else class="enterprise-roster__standard-mark">
          <i class="fa fa-check-circle" aria-hidden="true"></i> 已进入交付中心
        </span>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CustomDeliveryTicket, MarketAdminUser } from '@/api/xcmaxAdmin'

const props = defineProps<{
  users: MarketAdminUser[]
  tickets: CustomDeliveryTicket[]
}>()

const emit = defineEmits<{
  (event: 'open-custom', user: MarketAdminUser): void
}>()

const query = ref('')
const lane = ref('')

const stageLabels: Record<string, string> = {
  queued: '已受理',
  production: 'AI 生产中',
  acceptance: '待验收',
  commerce: '待商务闭环',
  rework: '待返工',
  delivering: '待安装回执',
  delivered: '已交付',
}

const ticketsByUser = computed(() => {
  const grouped = new Map<number, CustomDeliveryTicket[]>()
  for (const ticket of props.tickets) {
    const userId = Number(ticket.user_id)
    if (!Number.isFinite(userId)) continue
    const rows = grouped.get(userId) || []
    rows.push(ticket)
    grouped.set(userId, rows)
  }
  return grouped
})

const accounts = computed(() => {
  const needle = query.value.toLowerCase()
  return props.users.map((user) => {
    const tickets = ticketsByUser.value.get(Number(user.id)) || []
    const latest = [...tickets].sort((left, right) => String(right.updated_at || right.created_at || '')
      .localeCompare(String(left.updated_at || left.created_at || '')))[0]
    return {
      user,
      tickets,
      name: String(user.company || user.username || `企业客户 #${user.id}`),
      lane: tickets.length ? 'custom' : 'standard',
      latestStage: String(latest?.custom_delivery?.stage || 'queued'),
    }
  }).filter((account) => {
    if (lane.value && account.lane !== lane.value) return false
    if (!needle) return true
    return [account.name, account.user.username, account.user.email]
      .some((value) => String(value || '').toLowerCase().includes(needle))
  })
})

function stageLabel(stage: string): string {
  return stageLabels[stage] || stage
}
</script>

<style scoped>
.enterprise-roster { margin-bottom: 18px; padding: 17px; border: 1px solid #cbddee; border-radius: 17px; background: rgba(255,255,255,.92); box-shadow: 0 10px 28px rgba(24,58,94,.06); }
.enterprise-roster__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.enterprise-roster__head p { margin: 0 0 4px; color: #3d78bc; font-size: 9px; font-weight: 800; letter-spacing: .16em; }
.enterprise-roster__head h3 { margin: 0; color: #254663; font-size: 18px; }
.enterprise-roster__head span { display: block; margin-top: 5px; color: #6e8097; font-size: 11px; }
.enterprise-roster__head > strong { border-radius: 999px; background: #e7f1fd; color: #276bb7; padding: 7px 11px; white-space: nowrap; }
.enterprise-roster__toolbar { display: flex; align-items: center; gap: 9px; margin: 14px 0; padding: 9px; border-radius: 11px; background: #f3f7fb; }
.enterprise-roster__toolbar label { display: flex; align-items: center; gap: 7px; flex: 1; min-width: 180px; color: #7690ac; }
.enterprise-roster__toolbar input { width: 100%; border: 0; outline: 0; background: transparent; color: #132a46; }
.enterprise-roster__toolbar select { border: 1px solid #cbdbea; border-radius: 8px; background: #fff; padding: 7px 9px; color: #34516f; }
.enterprise-roster__toolbar > span { color: #6e8097; font-size: 11px; white-space: nowrap; }
.enterprise-roster__grid { display: grid; gap: 8px; }
.enterprise-roster__grid article { display: grid; grid-template-columns: 38px minmax(150px,.8fr) minmax(240px,1.2fr) auto; align-items: center; gap: 11px; padding: 11px 12px; border: 1px solid #dce7f1; border-left: 3px solid #6a9fd6; border-radius: 11px; background: #fbfdff; }
.enterprise-roster__grid article.is-custom { border-left-color: #e7903f; }
.enterprise-roster__avatar { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: #e8f1fb; color: #3172b7; font-weight: 800; }
.enterprise-roster__identity strong,.enterprise-roster__identity span,.enterprise-roster__path strong,.enterprise-roster__path span { display: block; }
.enterprise-roster__identity strong { color: #294a68; font-size: 12px; }
.enterprise-roster__identity span,.enterprise-roster__path span { margin-top: 3px; color: #718399; font-size: 10px; }
.enterprise-roster__path strong { color: #3d5d7b; font-size: 11px; }
.enterprise-roster__grid button { border: 1px solid #d5a071; border-radius: 8px; background: #fff7ef; color: #a65d26; padding: 7px 9px; font-size: 10px; font-weight: 700; cursor: pointer; }
.enterprise-roster__standard-mark { color: #2b8061; font-size: 10px; white-space: nowrap; }
.enterprise-roster__empty { padding: 22px; border: 1px dashed #c7d8e8; border-radius: 11px; color: #718399; text-align: center; }
@media (max-width: 760px) {
  .enterprise-roster__toolbar { align-items: stretch; flex-direction: column; }
  .enterprise-roster__grid article { grid-template-columns: 38px 1fr; }
  .enterprise-roster__path,.enterprise-roster__grid button,.enterprise-roster__standard-mark { grid-column: 2; }
}
</style>
