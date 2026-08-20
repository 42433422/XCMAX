import { describe, expect, it, afterEach } from 'vitest'
import { readApprovalModFacadeEnabled, setApprovalModFacadeEnabled, LS_APPROVAL_MOD_FACADE_ENABLED } from './approvalMod'
import { readErpDomainModFacadeEnabled, setErpDomainModFacadeEnabled, LS_ERP_DOMAIN_MOD_FACADE_ENABLED } from './erpDomainMod'
import { readLanModFacadeEnabled, setLanModFacadeEnabled, LS_LAN_MOD_FACADE_ENABLED } from './lanMod'
import { readModelPaymentModFacadeEnabled, setModelPaymentModFacadeEnabled, LS_MODEL_PAYMENT_MOD_FACADE_ENABLED } from './modelPaymentMod'
import {
  readOfficeEmployeePackModPagesEnabled,
  setOfficeEmployeePackModPagesEnabled,
  LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED,
} from './officeEmployeePackMod'
import { readPlannerModFacadeEnabled, setPlannerModFacadeEnabled, LS_PLANNER_MOD_FACADE_ENABLED } from './plannerMod'

/**
 * 临时把 globalThis.localStorage 隐藏（模拟无 Storage 环境），
 * 以覆盖各 mod 常量 `typeof localStorage === 'undefined'` 的短路分支。
 */
function withoutLocalStorage(fn: () => void) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const hadOwn = !!descriptor
  try {
    Object.defineProperty(globalThis, 'localStorage', {
      value: undefined,
      configurable: true,
      writable: true,
    })
    fn()
  } finally {
    if (hadOwn && descriptor) {
      Object.defineProperty(globalThis, 'localStorage', descriptor)
    } else {
      // 自有属性被删除后，恢复对原型 getter 的访问

      delete (globalThis as any).localStorage
    }
  }
}

interface ModFacadeCase {
  name: string
  read: () => boolean
  set: (on: boolean) => void
  key: string
}

const cases: ModFacadeCase[] = [
  {
    name: 'approval',
    read: readApprovalModFacadeEnabled,
    set: setApprovalModFacadeEnabled,
    key: LS_APPROVAL_MOD_FACADE_ENABLED,
  },
  {
    name: 'erpDomain',
    read: readErpDomainModFacadeEnabled,
    set: setErpDomainModFacadeEnabled,
    key: LS_ERP_DOMAIN_MOD_FACADE_ENABLED,
  },
  {
    name: 'lan',
    read: readLanModFacadeEnabled,
    set: setLanModFacadeEnabled,
    key: LS_LAN_MOD_FACADE_ENABLED,
  },
  {
    name: 'modelPayment',
    read: readModelPaymentModFacadeEnabled,
    set: setModelPaymentModFacadeEnabled,
    key: LS_MODEL_PAYMENT_MOD_FACADE_ENABLED,
  },
  {
    name: 'officeEmployeePack',
    read: readOfficeEmployeePackModPagesEnabled,
    set: setOfficeEmployeePackModPagesEnabled,
    key: LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED,
  },
  {
    name: 'planner',
    read: readPlannerModFacadeEnabled,
    set: setPlannerModFacadeEnabled,
    key: LS_PLANNER_MOD_FACADE_ENABLED,
  },
]

describe.each(cases)('$name mod facade storage edge branches', ({ read, set, key }) => {
  afterEach(() => {
    try {
      localStorage.clear()
    } catch {
      /* storage may be hidden */
    }
  })

  it('returns false when localStorage is unavailable (reader)', () => {
    withoutLocalStorage(() => {
      expect(read()).toBe(false)
    })
  })

  it('returns false when localStorage.getItem throws', () => {
    const originalGetItem = Storage.prototype.getItem
    Storage.prototype.getItem = () => {
      throw new Error('storage denied')
    }
    try {
      expect(read()).toBe(false)
    } finally {
      Storage.prototype.getItem = originalGetItem
    }
  })

  it('is a no-op when localStorage is unavailable (setter)', () => {
    withoutLocalStorage(() => {
      expect(() => set(true)).not.toThrow()
    })
  })

  it('is a no-op when localStorage.setItem throws', () => {
    const originalSetItem = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new Error('quota exceeded')
    }
    try {
      expect(() => set(false)).not.toThrow()
    } finally {
      Storage.prototype.setItem = originalSetItem
    }
  })

  it('writes and reads through the exposed key', () => {
    set(true)
    expect(localStorage.getItem(key)).toBe('1')
    set(false)
    expect(read()).toBe(false)
  })
})
