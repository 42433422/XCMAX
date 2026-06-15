import { describe, expect, it } from 'vitest';
import {
  detectRuntimeModeCommand,
  extractModelQtySpec,
  isStartPrintMessage,
  normalizeModel,
  parseCnInt,
  parseShipmentCommand,
} from './textParser';

describe('textParser', () => {
  it('parseCnInt handles arabic and chinese numerals', () => {
    expect(parseCnInt('12')).toBe(12);
    expect(parseCnInt('三')).toBe(3);
    expect(parseCnInt('二十三')).toBe(23);
    expect(parseCnInt('')).toBeNull();
  });

  it('normalizeModel uppercases and trims', () => {
    expect(normalizeModel(' ab-12 ')).toBe('AB-12');
  });

  it('extractModelQtySpec parses bucket + model + spec', () => {
    expect(extractModelQtySpec('2桶ABC-1规格18.5')).toEqual({
      model: 'ABC-1',
      quantity_tins: 2,
      tin_spec: 18.5,
    });
  });

  it('parseShipmentCommand detects add/remove/edit', () => {
    const add = parseShipmentCommand('再加 1桶X100规格20');
    expect(add?.action).toBe('add');
    expect(add?.product?.model_number).toBe('X100');

    const remove = parseShipmentCommand('删除 X100');
    expect(remove?.action).toBe('remove');
    expect(remove?.model).toBe('X100');

    const edit = parseShipmentCommand('把X100改成2桶规格15');
    expect(edit?.action).toBe('edit');
    expect(edit?.product?.tin_spec).toBe(15);
  });

  it('isStartPrintMessage matches print intents', () => {
    expect(isStartPrintMessage('开始打印吧')).toBe(true);
    expect(isStartPrintMessage('打印预览')).toBe(false);
  });

  it('detectRuntimeModeCommand recognizes work/monitor phrases', () => {
    expect(detectRuntimeModeCommand('工作模式')).toBe('set_work_mode');
    expect(detectRuntimeModeCommand('进入监控模式')).toBe('show_monitor');
    expect(detectRuntimeModeCommand('hello')).toBeNull();
  });
});
