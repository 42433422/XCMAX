import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { appAlert } from '@/utils/appDialog'
import { apiFetch } from '@/utils/apiBase'
import type { AdminUser, AssignableMod, LocalProfile, WalletRow } from './types'
import type { AdminEntitlementsState } from './useAdminEntitlementsState'

// AdminEntitlementsView 的加载与操作逻辑（与拆分前逐字一致）
export function useAdminEntitlementsActions(state: AdminEntitlementsState) {
  const {
    users,
    assignableMods,
    selectedUserId,
    userModIds,
    modToBind,
    binding,
    impersonateLoading,
    localStatusLoading,
    localStatusError,
    installedMods,
    syncStatus,
    forcePushingEntitlements,
    walletMap,
    walletLoadError,
    userProfiles,
    userProfilesByMarketId,
    profileEditing,
    profileSaving,
    createAccountOpen,
    creatingAccount,
    showNewAccountPassword,
    newAccount,
    creditingWallet,
    creditForm,
    selectedUser,
    selectedInstalledMods,
    selectedWorkflowEmployees,
    normalizeLocalCatalogRows,
  } = state

  async function refreshLocalStatus() {
    localStatusLoading.value = true
    localStatusError.value = ''
    try {
      const catalogRes = await apiFetch('/api/mod-store/catalog')
      if (!catalogRes.ok) throw new Error(`本地 Mod 目录 HTTP ${catalogRes.status}`)
      installedMods.value = normalizeLocalCatalogRows(await catalogRes.json())
    } catch (e) {
      installedMods.value = []
      localStatusError.value = `本地安装状态读取失败：${e instanceof Error ? e.message : String(e)}`
    }
    try {
      const syncRes = await apiFetch('/api/xcmax/sync/status')
      if (!syncRes.ok) throw new Error(`同步状态 HTTP ${syncRes.status}`)
      const body = await syncRes.json()
      const data = body?.data && typeof body.data === 'object' ? body.data : body
      syncStatus.value = data as Record<string, unknown>
    } catch (e) {
      syncStatus.value = null
      const msg = `同步状态读取失败：${e instanceof Error ? e.message : String(e)}`
      localStatusError.value = localStatusError.value ? `${localStatusError.value}；${msg}` : msg
    } finally {
      localStatusLoading.value = false
    }
  }
  async function loadUsers() {
    const res = await xcmaxAdminApi.listUsers()
    const data = res as { users?: AdminUser[]; data?: { users?: AdminUser[] } }
    const list = data.users || data.data?.users || []
    // 稳定 ID 优先；旧数据库尚未绑定时才回退 username。
    try {
      const profRes = await xcmaxAdminApi.getUserProfiles()
      const profBody = profRes as {
        data?: Record<string, LocalProfile>
        by_market_user_id?: Record<string, LocalProfile>
      }
      const profiles = profBody.data || {}
      const profilesByMarketId = profBody.by_market_user_id || {}
      userProfiles.value = profiles
      userProfilesByMarketId.value = profilesByMarketId
      for (const u of list) {
        const p = profilesByMarketId[String(u.id)] || profiles[u.username]
        if (p) {
          u.tier = p.tier
          u.industry_id = p.industry_id
          u.account_tier = p.account_tier
          u.budget_range = p.budget_range
          u.entitled_industries = p.entitled_industries
        }
      }
    } catch {
      // profile 加载失败不阻断用户列表
    }
    users.value = list
  }

  async function loadAssignable() {
    const res = await xcmaxAdminApi.listAssignableMods()
    const data = res as { mods?: AssignableMod[]; data?: { mods?: AssignableMod[] } }
    assignableMods.value = data.mods || data.data?.mods || []
  }

  async function loadWallets() {
    walletLoadError.value = ''
    try {
      const res = await xcmaxAdminApi.listWallets()
      const body = res as { items?: WalletRow[]; data?: { items?: WalletRow[] } }
      const items = body.items || body.data?.items || []
      const m = new Map<number, WalletRow>()
      for (const w of items) {
        if (w && typeof w.user_id === 'number') m.set(w.user_id, w)
      }
      walletMap.value = m
    } catch (error) {
      // 钱包加载失败不阻断页面，但要与真实零余额明确区分。
      walletMap.value = new Map()
      walletLoadError.value = error instanceof Error ? error.message : String(error)
    }
  }

  function defaultEmailForUsername(username: string): string {
    const normalized = username.trim().toLowerCase()
    return normalized.includes('@') ? normalized : `${normalized}@xcagi.local`
  }

  function secureRandomIndex(limit: number): number {
    const values = new Uint32Array(1)
    window.crypto.getRandomValues(values)
    return Number(values[0] % limit)
  }

  function generateTemporaryPassword() {
    const pools = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '!@#$%*-_']
    const all = pools.join('')
    const chars = pools.map((pool) => pool[secureRandomIndex(pool.length)])
    while (chars.length < 16) chars.push(all[secureRandomIndex(all.length)])
    for (let i = chars.length - 1; i > 0; i -= 1) {
      const j = secureRandomIndex(i + 1)
      ;[chars[i], chars[j]] = [chars[j], chars[i]]
    }
    newAccount.value.password = chars.join('')
    showNewAccountPassword.value = true
  }

  async function applyProfileToUser(user: AdminUser, tier: string, industryId: string) {
    const entitled = industryId ? [industryId] : ['通用']
    await xcmaxAdminApi.setUserProfile(user.id, {
      username: user.username,
      tier,
      industry_id: industryId || '通用',
      entitled_industries: entitled,
    })
    user.tier = tier
    user.industry_id = industryId || '通用'
    user.entitled_industries = entitled
  }

  async function createAccount() {
    const username = newAccount.value.username.trim()
    const password = newAccount.value.password
    if (!username) {
      await appAlert('请填写用户名')
      return
    }
    if (password.length < 6) {
      await appAlert('密码至少 6 位')
      return
    }
    creatingAccount.value = true
    try {
      const email = newAccount.value.email.trim() || defaultEmailForUsername(username)
      await xcmaxAdminApi.createMarketUser({ username, password, email })
      await loadUsers()
      let created = users.value.find((u) => u.username === username)
      if (created) {
        if (created.is_enterprise !== newAccount.value.is_enterprise) {
          await xcmaxAdminApi.setUserEnterprise(created.id, newAccount.value.is_enterprise)
          created.is_enterprise = newAccount.value.is_enterprise
        }
        await applyProfileToUser(created, newAccount.value.tier, newAccount.value.industry_id)
        await loadUsers()
        created = users.value.find((u) => u.username === username) || created
        await selectUser(created)
      }
      await loadWallets()
      newAccount.value = {
        username: '',
        password: '',
        email: '',
        tier: 'enterprise',
        industry_id: '通用',
        is_enterprise: true,
      }
      showNewAccountPassword.value = false
      createAccountOpen.value = false
      await appAlert('账号已创建')
    } catch (e) {
      await appAlert(`创建失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      creatingAccount.value = false
    }
  }

  function setCreditAmount(amount: number) {
    creditForm.value.amount = amount
  }

  async function creditSelectedWallet() {
    if (!selectedUser.value) return
    const amount = Number(creditForm.value.amount)
    if (!Number.isFinite(amount) || amount <= 0) {
      await appAlert('加款金额必须大于 0')
      return
    }
    creditingWallet.value = true
    try {
      await xcmaxAdminApi.creditWallet(selectedUser.value.id, {
        amount,
        description: creditForm.value.description.trim() || '后台加款',
      })
      await loadWallets()
      await appAlert('加钱成功')
    } catch (e) {
      await appAlert(`加钱失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      creditingWallet.value = false
    }
  }

  async function forcePushSelectedEntitlements() {
    if (!selectedUser.value) return
    const user = selectedUser.value
    const entitled = [...profileEditing.value.entitled_industries]
    if (profileEditing.value.industry_id && !entitled.includes(profileEditing.value.industry_id)) {
      entitled.push(profileEditing.value.industry_id)
    }
    const isEnterprise = profileEditing.value.tier === 'enterprise'
    const wallet = walletMap.value.get(user.id) || null
    forcePushingEntitlements.value = true
    try {
      const res = await xcmaxAdminApi.forcePushUserEntitlements(user.id, {
        user: {
          id: user.id,
          username: user.username,
          email: user.email || '',
          is_admin: Boolean(user.is_admin),
          is_enterprise: Boolean(user.is_enterprise || isEnterprise),
          tier: profileEditing.value.tier,
          industry_id: profileEditing.value.industry_id,
        },
        profile: {
          tier: profileEditing.value.tier,
          industry_id: profileEditing.value.industry_id || '通用',
          account_tier: isEnterprise ? profileEditing.value.account_tier || '' : '',
          budget_range: profileEditing.value.budget_range || '',
          entitled_industries: entitled,
        },
        mod_ids: [...userModIds.value],
        wallet: wallet
          ? {
              id: wallet.id,
              user_id: wallet.user_id,
              balance: wallet.balance,
              updated_at: wallet.updated_at,
            }
          : null,
        workflow_employees: selectedWorkflowEmployees.value.map((emp) => ({
          id: emp.id,
          label: emp.label,
          mod_id: emp.modId,
          mod_name: emp.modName,
          summary: emp.summary,
        })),
        installed_mods: selectedInstalledMods.value.map((mod) => ({
          id: mod.id,
          name: mod.name,
          version: mod.version,
          is_installed: Boolean(mod.is_installed),
        })),
      })
      await refreshLocalStatus()
      const body = res as {
        data?: { push?: { sent?: number; failed?: number; total_pending?: number } }
      }
      const push = body.data?.push || {}
      const sent = Number(push.sent ?? 0)
      const failed = Number(push.failed ?? 0)
      await appAlert(`已强制推送企业端：发送 ${sent} 条，失败 ${failed} 条`)
    } catch (e) {
      await appAlert(`强制推送失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      forcePushingEntitlements.value = false
    }
  }

  async function selectUser(u: AdminUser) {
    selectedUserId.value = u.id
    modToBind.value = ''
    // 初始化等级/行业编辑态：无本地 profile 时按远端标志推断默认值
    profileEditing.value = {
      tier: u.tier || (u.is_admin ? 'admin' : u.is_enterprise ? 'enterprise' : 'personal'),
      industry_id: u.industry_id || '通用',
      account_tier: u.account_tier || '',
      budget_range: u.budget_range || '',
      entitled_industries: Array.isArray(u.entitled_industries) ? [...u.entitled_industries] : [],
    }
    try {
      const res = await xcmaxAdminApi.listUserMods(u.id)
      const data = res as { mod_ids?: string[]; data?: { mod_ids?: string[] } }
      userModIds.value = [...(data.mod_ids || data.data?.mod_ids || u.mod_ids || [])]
    } catch (e) {
      userModIds.value = [...(u.mod_ids || [])]
      await appAlert(`加载用户 Mod 失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  async function saveProfile() {
    if (!selectedUser.value) return
    profileSaving.value = true
    try {
      // 当前行业必须在已授权集合内（与后端校验一致）：自动并入避免 422
      const entitled = [...profileEditing.value.entitled_industries]
      if (profileEditing.value.industry_id && !entitled.includes(profileEditing.value.industry_id)) {
        entitled.push(profileEditing.value.industry_id)
      }
      const isEnterprise = profileEditing.value.tier === 'enterprise'
      await xcmaxAdminApi.setUserProfile(selectedUser.value.id, {
        username: selectedUser.value.username,
        tier: profileEditing.value.tier,
        industry_id: profileEditing.value.industry_id,
        account_tier: isEnterprise ? profileEditing.value.account_tier || undefined : undefined,
        budget_range: profileEditing.value.budget_range || undefined,
        entitled_industries: entitled,
      })
      selectedUser.value.tier = profileEditing.value.tier
      selectedUser.value.industry_id = profileEditing.value.industry_id
      selectedUser.value.account_tier = isEnterprise ? profileEditing.value.account_tier : ''
      selectedUser.value.budget_range = profileEditing.value.budget_range
      selectedUser.value.entitled_industries = entitled
      profileEditing.value.entitled_industries = entitled
      await appAlert('已保存')
    } catch (e) {
      await appAlert(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      profileSaving.value = false
    }
  }

  async function bindMod() {
    if (!selectedUserId.value || !modToBind.value) return
    binding.value = true
    try {
      await xcmaxAdminApi.bindUserMod(selectedUserId.value, modToBind.value)
      if (!userModIds.value.includes(modToBind.value)) {
        userModIds.value = [...userModIds.value, modToBind.value]
      }
      modToBind.value = ''
      await loadUsers()
      await appAlert('已绑定')
    } catch (e) {
      await appAlert(`绑定失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      binding.value = false
    }
  }

  async function unbindMod(modId: string) {
    if (!selectedUserId.value) return
    try {
      await xcmaxAdminApi.unbindUserMod(selectedUserId.value, modId)
      userModIds.value = userModIds.value.filter((id) => id !== modId)
      await loadUsers()
    } catch (e) {
      await appAlert(`解绑失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  async function toggleEnterprise(ev: Event) {
    if (!selectedUser.value) return
    const checked = (ev.target as HTMLInputElement).checked
    try {
      await xcmaxAdminApi.setUserEnterprise(selectedUser.value.id, checked)
      selectedUser.value.is_enterprise = checked
      await loadUsers()
    } catch (e) {
      await appAlert(`更新失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  async function startImpersonate() {
    if (!selectedUser.value) return
    impersonateLoading.value = true
    try {
      await xcmaxAdminApi.startImpersonate(selectedUser.value.id, selectedUser.value.username)
      const { useAccountProfileStore } = await import('@/stores/accountProfile')
      await useAccountProfileStore().refreshFromServer()
      await appAlert(`已进入代管：${selectedUser.value.username}`)
      window.location.href = '/'
    } catch (e) {
      await appAlert(`代管失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      impersonateLoading.value = false
    }
  }

  return {
    loadUsers,
    loadAssignable,
    loadWallets,
    refreshLocalStatus,
    generateTemporaryPassword,
    applyProfileToUser,
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
  }
}
