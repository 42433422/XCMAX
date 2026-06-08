import { ref, computed } from 'vue';
import { get } from '@/api';
import { xcmaxAdminApi } from '@/api/xcmaxAdmin';

const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge/user-cs/clients';

export type WechatGroupRow = {
  id: number;
  contact_name?: string;
  remark?: string;
  wechat_id?: string;
  contact_type?: string;
  is_starred?: boolean;
};

export type EnterpriseCustomerRow = {
  id: number;
  username: string;
  email?: string;
  isEnterprise: boolean;
  hasPipeline: boolean;
  bindingCount?: number;
};

type MarketUserRaw = {
  id: number;
  username: string;
  email?: string;
  is_enterprise?: boolean;
};

type BindingRaw = {
  wechat_contact_id?: number;
  binding_id?: number;
};

function normalizeUsersPayload(res: unknown): MarketUserRaw[] {
  const data = res as {
    users?: MarketUserRaw[];
    data?: { users?: MarketUserRaw[] };
  };
  return data.users || data.data?.users || [];
}

function normalizeGroupsPayload(res: unknown): WechatGroupRow[] {
  const data = res as { data?: WechatGroupRow[]; success?: boolean };
  const rows = data.data;
  return Array.isArray(rows) ? rows : [];
}

function normalizeBindingsPayload(res: unknown): BindingRaw[] {
  const data = res as { data?: BindingRaw[] };
  const rows = data.data;
  return Array.isArray(rows) ? rows : [];
}

export function useWechatEnterpriseBinding() {
  const enterpriseUsers = ref<EnterpriseCustomerRow[]>([]);
  const selectedUserId = ref<number | null>(null);
  const wechatGroups = ref<WechatGroupRow[]>([]);
  const selectedGroupIdStrings = ref<string[]>([]);
  const groupFilter = ref('');
  const loadingUsers = ref(false);
  const loadingGroups = ref(false);
  const loadingBindings = ref(false);
  const savingBindings = ref(false);
  const bindingsDirty = ref(false);

  const selectedUser = computed(() => {
    const id = selectedUserId.value;
    if (id == null) return null;
    return enterpriseUsers.value.find((u) => u.id === id) ?? null;
  });

  const filteredGroups = computed(() => {
    const q = groupFilter.value.trim().toLowerCase();
    if (!q) return wechatGroups.value;
    return wechatGroups.value.filter((g) => {
      const name = String(g.contact_name || '').toLowerCase();
      const remark = String(g.remark || '').toLowerCase();
      return name.includes(q) || remark.includes(q);
    });
  });

  function setUserBindingCount(userId: number, count: number) {
    const row = enterpriseUsers.value.find((u) => u.id === userId);
    if (row) row.bindingCount = count;
  }

  async function loadEnterpriseUsers() {
    loadingUsers.value = true;
    try {
      const [adminRes, clientsRes] = await Promise.all([
        xcmaxAdminApi.listUsers(),
        get<{ data?: { clients?: Array<{ market_user_id: number }> } }>(CS_BRIDGE),
      ]);
      const users = normalizeUsersPayload(adminRes);
      const pipelineIds = new Set(
        (clientsRes?.data?.clients || [])
          .map((c) => Number(c.market_user_id))
          .filter((id) => id > 0),
      );
      enterpriseUsers.value = users
        .filter((u) => Boolean(u.is_enterprise) || pipelineIds.has(u.id))
        .map((u) => ({
          id: u.id,
          username: u.username,
          email: u.email,
          isEnterprise: Boolean(u.is_enterprise),
          hasPipeline: pipelineIds.has(u.id),
          bindingCount: undefined as number | undefined,
        }))
        .sort((a, b) => a.username.localeCompare(b.username, 'zh-CN'));
    } finally {
      loadingUsers.value = false;
    }
  }

  async function loadWechatGroups() {
    loadingGroups.value = true;
    try {
      const res = await xcmaxAdminApi.listWechatGroups({ limit: 200 });
      wechatGroups.value = normalizeGroupsPayload(res);
    } finally {
      loadingGroups.value = false;
    }
  }

  async function selectEnterprise(id: number) {
    selectedUserId.value = id;
    loadingBindings.value = true;
    bindingsDirty.value = false;
    try {
      const res = await xcmaxAdminApi.getUserWechatBindings(id);
      const bindings = normalizeBindingsPayload(res);
      const ids = bindings
        .map((b) => b.wechat_contact_id)
        .filter((cid): cid is number => typeof cid === 'number' && cid > 0);
      selectedGroupIdStrings.value = ids.map(String);
      setUserBindingCount(id, ids.length);
    } catch {
      selectedGroupIdStrings.value = [];
      setUserBindingCount(id, 0);
    } finally {
      loadingBindings.value = false;
    }
  }

  function onGroupSelectionChange() {
    bindingsDirty.value = true;
  }

  async function saveBindings() {
    const userId = selectedUserId.value;
    if (userId == null) return;
    const contactIds = selectedGroupIdStrings.value
      .map((s) => parseInt(s, 10))
      .filter((n) => Number.isFinite(n) && n > 0);
    savingBindings.value = true;
    try {
      await xcmaxAdminApi.saveUserWechatBindings(userId, contactIds);
      setUserBindingCount(userId, contactIds.length);
      bindingsDirty.value = false;
    } finally {
      savingBindings.value = false;
    }
  }

  return {
    enterpriseUsers,
    selectedUserId,
    selectedUser,
    wechatGroups,
    selectedGroupIdStrings,
    groupFilter,
    filteredGroups,
    loadingUsers,
    loadingGroups,
    loadingBindings,
    savingBindings,
    bindingsDirty,
    loadEnterpriseUsers,
    loadWechatGroups,
    selectEnterprise,
    onGroupSelectionChange,
    saveBindings,
  };
}
