import { describe, expect, it, beforeEach } from 'vitest'
import {
  clearWorkbenchEphemeralStorage,
  getWorkbenchEphemeral,
  removeWorkbenchEphemeral,
  setWorkbenchEphemeral,
} from './workbenchEphemeralStorage'

describe('workbenchEphemeralStorage', () => {
  beforeEach(() => {
    clearWorkbenchEphemeralStorage()
  })

  it('stores and retrieves values in memory', () => {
    setWorkbenchEphemeral('wb_direct_chat_employee_id', 'excel-full-read-employee')
    expect(getWorkbenchEphemeral('wb_direct_chat_employee_id')).toBe('excel-full-read-employee')
  })

  it('remove clears a key', () => {
    setWorkbenchEphemeral('k', 'v')
    removeWorkbenchEphemeral('k')
    expect(getWorkbenchEphemeral('k')).toBeNull()
  })

  it('does not touch sessionStorage', () => {
    setWorkbenchEphemeral('secret', 'employee-id')
    expect(sessionStorage.getItem('secret')).toBeNull()
  })
})
