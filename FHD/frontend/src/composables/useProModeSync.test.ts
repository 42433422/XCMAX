import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// useProModeSync 是从 useAppProMode 重新导出的 useAppProMode
// useAppProMode 需要 modsStore/router/route 参数，这里测试 re-export 行为
import { useProModeSync } from './useProModeSync'

describe('useProModeSync (re-export from useAppProMode)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('is a function (re-exported)', () => {
    expect(typeof useProModeSync).toBe('function')
  })
})
