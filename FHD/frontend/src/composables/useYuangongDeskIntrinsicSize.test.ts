import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useYuangongDeskIntrinsicSize } from './useYuangongDeskIntrinsicSize'

describe('useYuangongDeskIntrinsicSize', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns expected API shape', () => {
    const { deskW, deskH, deskIntrinsicReady } = useYuangongDeskIntrinsicSize()
    expect(typeof deskW.value).toBe('number')
    expect(typeof deskH.value).toBe('number')
    expect(deskIntrinsicReady.value).toBe(false)
  })

  it('initializes with default canvas dimensions', () => {
    const { deskW, deskH } = useYuangongDeskIntrinsicSize()
    // YUANGONG_CANVAS_W=96, YUANGONG_CANVAS_H=64
    expect(deskW.value).toBe(96)
    expect(deskH.value).toBe(64)
  })

  it('deskIntrinsicReady starts as false', () => {
    const { deskIntrinsicReady } = useYuangongDeskIntrinsicSize()
    expect(deskIntrinsicReady.value).toBe(false)
  })
})
