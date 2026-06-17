import { describe, expect, it } from 'vitest'

import {
  consumePlannerChatDbWriteTokenArm,
  isPlannerChatDbWriteTokenArmed,
  readStoredDbTokensForMod,
  saveStoredDbTokensForMod,
} from '@/fhd/dbTokenHeaders'

describe('dbTokenHeaders enhanced compatibility', () => {
  it('keeps per-mod and planner token arms inert', () => {
    saveStoredDbTokensForMod('mod-a', 'read', 'write')
    expect(readStoredDbTokensForMod('mod-a')).toEqual({ read: '', write: '' })
    expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
    consumePlannerChatDbWriteTokenArm()
    expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
  })
})
