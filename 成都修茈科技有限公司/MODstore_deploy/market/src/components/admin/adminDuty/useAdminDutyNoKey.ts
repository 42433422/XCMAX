/**
 * 无密钥员工修复面板的数据与动作。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import type { Router } from 'vue-router'
import { api } from '../../../api'
import { isDeployedDutyRosterRow } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { AdminDutyData } from './useAdminDutyData'
import type { NoKeyRow, NoKeyResponse } from './adminDutyTypes'

export function useAdminDutyNoKey(s: AdminDutyState, data: AdminDutyData, ctx: { router: Router }) {
  const { router } = ctx
  const { employees, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow } = s
  const { loadPhase2, loadCapabilities } = data

async function loadNoKeyEmployees() {
  noKeyLoading.value = true
  noKeyError.value = ''
  try {
    const r = (await api.adminListNoKeyEmployees()) as NoKeyResponse
    noKeyData.value = r
  } catch (e: unknown) {
    noKeyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    noKeyLoading.value = false
  }
}


async function alignSingleEmployeeToAuto(row: NoKeyRow) {
  if (noKeyBusyRow.value[row.pkg_id]) return
  noKeyBusyRow.value = { ...noKeyBusyRow.value, [row.pkg_id]: true }
  try {
    await api.adminAlignSingleEmployeeLlmToAuto(row.pkg_id, false)
    await loadPhase2(employees.value.filter(isDeployedDutyRosterRow))
    await loadCapabilities(employees.value.filter(isDeployedDutyRosterRow))
    await loadNoKeyEmployees()
  } catch (e: unknown) {
    noKeyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    noKeyBusyRow.value = { ...noKeyBusyRow.value, [row.pkg_id]: false }
  }
}


function gotoAddKey() {
  router.push({ name: 'account', hash: '#api-keys' })
}


  return { loadNoKeyEmployees, alignSingleEmployeeToAuto, gotoAddKey }
}

export type AdminDutyNoKey = ReturnType<typeof useAdminDutyNoKey>
