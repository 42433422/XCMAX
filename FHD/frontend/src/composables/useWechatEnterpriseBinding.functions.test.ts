import { describe, it, expect } from 'vitest'
import { useWechatEnterpriseBinding } from './useWechatEnterpriseBinding'

describe('useWechatEnterpriseBinding', () => {
  it('returns all expected reactive properties and methods', () => {
    const result = useWechatEnterpriseBinding()
    expect(result).toHaveProperty('enterpriseUsers')
    expect(result).toHaveProperty('selectedUserId')
    expect(result).toHaveProperty('selectedUser')
    expect(result).toHaveProperty('wechatGroups')
    expect(result).toHaveProperty('selectedGroupIdStrings')
    expect(result).toHaveProperty('groupFilter')
    expect(result).toHaveProperty('filteredGroups')
    expect(result).toHaveProperty('loadingUsers')
    expect(result).toHaveProperty('loadingGroups')
    expect(result).toHaveProperty('loadingBindings')
    expect(result).toHaveProperty('savingBindings')
    expect(result).toHaveProperty('bindingsDirty')
    expect(result).toHaveProperty('loadEnterpriseUsers')
    expect(result).toHaveProperty('loadWechatGroups')
    expect(result).toHaveProperty('selectEnterprise')
    expect(result).toHaveProperty('onGroupSelectionChange')
    expect(result).toHaveProperty('saveBindings')
  })

  it('initializes enterpriseUsers as empty array', () => {
    const { enterpriseUsers } = useWechatEnterpriseBinding()
    expect(enterpriseUsers.value).toEqual([])
  })

  it('initializes selectedUserId as null', () => {
    const { selectedUserId } = useWechatEnterpriseBinding()
    expect(selectedUserId.value).toBeNull()
  })

  it('initializes selectedUser computed as null', () => {
    const { selectedUser } = useWechatEnterpriseBinding()
    expect(selectedUser.value).toBeNull()
  })

  it('initializes wechatGroups as empty array', () => {
    const { wechatGroups } = useWechatEnterpriseBinding()
    expect(wechatGroups.value).toEqual([])
  })

  it('initializes selectedGroupIdStrings as empty array', () => {
    const { selectedGroupIdStrings } = useWechatEnterpriseBinding()
    expect(selectedGroupIdStrings.value).toEqual([])
  })

  it('initializes groupFilter as empty string', () => {
    const { groupFilter } = useWechatEnterpriseBinding()
    expect(groupFilter.value).toBe('')
  })

  it('initializes filteredGroups computed as empty array', () => {
    const { filteredGroups } = useWechatEnterpriseBinding()
    expect(filteredGroups.value).toEqual([])
  })

  it('initializes all loading flags as false', () => {
    const { loadingUsers, loadingGroups, loadingBindings, savingBindings } = useWechatEnterpriseBinding()
    expect(loadingUsers.value).toBe(false)
    expect(loadingGroups.value).toBe(false)
    expect(loadingBindings.value).toBe(false)
    expect(savingBindings.value).toBe(false)
  })

  it('initializes bindingsDirty as false', () => {
    const { bindingsDirty } = useWechatEnterpriseBinding()
    expect(bindingsDirty.value).toBe(false)
  })

  it('loadEnterpriseUsers resolves without throwing', async () => {
    const { loadEnterpriseUsers } = useWechatEnterpriseBinding()
    await expect(loadEnterpriseUsers()).resolves.toBeUndefined()
  })

  it('loadWechatGroups resolves without throwing', async () => {
    const { loadWechatGroups } = useWechatEnterpriseBinding()
    await expect(loadWechatGroups()).resolves.toBeUndefined()
  })

  it('selectEnterprise does not throw', () => {
    const { selectEnterprise } = useWechatEnterpriseBinding()
    expect(() => selectEnterprise(1)).not.toThrow()
  })

  it('onGroupSelectionChange does not throw', () => {
    const { onGroupSelectionChange } = useWechatEnterpriseBinding()
    expect(() => onGroupSelectionChange()).not.toThrow()
  })

  it('saveBindings resolves without throwing', async () => {
    const { saveBindings } = useWechatEnterpriseBinding()
    await expect(saveBindings()).resolves.toBeUndefined()
  })
})
