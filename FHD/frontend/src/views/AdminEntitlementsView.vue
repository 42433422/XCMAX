<template>
  <div class="page-view admin-entitlements-view">
    <div class="page-content">
      <header class="admin-entitlements-head">
        <div>
          <h2>用户管理</h2>
          <p class="muted">管理用户等级与行业，分配客户 Mod 权益，或进入代管模式代为配置。</p>
        </div>
        <button type="button" class="btn btn-primary btn-sm" @click="createAccountOpen = !createAccountOpen">
          {{ createAccountOpen ? '收起新建' : '新建账号' }}
        </button>
      </header>

      <div v-if="loadError" class="admin-entitlements-alert" role="alert">{{ loadError }}</div>
      <div v-if="walletLoadError" class="admin-entitlements-alert admin-entitlements-alert--soft" role="status">
        余额查询失败：{{ walletLoadError }}
      </div>

      <section class="admin-sync-strip" aria-label="本地安装与同步状态">
        <div>
          <strong>本地宿主状态</strong>
          <span class="muted">
            {{ installedModIds.size }} 个 Mod 已安装
            <template v-if="syncLastText"> · 最后同步 {{ syncLastText }}</template>
          </span>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" :disabled="localStatusLoading" @click="refreshLocalStatus">
          {{ localStatusLoading ? '刷新中…' : '刷新状态' }}
        </button>
      </section>
      <div v-if="localStatusError" class="admin-entitlements-alert admin-entitlements-alert--soft" role="status">
        {{ localStatusError }}
      </div>

      <section v-if="createAccountOpen" class="admin-create-account" aria-label="新建账号">
        <div class="admin-create-account__grid">
          <label class="admin-user-profile__field">
            <span class="admin-user-profile__label">用户名</span>
            <input
              v-model.trim="newAccount.username"
              class="admin-user-input"
              type="text"
              autocomplete="off"
              placeholder="例如 15099909316"
            />
          </label>
          <label class="admin-user-profile__field">
            <span class="admin-user-profile__label">密码</span>
            <span class="admin-password-field">
              <input
                v-model="newAccount.password"
                class="admin-user-input"
                :type="showNewAccountPassword ? 'text' : 'password'"
                autocomplete="new-password"
                placeholder="填写或安全生成"
              />
              <button type="button" class="btn btn-secondary btn-sm" @click="generateTemporaryPassword">
                生成
              </button>
              <button type="button" class="btn btn-secondary btn-sm" @click="showNewAccountPassword = !showNewAccountPassword">
                {{ showNewAccountPassword ? '隐藏' : '显示' }}
              </button>
            </span>
          </label>
          <label class="admin-user-profile__field">
            <span class="admin-user-profile__label">邮箱</span>
            <input v-model.trim="newAccount.email" class="admin-user-input" type="email" placeholder="默认自动生成" />
          </label>
          <label class="admin-user-profile__field">
            <span class="admin-user-profile__label">等级</span>
            <select v-model="newAccount.tier" class="admin-user-profile__select">
              <option v-for="t in TIER_OPTIONS" :key="t.value" :value="t.value">
                {{ t.label }}
              </option>
            </select>
          </label>
          <label class="admin-user-profile__field">
            <span class="admin-user-profile__label">行业</span>
            <select v-model="newAccount.industry_id" class="admin-user-profile__select">
              <option v-for="id in INDUSTRY_PRESET_IDS" :key="id" :value="id">{{ id }}</option>
            </select>
          </label>
          <label class="admin-flag admin-create-account__flag">
            <input v-model="newAccount.is_enterprise" type="checkbox" />
            企业用户
          </label>
          <button type="button" class="btn btn-primary btn-sm" :disabled="creatingAccount" @click="createAccount">
            {{ creatingAccount ? '创建中…' : '创建账号' }}
          </button>
        </div>
      </section>

      <section class="admin-user-toolbar" aria-label="用户筛选">
        <div class="admin-user-toolbar__search">
          <input v-model="userFilter" type="search" class="admin-user-search" placeholder="搜索用户名 / 邮箱" />
        </div>
        <div class="admin-user-toolbar__filters">
          <select v-model="tierFilter" class="admin-user-filter-select" aria-label="按等级筛选">
            <option value="">全部等级</option>
            <option v-for="t in TIER_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}（{{ tierStats[t.value] || 0 }}）</option>
          </select>
          <select v-model="industryFilter" class="admin-user-filter-select" aria-label="按行业筛选">
            <option value="">全部行业</option>
            <option v-for="id in INDUSTRY_PRESET_IDS" :key="id" :value="id">{{ id }}</option>
          </select>
          <span class="admin-user-toolbar__count muted"> 共 {{ filteredUsers.length }} / {{ users.length }} 人 </span>
        </div>
      </section>

      <section v-if="filteredUsers.length" class="admin-user-grid" aria-label="用户卡片列表">
        <article
          v-for="u in filteredUsers"
          :key="u.id"
          class="admin-user-card"
          :class="[`admin-user-card--${resolveTier(u)}`, { active: selectedUserId === u.id }]"
          tabindex="0"
          role="button"
          @click="selectUser(u)"
          @keydown.enter.prevent="selectUser(u)"
          @keydown.space.prevent="selectUser(u)"
        >
          <div class="admin-user-card__bar" aria-hidden="true"></div>
          <div class="admin-user-card__body">
            <div class="admin-user-card__head">
              <span class="admin-user-card__name">{{ u.username }}</span>
              <span class="admin-tier-tag" :class="`admin-tier-tag--${resolveTier(u)}`">{{ tierLabel(u) }}</span>
            </div>
            <dl class="admin-user-card__meta">
              <div class="admin-user-card__row">
                <dt>行业</dt>
                <dd>{{ u.industry_id || '通用' }}</dd>
              </div>
              <div class="admin-user-card__row">
                <dt>Mod</dt>
                <dd>{{ (u.mod_ids || []).length }} 个</dd>
              </div>
              <div class="admin-user-card__row admin-user-card__row--balance">
                <dt>余额</dt>
                <dd>{{ walletBalance(u) }}</dd>
              </div>
              <div class="admin-user-card__row admin-user-card__row--email">
                <dt>邮箱</dt>
                <dd>{{ u.email || '—' }}</dd>
              </div>
            </dl>
            <div class="admin-user-card__foot">
              <span class="muted">ID {{ u.id }}</span>
              <span v-if="u.is_enterprise" class="admin-user-card__badge">企业</span>
            </div>
          </div>
        </article>
      </section>
      <p v-else class="muted admin-user-grid__empty">没有匹配的用户</p>

      <section v-if="selectedUser" class="admin-user-detail" aria-label="用户详情">
        <header class="admin-user-detail__head">
          <div>
            <h3>{{ selectedUser.username }}</h3>
            <p class="muted">ID {{ selectedUser.id }} · {{ selectedUser.email || '无邮箱' }}</p>
          </div>
          <div class="admin-user-detail__actions">
            <label class="admin-flag">
              <input type="checkbox" :checked="selectedUser.is_enterprise" @change="toggleEnterprise($event)" />
              企业用户
            </label>
            <button type="button" class="btn btn-primary btn-sm" :disabled="impersonateLoading" @click="startImpersonate">
              {{ impersonateLoading ? '进入中…' : '进入代管' }}
            </button>
          </div>
        </header>

        <section class="admin-user-profile" aria-label="用户账号体系">
          <div class="admin-user-profile__row">
            <label class="admin-user-profile__field">
              <span class="admin-user-profile__label">等级</span>
              <select v-model="profileEditing.tier" class="admin-user-profile__select">
                <option v-for="t in TIER_OPTIONS" :key="t.value" :value="t.value">
                  {{ t.label }}
                </option>
              </select>
            </label>
            <label class="admin-user-profile__field">
              <span class="admin-user-profile__label">行业</span>
              <select v-model="profileEditing.industry_id" class="admin-user-profile__select">
                <option v-for="id in INDUSTRY_PRESET_IDS" :key="id" :value="id">{{ id }}</option>
              </select>
            </label>
            <label v-if="isEnterpriseProfile" class="admin-user-profile__field">
              <span class="admin-user-profile__label">账号等级</span>
              <select v-model="profileEditing.account_tier" class="admin-user-profile__select">
                <option value="">未设</option>
                <option v-for="t in ACCOUNT_TIER_OPTIONS" :key="t.value" :value="t.value">
                  {{ t.label }}
                </option>
              </select>
            </label>
            <label v-if="isEnterpriseProfile" class="admin-user-profile__field">
              <span class="admin-user-profile__label">预算</span>
              <select v-model="profileEditing.budget_range" class="admin-user-profile__select">
                <option value="">未填</option>
                <option v-for="b in BUDGET_RANGE_OPTIONS" :key="b" :value="b">{{ b }}</option>
              </select>
            </label>
            <button type="button" class="btn btn-primary btn-sm" :disabled="profileSaving" @click="saveProfile">
              {{ profileSaving ? '保存中…' : '保存' }}
            </button>
          </div>
          <div class="admin-user-profile__row admin-user-profile__entitled">
            <span class="admin-user-profile__label">已授权行业</span>
            <label v-for="id in INDUSTRY_PRESET_IDS" :key="id" class="admin-user-profile__chip">
              <input type="checkbox" :value="id" v-model="profileEditing.entitled_industries" />
              <span>{{ id }}</span>
            </label>
          </div>
        </section>

        <section class="admin-wallet-panel" aria-label="账户余额加款">
          <div class="admin-wallet-panel__summary">
            <span class="admin-user-profile__label">账户余额</span>
            <strong>{{ walletBalance(selectedUser) }}</strong>
            <small class="muted">给客户市场钱包加款，完成后同步到账户可用余额。</small>
          </div>
          <div class="admin-wallet-panel__form">
            <label class="admin-user-profile__field admin-wallet-panel__amount">
              <span class="admin-user-profile__label">添加金额</span>
              <input v-model.number="creditForm.amount" class="admin-user-input" type="number" min="0.01" step="0.01" inputmode="decimal" />
            </label>
            <label class="admin-user-profile__field admin-wallet-panel__desc">
              <span class="admin-user-profile__label">备注</span>
              <input v-model.trim="creditForm.description" class="admin-user-input" type="text" placeholder="后台加款" />
            </label>
            <div class="admin-wallet-panel__quick" aria-label="快捷金额">
              <button
                v-for="amount in CREDIT_QUICK_AMOUNTS"
                :key="amount"
                type="button"
                class="btn btn-secondary btn-sm"
                @click="setCreditAmount(amount)"
              >
                ¥{{ amount }}
              </button>
            </div>
            <button type="button" class="btn btn-primary btn-sm" :disabled="creditingWallet" @click="creditSelectedWallet">
              {{ creditingWallet ? '加款中…' : '加钱' }}
            </button>
          </div>
        </section>

        <section class="admin-entitlement-chain" aria-label="授权联动闭环">
          <div class="admin-entitlement-chain__intro">
            <div>
              <strong>账号 → Mod → AI 员工 → 设备执行</strong>
              <span class="muted">这里的绑定会决定企业端、手机端和信息页能看到并调用哪些员工。</span>
            </div>
            <div class="admin-chain-actions">
              <button
                type="button"
                class="btn btn-primary btn-sm"
                :disabled="forcePushingEntitlements"
                @click="forcePushSelectedEntitlements"
              >
                {{ forcePushingEntitlements ? '推送中…' : '强制推送企业端' }}
              </button>
              <a class="btn btn-secondary btn-sm" href="/admin/im">打开信息</a>
              <a class="btn btn-secondary btn-sm" href="/admin/settings">设备绑定</a>
            </div>
          </div>
          <div class="admin-chain-grid">
            <div v-for="card in selectedChainCards" :key="card.label" class="admin-chain-card">
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.detail }}</small>
            </div>
          </div>
          <div v-if="selectedMissingModIds.length" class="admin-chain-warning" role="status">
            已授权但本机未安装：{{ selectedMissingModIds.map(modLabel).join('、') }}。手机端不会拿到这些 Mod 下的员工。
          </div>
          <div class="admin-chain-employees">
            <div class="admin-chain-employees__head">
              <strong>授权后会同步的 AI 员工</strong>
              <span class="muted">{{ selectedWorkflowEmployees.length }} 个</span>
            </div>
            <div v-if="selectedWorkflowEmployees.length" class="admin-chain-employee-list">
              <span
                v-for="emp in selectedWorkflowEmployees"
                :key="`${emp.modId}:${emp.id}`"
                class="admin-chain-employee-chip"
                :title="emp.summary || emp.modName"
              >
                {{ emp.label }}
                <small>{{ emp.modName }}</small>
              </span>
            </div>
            <p v-else class="muted admin-chain-empty">
              当前账号的已安装 Mod 还没有暴露 workflow_employees；绑定并安装带员工的 Mod 后，会出现在信息页和手机端 AI 员工列表。
            </p>
          </div>
        </section>
        <AdminPrivateDeliveryPanel :user-id="selectedUserId" />
        <div class="admin-mod-panel">
          <h4>已绑定客户 Mod</h4>
          <div v-if="userModIds.length" class="admin-mod-chips">
            <span v-for="mid in userModIds" :key="mid" class="admin-mod-chip">
              {{ modLabel(mid) }}
              <small :class="['admin-mod-install', isModInstalled(mid) ? 'is-installed' : '']">
                {{ modInstallText(mid) }}
              </small>
              <button type="button" class="admin-mod-chip__remove" @click="unbindMod(mid)">×</button>
            </span>
          </div>
          <p v-else class="muted">尚未绑定客户 Mod</p>

          <h4>可分配 Mod</h4>
          <div class="admin-mod-assign">
            <select v-model="modToBind" class="admin-mod-select">
              <option value="">选择 Mod…</option>
              <option v-for="m in assignableMods" :key="m.id" :value="m.id" :disabled="userModIds.includes(m.id)">
                {{ m.name || m.id }} · {{ modInstallText(m.id) }}
              </option>
            </select>
            <button type="button" class="btn btn-secondary btn-sm" :disabled="!modToBind || binding" @click="bindMod">
              {{ binding ? '绑定中…' : '绑定' }}
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import AdminPrivateDeliveryPanel from '@/components/privateMod/AdminPrivateDeliveryPanel.vue'
import { INDUSTRY_PRESET_IDS } from '@/constants/industryPresets'
import {
  ACCOUNT_TIER_OPTIONS,
  BUDGET_RANGE_OPTIONS,
  CREDIT_QUICK_AMOUNTS,
  TIER_OPTIONS,
} from './admin-entitlements/types'
import { useAdminEntitlementsActions } from './admin-entitlements/useAdminEntitlementsActions'
import { useAdminEntitlementsState } from './admin-entitlements/useAdminEntitlementsState'

// 逻辑按领域拆分到 admin-entitlements/ 下的 composables，此处仅组装（模板与拆分前逐字一致）
const state = useAdminEntitlementsState()
const {
  users,
  assignableMods,
  selectedUserId,
  userModIds,
  userFilter,
  tierFilter,
  industryFilter,
  loadError,
  modToBind,
  binding,
  impersonateLoading,
  localStatusLoading,
  localStatusError,
  installedModIds,
  syncLastText,
  forcePushingEntitlements,
  walletMap,
  walletLoadError,
  profileEditing,
  profileSaving,
  createAccountOpen,
  creatingAccount,
  showNewAccountPassword,
  newAccount,
  creditingWallet,
  creditForm,
  selectedUser,
  isEnterpriseProfile,
  filteredUsers,
  tierStats,
  selectedMissingModIds,
  selectedWorkflowEmployees,
  selectedChainCards,
  resolveTier,
  tierLabel,
  modLabel,
  isModInstalled,
  modInstallText,
  walletBalance,
  normalizeLocalCatalogRows,
} = state

const {
  loadUsers,
  loadAssignable,
  loadWallets,
  refreshLocalStatus,
  generateTemporaryPassword,
  createAccount,
  setCreditAmount,
  creditSelectedWallet,
  forcePushSelectedEntitlements,
  selectUser,
  saveProfile,
  bindMod,
  unbindMod,
  toggleEnterprise,
  startImpersonate,
} = useAdminEntitlementsActions(state)

onMounted(async () => {
  try {
    await Promise.all([loadUsers(), loadAssignable(), refreshLocalStatus(), loadWallets()])
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<style scoped src="./admin-entitlements/admin-entitlements.css"></style>
