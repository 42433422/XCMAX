import { beforeEach, describe, expect, it } from 'vitest'
import {
  readActiveExtensionModIdFromStorage,
  writeActiveExtensionModIdToStorage,
} from './xcagiStorageKeys'

beforeEach(() => {
  localStorage.clear()
})

describe('xcagiStorageKeys', () => {
  it('round-trips active extension mod id', () => {
    writeActiveExtensionModIdToStorage('mod-a')
    expect(readActiveExtensionModIdFromStorage()).toBe('mod-a')
    writeActiveExtensionModIdToStorage('')
    expect(readActiveExtensionModIdFromStorage()).toBe('')
  })

})
