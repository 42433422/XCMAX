<template>
  <div class="page-view admin-entitlements-view">
    <div class="page-content">
      <header class="admin-entitlements-head">
        <h2>用户 Mod 管理</h2>
        <p class="muted">为市场用户分配客户 Mod 权益，或进入代管模式代为配置。</p>
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

      <div class="admin-entitlements-layout">
        <aside class="admin-user-list">
          <div class="admin-user-list__toolbar">
            <input
              v-model="userFilter"
              type="search"
              class="admin-user-search"
              placeholder="搜索用户名 / 邮箱"
            >
          </div>
          <ul v-if="filteredUsers.length" class="admin-user-list__items">
            <li
              v-for="u in filteredUsers"
              :key="u.id"
              class="admin-user-row"
              :class="{ active: selectedUserId === u.id }"
            >
              <button type="button" class="admin-user-row__btn" @click="selectUser(u)">
                <span class="admin-user-row__name">{{ u.username }}</span>
                <span class="admin-user-row__meta muted">
                  <span v-if="u.is_admin">管理员</span>
                  <span v-else-if="u.is_enterprise">企业</span>
                  <span v-else>普通</span>
                  · {{ (u.mod_ids || []).length }} Mod
                </span>
              </button>
            </li>
          </ul>
          <p v-else class="muted admin-user-list__empty">暂无用户</p>
        </aside>

        <section v-if="selectedUser" class="admin-user-detail">
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

        <section v-else class="admin-user-detail admin-user-detail--empty muted">
          请选择左侧用户
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { xcmaxAdminApi } from '@/api/xcmaxAdmin';
import { appAlert } from '@/utils/appDialog';
import { apiFetch } from '@/utils/apiBase';

type AdminUser = {
  id: number;
  username: string;
  email?: string;
  is_admin?: boolean;
  is_enterprise?: boolean;
  mod_ids?: string[];
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
const loadError = ref('');
const modToBind = ref('');
const binding = ref(false);
const impersonateLoading = ref(false);
const localStatusLoading = ref(false);
const localStatusError = ref('');
const installedMods = ref<LocalModRow[]>([]);
const syncStatus = ref<Record<string, unknown> | null>(null);

const selectedUser = computed(() =>
  users.value.find((u) => u.id === selectedUserId.value) || null,
);

const filteredUsers = computed(() => {
  const q = userFilter.value.trim().toLowerCase();
  if (!q) return users.value;
  return users.value.filter(
    (u) =>
      u.username.toLowerCase().includes(q) ||
      String(u.email || '')
        .toLowerCase()
        .includes(q),
  );
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
  users.value = data.users || data.data?.users || [];
}

async function loadAssignable() {
  const res = await xcmaxAdminApi.listAssignableMods();
  const data = res as { mods?: AssignableMod[]; data?: { mods?: AssignableMod[] } };
  assignableMods.value = data.mods || data.data?.mods || [];
}

async function selectUser(u: AdminUser) {
  selectedUserId.value = u.id;
  modToBind.value = '';
  try {
    const res = await xcmaxAdminApi.listUserMods(u.id);
    const data = res as { mod_ids?: string[]; data?: { mod_ids?: string[] } };
    userModIds.value = [...(data.mod_ids || data.data?.mod_ids || u.mod_ids || [])];
  } catch (e) {
    userModIds.value = [...(u.mod_ids || [])];
    await appAlert(`加载用户 Mod 失败：${e instanceof Error ? e.message : String(e)}`);
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
    await Promise.all([loadUsers(), loadAssignable(), refreshLocalStatus()]);
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  }
});
</script>

<style scoped>
.admin-entitlements-view .page-content {
  padding: 20px 24px 40px;
  max-width: 1100px;
  margin: 0 auto;
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

.admin-entitlements-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  margin-top: 16px;
  min-height: 420px;
}

.admin-user-list {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
}

.admin-user-search {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: none;
  border-bottom: 1px solid #e5e7eb;
  font-size: 13px;
}

.admin-user-list__items {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 520px;
  overflow-y: auto;
}

.admin-user-row__btn {
  width: 100%;
  text-align: left;
  padding: 10px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
}

.admin-user-row.active .admin-user-row__btn,
.admin-user-row__btn:hover {
  background: #f3f4f6;
}

.admin-user-row__name {
  display: block;
  font-weight: 600;
  font-size: 14px;
}

.admin-user-row__meta {
  font-size: 12px;
}

.admin-user-detail {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  padding: 16px 18px;
}

.admin-user-detail--empty {
  display: flex;
  align-items: center;
  justify-content: center;
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
  .admin-entitlements-layout {
    grid-template-columns: 1fr;
  }

  .admin-chain-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .admin-entitlement-chain__intro {
    flex-direction: column;
  }
}
</style>
