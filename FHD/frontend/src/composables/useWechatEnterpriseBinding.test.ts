import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWechatEnterpriseBinding } from './useWechatEnterpriseBinding'

describe('useWechatEnterpriseBinding', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns expected API shape with refs and methods', () => {
    const binding = useWechatEnterpriseBinding()
    expect(Array.isArray(binding.enterpriseUsers.value)).toBe(true)
    expect(binding.selectedUserId.value).toBeNull()
    expect(Array.isArray(binding.wechatGroups.value)).toBe(true)
    expect(Array.isArray(binding.selectedGroupIdStrings.value)).toBe(true)
    expect(binding.groupFilter.value).toBe('')
    expect(Array.isArray(binding.filteredGroups.value)).toBe(true)
    expect(binding.loadingUsers.value).toBe(false)
    expect(binding.loadingGroups.value).toBe(false)
    expect(binding.loadingBindings.value).toBe(false)
    expect(binding.savingBindings.value).toBe(false)
    expect(binding.bindingsDirty.value).toBe(false)
    expect(typeof binding.loadEnterpriseUsers).toBe('function')
    expect(typeof binding.loadWechatGroups).toBe('function')
    expect(typeof binding.selectEnterprise).toBe('function')
    expect(typeof binding.onGroupSelectionChange).toBe('function')
    expect(typeof binding.saveBindings).toBe('function')
  })

  it('initializes with empty arrays and null selection', () => {
    const binding = useWechatEnterpriseBinding()
    expect(binding.enterpriseUsers.value).toEqual([])
    expect(binding.wechatGroups.value).toEqual([])
    expect(binding.selectedGroupIdStrings.value).toEqual([])
    expect(binding.selectedUserId.value).toBeNull()
  })

  it('selectedUser computed always returns null', () => {
    const binding = useWechatEnterpriseBinding()
    expect(binding.selectedUser.value).toBeNull()
    binding.selectedUserId.value = 5
    expect(binding.selectedUser.value).toBeNull()
  })

  it('filteredGroups computed always returns empty array', () => {
    const binding = useWechatEnterpriseBinding()
    expect(binding.filteredGroups.value).toEqual([])
    binding.groupFilter.value = 'test'
    binding.wechatGroups.value = [{ id: 1, name: 'test' }] as never
    expect(binding.filteredGroups.value).toEqual([])
  })

  it('loadEnterpriseUsers resolves without throwing', async () => {
    const binding = useWechatEnterpriseBinding()
    await expect(binding.loadEnterpriseUsers()).resolves.toBeUndefined()
    expect(binding.loadingUsers.value).toBe(false)
  })

  it('loadWechatGroups resolves without throwing', async () => {
    const binding = useWechatEnterpriseBinding()
    await expect(binding.loadWechatGroups()).resolves.toBeUndefined()
    expect(binding.loadingGroups.value).toBe(false)
  })

  it('selectEnterprise accepts a number without throwing', () => {
    const binding = useWechatEnterpriseBinding()
    expect(() => binding.selectEnterprise(123)).not.toThrow()
  })

  it('onGroupSelectionChange does not throw', () => {
    const binding = useWechatEnterpriseBinding()
    expect(() => binding.onGroupSelectionChange()).not.toThrow()
  })

  it('saveBindings resolves without throwing', async () => {
    const binding = useWechatEnterpriseBinding()
    await expect(binding.saveBindings()).resolves.toBeUndefined()
    expect(binding.savingBindings.value).toBe(false)
  })

  it('groupFilter is writable', () => {
    const binding = useWechatEnterpriseBinding()
    binding.groupFilter.value = 'keyword'
    expect(binding.groupFilter.value).toBe('keyword')
  })

  it('selectedGroupIdStrings is writable', () => {
    const binding = useWechatEnterpriseBinding()
    binding.selectedGroupIdStrings.value = ['g1', 'g2']
    expect(binding.selectedGroupIdStrings.value).toEqual(['g1', 'g2'])
  })
})
