<template>
  <div class="page-view admin-entitlements-view">
    <div class="page-content">
      <header class="admin-entitlements-head">
        <h2>用户管理</h2>
        <p class="muted">管理用户等级与行业，分配客户 Mod 权益，或进入代管模式代为配置。</p>
      </header>

      <div v-if="loadError" class="admin-entitlements-alert" role="alert">{{ loadError }}</div>

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

      <section class="admin-user-toolbar" aria-label="用户筛选">
        <div class="admin-user-toolbar__search">
          <input
            v-model="userFilter"
            type="search"
            class="admin-user-search"
            placeholder="搜索用户名 / 邮箱"
          >
        </div>
        <div class="admin-user-toolbar__filters">
          <select v-model="tierFilter" class="admin-user-filter-select" aria-label="按等级筛选">
            <option value="">全部等级</option>
            <option v-for="t in TIER_OPTIONS" :key="t.value" :value="t.value">
              {{ t.label }}（{{ tierStats[t.value] || 0 }}）
            </option>
          </select>
          <select v-model="industryFilter" class="admin-user-filter-select" aria-label="按行业筛选">
            <option value="">全部行业</option>
            <option v-for="id in INDUSTRY_PRESET_IDS" :key="id" :value="id">{{ id }}</option>
          </select>
          <span class="admin-user-toolbar__count muted">
            共 {{ filteredUsers.length }} / {{ users.length }} 人
          </span>
        </div>
      </section>

      <section v-if="filteredUsers.length" class="admin-user-grid" aria-label="用户卡片列表">
        <article
          v-for="u in filteredUsers"
          :key="u.id"
          class="admin-user-card"
          :class="[
            `admin-user-card--${resolveTier(u)}`,
            { active: selectedUserId === u.id },
          ]"
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
              <span
                class="admin-tier-tag"
                :class="`admin-tier-tag--${resolveTier(u)}`"
              >{{ tierLabel(u) }}</span>
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
              <input
                type="checkbox"
                :checked="selectedUser.is_enterprise"
                @change="toggleEnterprise($event)"
              >
              企业用户
            </label>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="impersonateLoading"
              @click="startImpersonate"
            >
              {{ impersonateLoading ? '进入中…' : '进入代管' }}
            </button>
          </div>
        </header>

        <section class="admin-user-profile" aria-label="用户账号体系">
          <div class="admin-user-profile__row">
            <label class="admin-user-profile__field">
              <span class="admin-user-profile__label">等级</span>
              <select v-model="profileEditing.tier" class="admin-user-profile__select">
                <option v-for="t in TIER_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}</option>
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
                <option v-for="t in ACCOUNT_TIER_OPTIONS" :key="t.value" :value="t.value">{{ t.label }}</option>
              </select>
            </label>
            <label v-if="isEnterpriseProfile" class="admin-user-profile__field">
              <span class="admin-user-profile__label">预算</span>
              <select v-model="profileEditing.budget_range" class="admin-user-profile__select">
                <option value="">未填</option>
                <option v-for="b in BUDGET_RANGE_OPTIONS" :key="b" :value="b">{{ b }}</option>
              </select>
            </label>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="profileSaving"
              @click="saveProfile"
            >
              {{ profileSaving ? '保存中…' : '保存' }}
            </button>
          </div>
          <div class="admin-user-profile__row admin-user-profile__entitled">
            <span class="admin-user-profile__label">已授权行业</span>
            <label
              v-for="id in INDUSTRY_PRESET_IDS"
              :key="id"
              class="admin-user-profile__chip"
            >
              <input type="checkbox" :value="id" v-model="profileEditing.entitled_industries" />
              <span>{{ id }}</span>
            </label>
          </div>
        </section>

        <section class="admin-entitlement-chain" aria-label="授权联动闭环">
          <div class="admin-entitlement-chain__intro">
            <div>
              <strong>账号 → Mod → AI 员工 → 设备执行</strong>
              <span class="muted">这里的绑定会决定企业端、手机端和信息页能看到并调用哪些员工。</span>
            </div>
            <div class="admin-chain-actions">
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
              <option
                v-for="m in assignableMods"
                :key="m.id"
                :value="m.id"
                :disabled="userModIds.includes(m.id)"
              >
                {{ m.name || m.id }} · {{ modInstallText(m.id) }}
              </option>
            </select>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="!modToBind || binding"
              @click="bindMod"
            >
              {{ binding ? '绑定中…' : '绑定' }}
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { xcmaxAdminApi } from '@/api/xcmaxAdmin';
import { appAlert } from '@/utils/appDialog';
import { apiFetch } from '@/utils/apiBase';
import { INDUSTRY_PRESET_IDS } from '@/constants/industryPresets';

type AdminUser = {
  id: number;
  username: string;
  email?: string;
  is_admin?: boolean;
  is_enterprise?: boolean;
  mod_ids?: string[];
  tier?: string;
  industry_id?: string;
  account_tier?: string;
  budget_range?: string;
  entitled_industries?: string[];
};

type LocalProfile = {
  tier: string;
  industry_id: string;
  account_tier?: string;
  budget_range?: string;
  entitled_industries?: string[];
};

type WalletRow = {
  id?: number;
  user_id?: number;
  balance?: number | string | null;
  updated_at?: string;
};

type AssignableMod = { id: string; name?: string };
type WorkflowEmployeeRow = {
  id?: string;
  label?: string;
  name?: string;
  title?: string;
  panel_title?: string;
  panel_summary?: string;
};
type LocalModRow = {
  id?: string;
  name?: string;
  version?: string;
  is_installed?: boolean;
  workflow_employees?: WorkflowEmployeeRow[];
};
type EntitlementEmployeePreview = {
  id: string;
  label: string;
  modId: string;
  modName: string;
  summary: string;
};

const users = ref<AdminUser[]>([]);
const assignableMods = ref<AssignableMod[]>([]);
const selectedUserId = ref<number | null>(null);
const userModIds = ref<string[]>([]);
const userFilter = ref('');
const tierFilter = ref('');
const industryFilter = ref('');
const loadError = ref('');
const modToBind = ref('');
const binding = ref(false);
const impersonateLoading = ref(false);
const localStatusLoading = ref(false);
const localStatusError = ref('');
const installedMods = ref<LocalModRow[]>([]);
const syncStatus = ref<Record<string, unknown> | null>(null);

// 用户钱包余额（远端 market /api/admin/wallets，按 user_id 索引）
const walletMap = ref<Map<number, WalletRow>>(new Map());

// 用户账号体系（本地持久化，按 username 合并远端用户列表）
const userProfiles = ref<Record<string, LocalProfile>>({});
const profileEditing = ref<{
  tier: string;
  industry_id: string;
  account_tier: string;
  budget_range: string;
  entitled_industries: string[];
}>({ tier: '', industry_id: '', account_tier: '', budget_range: '', entitled_industries: [] });
const profileSaving = ref(false);

const TIER_OPTIONS: { value: string; label: string }[] = [
  { value: 'personal', label: '个人' },
  { value: 'enterprise', label: '企业' },
  { value: 'admin', label: '管理员' },
];
const ACCOUNT_TIER_OPTIONS: { value: string; label: string }[] = [
  { value: 'normal', label: '普通' },
  { value: 'pro', label: 'Pro' },
  { value: 'max', label: 'Max' },
  { value: 'ultra', label: 'Ultra' },
];
const BUDGET_RANGE_OPTIONS = ['5 万以内', '5–20 万', '20–50 万', '50 万以上'];

function resolveTier(u: AdminUser): string {
  return u.tier || (u.is_admin ? 'admin' : u.is_enterprise ? 'enterprise' : 'personal');
}

function tierLabel(u: AdminUser): string {
  return TIER_OPTIONS.find((t) => t.value === resolveTier(u))?.label || '个人';
}

const selectedUser = computed(() =>
  users.value.find((u) => u.id === selectedUserId.value) || null,
);
// 账号等级仅企业用户可设
const isEnterpriseProfile = computed(() => profileEditing.value.tier === 'enterprise');

const filteredUsers = computed(() => {
  const q = userFilter.value.trim().toLowerCase();
  const tier = tierFilter.value;
  const industry = industryFilter.value;
  return users.value.filter((u) => {
    if (tier && resolveTier(u) !== tier) return false;
    if (industry && (u.industry_id || '通用') !== industry) return false;
    if (!q) return true;
    return (
      u.username.toLowerCase().includes(q) ||
      String(u.email || '')
        .toLowerCase()
        .includes(q)
    );
  });
});

const tierStats = computed(() => {
  const stats: Record<string, number> = { personal: 0, enterprise: 0, admin: 0 };
  for (const u of users.value) stats[resolveTier(u)] = (stats[resolveTier(u)] || 0) + 1;
  return stats;
});

const installedModMap = computed(() => {
  const m = new Map<string, LocalModRow>();
  for (const row of installedMods.value) {
    const id = String(row?.id || '').trim();
    if (id) m.set(id, row);
  }
  return m;
});

const installedModIds = computed(() => new Set(installedModMap.value.keys()));

const selectedInstalledMods = computed(() =>
  userModIds.value
    .map((id) => installedModMap.value.get(String(id || '').trim()))
    .filter((row): row is LocalModRow => Boolean(row)),
);

const selectedMissingModIds = computed(() =>
  userModIds.value.filter((id) => !installedModMap.value.has(String(id || '').trim())),
);

const selectedWorkflowEmployees = computed<EntitlementEmployeePreview[]>(() => {
  const seen = new Set<string>();
  const rows: EntitlementEmployeePreview[] = [];
  for (const mod of selectedInstalledMods.value) {
    const modId = String(mod.id || '').trim();
    const modName = modLabel(modId);
    for (const employee of mod.workflow_employees || []) {
      const id = String(employee?.id || '').trim();
      if (!id || seen.has(`${modId}:${id}`)) continue;
      seen.add(`${modId}:${id}`);
      rows.push({
        id,
        label: String(
          employee.label || employee.name || employee.title || employee.panel_title || id,
        ).trim(),
        modId,
        modName,
        summary: String(employee.panel_summary || '').trim(),
      });
    }
  }
  return rows;
});

const selectedChainCards = computed(() => {
  const modTotal = userModIds.value.length;
  const installedTotal = selectedInstalledMods.value.length;
  const employeeTotal = selectedWorkflowEmployees.value.length;
  return [
    {
      label: '账号权益',
      value: selectedUser.value?.is_enterprise ? '企业账号' : '普通账号',
      detail: `${modTotal} 个客户 Mod 权益`,
    },
    {
      label: '本机落地',
      value: `${installedTotal}/${modTotal} 可用`,
      detail: selectedMissingModIds.value.length ? '存在未安装 Mod' : '本机安装状态可用',
    },
    {
      label: '信息/手机',
      value: `${employeeTotal} 个员工`,
      detail: '进入信息页、员工空间和手机 AI 员工列表',
    },
    {
      label: '设备执行',
      value: employeeTotal ? '可派工' : '待补员工',
      detail: '手机可经局域网或服务器中继把任务派到电脑执行',
    },
  ];
});

const syncLastText = computed(() => {
  const raw = String(syncStatus.value?.last_sync_at || '').trim();
  if (!raw) return '';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString();
});

function modLabel(modId: string) {
  const hit = assignableMods.value.find((m) => m.id === modId);
  return hit?.name || modId;
}

function isModInstalled(modId: string) {
  return installedModMap.value.has(String(modId || '').trim());
}

function modInstallText(modId: string) {
  const row = installedModMap.value.get(String(modId || '').trim());
  if (!row) return '未安装';
  const version = String(row.version || '').trim();
  return version ? `已安装 v${version}` : '已安装';
}

function normalizeLocalCatalogRows(raw: Record<string, unknown>): LocalModRow[] {
  const data = (raw?.data && typeof raw.data === 'object' ? raw.data : raw) as Record<string, unknown>;
  const installed = Array.isArray(data.installed) ? data.installed : [];
  const available = Array.isArray(data.available) ? data.available : [];
  const byId = new Map<string, LocalModRow>();
  for (const row of [...available, ...installed]) {
    if (!row || typeof row !== 'object') continue;
    const r = row as LocalModRow;
    const id = String(r.id || '').trim();
    if (!id) continue;
    const prev = byId.get(id) || {};
    const installedFlag = Boolean(prev.is_installed || r.is_installed || installed.includes(row));
    byId.set(id, { ...prev, ...r, id, is_installed: installedFlag });
  }
  return Array.from(byId.values()).filter((row) => row.is_installed);
}

async function refreshLocalStatus() {
  localStatusLoading.value = true;
  localStatusError.value = '';
  try {
    const catalogRes = await apiFetch('/api/mod-store/catalog');
    if (!catalogRes.ok) throw new Error(`本地 Mod 目录 HTTP ${catalogRes.status}`);
    installedMods.value = normalizeLocalCatalogRows(await catalogRes.json());
  } catch (e) {
    installedMods.value = [];
    localStatusError.value = `本地安装状态读取失败：${e instanceof Error ? e.message : String(e)}`;
  }
  try {
    const syncRes = await apiFetch('/api/xcmax/sync/status');
    if (!syncRes.ok) throw new Error(`同步状态 HTTP ${syncRes.status}`);
    const body = await syncRes.json();
    const data = body?.data && typeof body.data === 'object' ? body.data : body;
    syncStatus.value = data as Record<string, unknown>;
  } catch (e) {
    syncStatus.value = null;
    const msg = `同步状态读取失败：${e instanceof Error ? e.message : String(e)}`;
    localStatusError.value = localStatusError.value ? `${localStatusError.value}；${msg}` : msg;
  } finally {
    localStatusLoading.value = false;
  }
}

async function loadUsers() {
  const res = await xcmaxAdminApi.listUsers();
  const data = res as { users?: AdminUser[]; data?: { users?: AdminUser[] } };
  const list = data.users || data.data?.users || [];
  // 合并本地 tier/industry_id（按 username 匹配）
  try {
    const profRes = await xcmaxAdminApi.getUserProfiles();
    const profBody = profRes as { data?: Record<string, LocalProfile> };
    const profiles = profBody.data || {};
    userProfiles.value = profiles;
    for (const u of list) {
      const p = profiles[u.username];
      if (p) {
        u.tier = p.tier;
        u.industry_id = p.industry_id;
        u.account_tier = p.account_tier;
        u.budget_range = p.budget_range;
        u.entitled_industries = p.entitled_industries;
      }
    }
  } catch {
    // profile 加载失败不阻断用户列表
  }
  users.value = list;
}

async function loadAssignable() {
  const res = await xcmaxAdminApi.listAssignableMods();
  const data = res as { mods?: AssignableMod[]; data?: { mods?: AssignableMod[] } };
  assignableMods.value = data.mods || data.data?.mods || [];
}

async function loadWallets() {
  try {
    const res = await xcmaxAdminApi.listWallets();
    const body = res as { items?: WalletRow[]; data?: { items?: WalletRow[] } };
    const items = body.items || body.data?.items || [];
    const m = new Map<number, WalletRow>();
    for (const w of items) {
      if (w && typeof w.user_id === 'number') m.set(w.user_id, w);
    }
    walletMap.value = m;
  } catch {
    // 钱包加载失败不阻断页面
    walletMap.value = new Map();
  }
}

function walletBalance(u: AdminUser): string {
  const w = walletMap.value.get(u.id);
  if (!w || w.balance === null || w.balance === undefined) return '—';
  const n = typeof w.balance === 'string' ? parseFloat(w.balance) : w.balance;
  if (Number.isNaN(n)) return '—';
  return `¥${n.toFixed(2)}`;
}

async function selectUser(u: AdminUser) {
  selectedUserId.value = u.id;
  modToBind.value = '';
  // 初始化等级/行业编辑态：无本地 profile 时按远端标志推断默认值
  profileEditing.value = {
    tier: u.tier || (u.is_admin ? 'admin' : u.is_enterprise ? 'enterprise' : 'personal'),
    industry_id: u.industry_id || '通用',
    account_tier: u.account_tier || '',
    budget_range: u.budget_range || '',
    entitled_industries: Array.isArray(u.entitled_industries) ? [...u.entitled_industries] : [],
  };
  try {
    const res = await xcmaxAdminApi.listUserMods(u.id);
    const data = res as { mod_ids?: string[]; data?: { mod_ids?: string[] } };
    userModIds.value = [...(data.mod_ids || data.data?.mod_ids || u.mod_ids || [])];
  } catch (e) {
    userModIds.value = [...(u.mod_ids || [])];
    await appAlert(`加载用户 Mod 失败：${e instanceof Error ? e.message : String(e)}`);
  }
}

async function saveProfile() {
  if (!selectedUser.value) return;
  profileSaving.value = true;
  try {
    // 当前行业必须在已授权集合内（与后端校验一致）：自动并入避免 422
    const entitled = [...profileEditing.value.entitled_industries];
    if (
      profileEditing.value.industry_id &&
      !entitled.includes(profileEditing.value.industry_id)
    ) {
      entitled.push(profileEditing.value.industry_id);
    }
    const isEnterprise = profileEditing.value.tier === 'enterprise';
    await xcmaxAdminApi.setUserProfile(selectedUser.value.id, {
      username: selectedUser.value.username,
      tier: profileEditing.value.tier,
      industry_id: profileEditing.value.industry_id,
      account_tier: isEnterprise ? profileEditing.value.account_tier || undefined : undefined,
      budget_range: profileEditing.value.budget_range || undefined,
      entitled_industries: entitled,
    });
    selectedUser.value.tier = profileEditing.value.tier;
    selectedUser.value.industry_id = profileEditing.value.industry_id;
    selectedUser.value.account_tier = isEnterprise ? profileEditing.value.account_tier : '';
    selectedUser.value.budget_range = profileEditing.value.budget_range;
    selectedUser.value.entitled_industries = entitled;
    profileEditing.value.entitled_industries = entitled;
    await appAlert('已保存');
  } catch (e) {
    await appAlert(`保存失败：${e instanceof Error ? e.message : String(e)}`);
  } finally {
    profileSaving.value = false;
  }
}

async function bindMod() {
  if (!selectedUserId.value || !modToBind.value) return;
  binding.value = true;
  try {
    await xcmaxAdminApi.bindUserMod(selectedUserId.value, modToBind.value);
    if (!userModIds.value.includes(modToBind.value)) {
      userModIds.value = [...userModIds.value, modToBind.value];
    }
    modToBind.value = '';
    await loadUsers();
    await appAlert('已绑定');
  } catch (e) {
    await appAlert(`绑定失败：${e instanceof Error ? e.message : String(e)}`);
  } finally {
    binding.value = false;
  }
}

async function unbindMod(modId: string) {
  if (!selectedUserId.value) return;
  try {
    await xcmaxAdminApi.unbindUserMod(selectedUserId.value, modId);
    userModIds.value = userModIds.value.filter((id) => id !== modId);
    await loadUsers();
  } catch (e) {
    await appAlert(`解绑失败：${e instanceof Error ? e.message : String(e)}`);
  }
}

async function toggleEnterprise(ev: Event) {
  if (!selectedUser.value) return;
  const checked = (ev.target as HTMLInputElement).checked;
  try {
    await xcmaxAdminApi.setUserEnterprise(selectedUser.value.id, checked);
    selectedUser.value.is_enterprise = checked;
    await loadUsers();
  } catch (e) {
    await appAlert(`更新失败：${e instanceof Error ? e.message : String(e)}`);
  }
}

async function startImpersonate() {
  if (!selectedUser.value) return;
  impersonateLoading.value = true;
  try {
    await xcmaxAdminApi.startImpersonate(selectedUser.value.id, selectedUser.value.username);
    const { useAccountProfileStore } = await import('@/stores/accountProfile');
    await useAccountProfileStore().refreshFromServer();
    await appAlert(`已进入代管：${selectedUser.value.username}`);
    window.location.href = '/';
  } catch (e) {
    await appAlert(`代管失败：${e instanceof Error ? e.message : String(e)}`);
  } finally {
    impersonateLoading.value = false;
  }
}

onMounted(async () => {
  try {
    await Promise.all([loadUsers(), loadAssignable(), refreshLocalStatus(), loadWallets()]);
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  }
});
</script>

<style scoped>
.admin-entitlements-view .page-content {
  padding: 20px 24px 40px;
  width: 100%;
  max-width: none;
  margin: 0;
}

.admin-entitlements-head h2 {
  margin: 0 0 6px;
}

.admin-entitlements-alert {
  margin: 12px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.admin-entitlements-alert--soft {
  color: #455a64;
  background: #eef3f7;
  border-color: #d6e0e8;
}

.admin-sync-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 12px 0 16px;
  padding: 12px 14px;
  border: 1px solid #dce3eb;
  border-radius: 8px;
  background: #f8fafc;
}

/* 顶部筛选工具栏 */
.admin-user-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 16px 0;
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
}

.admin-user-toolbar__search {
  flex: 1 1 240px;
  min-width: 200px;
}

.admin-user-toolbar__filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.admin-user-search {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  background: #f8fafc;
}

.admin-user-search:focus {
  outline: none;
  border-color: #1e3a5f;
  background: #fff;
}

.admin-user-filter-select {
  padding: 6px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  background: #fff;
  min-width: 110px;
}

.admin-user-toolbar__count {
  font-size: 12px;
  white-space: nowrap;
}

/* 卡片网格 */
.admin-user-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.admin-user-grid__empty {
  padding: 32px 12px;
  text-align: center;
  border: 1px dashed #d6e0e8;
  border-radius: 12px;
  background: #f8fafc;
  margin-bottom: 20px;
}

.admin-user-card {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
  outline: none;
}

.admin-user-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
  border-color: #cbd5e1;
}

.admin-user-card:focus-visible {
  border-color: #1e3a5f;
  box-shadow: 0 0 0 3px rgba(30, 58, 95, 0.18);
}

.admin-user-card.active {
  border-color: #1e3a5f;
  box-shadow: 0 0 0 2px rgba(30, 58, 95, 0.25);
}

.admin-user-card__bar {
  height: 4px;
  width: 100%;
  background: #64748b;
}

.admin-user-card--personal .admin-user-card__bar { background: #64748b; }
.admin-user-card--enterprise .admin-user-card__bar { background: #1e3a5f; }
.admin-user-card--admin .admin-user-card__bar { background: #92400e; }

.admin-user-card__body {
  padding: 12px 14px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}

.admin-user-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.admin-user-card__name {
  font-weight: 600;
  font-size: 15px;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-user-card__meta {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.admin-user-card__row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
}

.admin-user-card__row dt {
  color: #94a3b8;
  min-width: 32px;
  margin: 0;
}

.admin-user-card__row dd {
  margin: 0;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-user-card__row--email dd {
  color: #64748b;
  font-size: 11px;
}

.admin-user-card__row--balance dd {
  color: #16803c;
  font-weight: 600;
  font-size: 13px;
}

.admin-user-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px dashed #e5e7eb;
  font-size: 11px;
}

.admin-user-card__badge {
  padding: 1px 6px;
  border-radius: 3px;
  background: #1e3a5f;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
}

/* 用户等级标签 */
.admin-tier-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
}
.admin-tier-tag--personal { background: #64748b; }
.admin-tier-tag--enterprise { background: #1e3a5f; }
.admin-tier-tag--admin { background: #92400e; }

/* 详情区 */
.admin-user-detail {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  padding: 16px 18px;
}

.admin-user-detail__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.admin-user-detail__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.admin-flag {
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* 用户等级/行业编辑区 */
.admin-user-profile {
  margin-bottom: 16px;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 6px;
}
.admin-user-profile__row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}
.admin-user-profile__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.admin-user-profile__label {
  font-size: 12px;
  color: #64748b;
}
.admin-user-profile__select {
  padding: 4px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 13px;
  background: #fff;
  min-width: 100px;
}
.admin-user-profile__entitled {
  margin-top: 10px;
  align-items: center;
}
.admin-user-profile__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  font-size: 12px;
  color: #334155;
  background: #fff;
  cursor: pointer;
}
.admin-user-profile__chip input {
  margin: 0;
}

.admin-entitlement-chain {
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid #dce7f5;
  border-radius: 12px;
  background: #f8fbff;
}

.admin-entitlement-chain__intro {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.admin-entitlement-chain__intro strong,
.admin-entitlement-chain__intro span {
  display: block;
}

.admin-chain-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.admin-chain-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.admin-chain-card {
  min-width: 0;
  padding: 10px;
  border: 1px solid #dbe6f3;
  border-radius: 8px;
  background: #fff;
}

.admin-chain-card span,
.admin-chain-card small {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.admin-chain-card strong {
  display: block;
  margin: 4px 0;
  color: #111827;
  font-size: 15px;
}

.admin-chain-warning {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 12px;
}

.admin-chain-employees {
  margin-top: 12px;
}

.admin-chain-employees__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.admin-chain-employee-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.admin-chain-employee-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 5px 8px;
  border-radius: 8px;
  background: #eef6ff;
  color: #1d4ed8;
  font-size: 12px;
}

.admin-chain-employee-chip small {
  color: #64748b;
}

.admin-chain-empty {
  margin: 0;
  font-size: 12px;
}

.admin-mod-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 16px;
}

.admin-mod-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
}

.admin-mod-install {
  color: #8a94a6;
  font-size: 11px;
}

.admin-mod-install.is-installed {
  color: #16803c;
}

.admin-mod-chip__remove {
  border: none;
  background: transparent;
  cursor: pointer;
  color: #64748b;
  font-size: 14px;
  line-height: 1;
}

.admin-mod-assign {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}

.admin-mod-select {
  flex: 1;
  min-height: 34px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  padding: 0 10px;
}

@media (max-width: 900px) {
  .admin-user-grid {
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  }

  .admin-chain-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .admin-entitlement-chain__intro {
    flex-direction: column;
  }
}

@media (max-width: 600px) {
  .admin-user-grid {
    grid-template-columns: 1fr;
  }
}
</style>
