/** 通用 SKU：内部客服微信绑定见 admin-console */
import { ref, computed } from 'vue'

export function useWechatEnterpriseBinding() {
  const enterpriseUsers = ref<unknown[]>([])
  const selectedUserId = ref<number | null>(null)
  const selectedUser = computed(() => null)
  const wechatGroups = ref<unknown[]>([])
  const selectedGroupIdStrings = ref<string[]>([])
  const groupFilter = ref('')
  const filteredGroups = computed(() => [] as unknown[])
  const loadingUsers = ref(false)
  const loadingGroups = ref(false)
  const loadingBindings = ref(false)
  const savingBindings = ref(false)
  const bindingsDirty = ref(false)

  async function loadEnterpriseUsers() {}
  async function loadWechatGroups() {}
  function selectEnterprise(_id: number) {}
  function onGroupSelectionChange() {}
  async function saveBindings() {}

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
  }
}
