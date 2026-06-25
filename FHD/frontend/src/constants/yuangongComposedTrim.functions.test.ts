import { describe, it, expect } from 'vitest'
import {
  YUANGONG_CANVAS_W,
  YUANGONG_CANVAS_H,
  YUANGONG_COMPOSED_TRIM,
  yuangongComposedBaseSize,
  yuangongComposedBaseSizeFromCanvas,
} from './yuangongComposedTrim'

describe('yuangongComposedTrim constants and functions', () => {
  describe('YUANGONG_CANVAS_W and YUANGONG_CANVAS_H', () => {
    it('canvas width is 96', () => {
      expect(YUANGONG_CANVAS_W).toBe(96)
    })

    it('canvas height is 64', () => {
      expect(YUANGONG_CANVAS_H).toBe(64)
    })

    it('canvas dimensions are positive numbers', () => {
      expect(YUANGONG_CANVAS_W).toBeGreaterThan(0)
      expect(YUANGONG_CANVAS_H).toBeGreaterThan(0)
    })
  })

  describe('YUANGONG_COMPOSED_TRIM', () => {
    it('has all four trim sides', () => {
      expect(YUANGONG_COMPOSED_TRIM).toHaveProperty('left')
      expect(YUANGONG_COMPOSED_TRIM).toHaveProperty('right')
      expect(YUANGONG_COMPOSED_TRIM).toHaveProperty('top')
      expect(YUANGONG_COMPOSED_TRIM).toHaveProperty('bottom')
    })

    it('default trim values are all zero', () => {
      expect(YUANGONG_COMPOSED_TRIM.left).toBe(0)
      expect(YUANGONG_COMPOSED_TRIM.right).toBe(0)
      expect(YUANGONG_COMPOSED_TRIM.top).toBe(0)
      expect(YUANGONG_COMPOSED_TRIM.bottom).toBe(0)
    })
  })

  describe('yuangongComposedBaseSize', () => {
    it('returns default canvas dimensions with zero trim', () => {
      const size = yuangongComposedBaseSize()
      expect(size.width).toBe(YUANGONG_CANVAS_W)
      expect(size.height).toBe(YUANGONG_CANVAS_H)
    })

    it('returns 96x64 by default', () => {
      const size = yuangongComposedBaseSize()
      expect(size).toEqual({ width: 96, height: 64 })
    })

    it('returns positive dimensions', () => {
      const size = yuangongComposedBaseSize()
      expect(size.width).toBeGreaterThan(0)
      expect(size.height).toBeGreaterThan(0)
    })
  })

  describe('yuangongComposedBaseSizeFromCanvas', () => {
    it('returns dimensions matching input canvas when trim is zero', () => {
      const size = yuangongComposedBaseSizeFromCanvas(100, 80)
      expect(size).toEqual({ width: 100, height: 80 })
    })

    it('handles default canvas dimensions', () => {
      const size = yuangongComposedBaseSizeFromCanvas(96, 64)
      expect(size).toEqual({ width: 96, height: 64 })
    })

    it('handles zero width input by clamping to minimum 1', () => {
      const size = yuangongComposedBaseSizeFromCanvas(0, 50)
      expect(size.width).toBe(1)
      expect(size.height).toBe(50)
    })

    it('handles zero height input by clamping to minimum 1', () => {
      const size = yuangongComposedBaseSizeFromCanvas(50, 0)
      expect(size.width).toBe(50)
      expect(size.height).toBe(1)
    })

    it('handles both zero dimensions by clamping to minimum 1', () => {
      const size = yuangongComposedBaseSizeFromCanvas(0, 0)
      expect(size).toEqual({ width: 1, height: 1 })
    })

    it('rounds float input values', () => {
      const size = yuangongComposedBaseSizeFromCanvas(96.7, 64.2)
      expect(size.width).toBe(97)
      expect(size.height).toBe(64)
    })

    it('handles large dimensions', () => {
      const size = yuangongComposedBaseSizeFromCanvas(1920, 1080)
      expect(size).toEqual({ width: 1920, height: 1080 })
    })

    it('handles negative width by clamping to minimum 1', () => {
      const size = yuangongComposedBaseSizeFromCanvas(-10, 50)
      expect(size.width).toBe(1)
    })

    it('handles negative height by clamping to minimum 1', () => {
      const size = yuangongComposedBaseSizeFromCanvas(50, -10)
      expect(size.height).toBe(1)
    })
  })
})
