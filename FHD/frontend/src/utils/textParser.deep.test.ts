import { describe, it, expect } from 'vitest'
import {
  parseCnInt,
  normalizeProductToken,
  extractModelQtySpec,
  parseShipmentCommand,
  detectRuntimeModeCommand,
  isStartPrintMessage,
} from './textParser'

describe('textParser deep branches', () => {
  it('parseCnInt handles 个 suffix and ten variants', () => {
    expect(parseCnInt('3个')).toBe(3)
    expect(parseCnInt('十')).toBe(10)
    expect(parseCnInt('三十')).toBe(30)
    expect(parseCnInt('十五')).toBe(15)
    expect(parseCnInt('二十三')).toBe(23)
    expect(parseCnInt('两')).toBe(2)
    expect(parseCnInt('abc')).toBeNull()
  })

  it('normalizeProductToken removes spaces and dashes', () => {
    expect(normalizeProductToken(' a-b c ')).toBe('ABC')
  })

  it('extractModelQtySpec matches bucket+model+spec (p00)', () => {
    expect(extractModelQtySpec('一个2桶ABC规格18')).toEqual({
      model: 'ABC',
      quantity_tins: 2,
      tin_spec: 18,
    })
  })

  it('extractModelQtySpec matches bucket+model only (p00b)', () => {
    expect(extractModelQtySpec('2桶ABC')).toEqual({ model: 'ABC', quantity_tins: 2, tin_spec: null })
  })

  it('extractModelQtySpec matches bucket+spec without model (p00c)', () => {
    expect(extractModelQtySpec('3桶规格20')).toEqual({ model: null, quantity_tins: 3, tin_spec: 20 })
  })

  it('extractModelQtySpec matches spec only (p00d)', () => {
    expect(extractModelQtySpec('规格12.5')).toEqual({ model: null, quantity_tins: null, tin_spec: 12.5 })
  })

  it('extractModelQtySpec matches model+spec (p3)', () => {
    expect(extractModelQtySpec('X100规格15')).toEqual({ model: 'X100', quantity_tins: null, tin_spec: 15 })
  })

  it('extractModelQtySpec falls back to model only (p4)', () => {
    expect(extractModelQtySpec('AB12')).toEqual({ model: 'AB12', quantity_tins: null, tin_spec: null })
  })

  it('extractModelQtySpec returns null for noise', () => {
    expect(extractModelQtySpec('你好吗')).toBeNull()
  })

  it('parseShipmentCommand add with chinese numbers', () => {
    const r = parseShipmentCommand('再加两桶X200')
    expect(r?.action).toBe('add')
    expect(r?.product?.quantity_tins).toBe(2)
  })

  it('parseShipmentCommand remove via suffix pattern', () => {
    const r = parseShipmentCommand('X300删掉')
    expect(r?.action).toBe('remove')
    expect(r?.model).toBe('X300')
  })

  it('parseShipmentCommand edit spec change', () => {
    const r = parseShipmentCommand('X100规格改成18')
    expect(r?.action).toBe('edit')
    expect(r?.product?.tin_spec).toBe(18)
  })

  it('parseShipmentCommand returns null action for unmatched', () => {
    expect(parseShipmentCommand('随便聊聊')).toEqual({ action: null })
  })

  it('isStartPrintMessage variants', () => {
    expect(isStartPrintMessage('开始打印')).toBe(true)
    expect(isStartPrintMessage('开始打印一下')).toBe(true)
    expect(isStartPrintMessage('')).toBe(false)
  })

  it('detectRuntimeModeCommand english phrases', () => {
    expect(detectRuntimeModeCommand('work mode')).toBe('set_work_mode')
    expect(detectRuntimeModeCommand('monitor mode')).toBe('show_monitor')
    expect(detectRuntimeModeCommand('切换监控模式')).toBe('show_monitor')
    expect(detectRuntimeModeCommand('')).toBeNull()
  })
})
