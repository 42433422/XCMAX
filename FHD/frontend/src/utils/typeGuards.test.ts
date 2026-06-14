import { describe, expect, it } from 'vitest';
import {
  asArray,
  asBoolean,
  asDisposable,
  asNumber,
  asRecord,
  asString,
} from './typeGuards';

describe('typeGuards', () => {
  it('asRecord accepts plain objects only', () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
    expect(asRecord(null)).toEqual({});
    expect(asRecord([1])).toEqual({});
    expect(asRecord('x')).toEqual({});
  });

  it('asArray returns arrays or empty list', () => {
    expect(asArray([1, 2])).toEqual([1, 2]);
    expect(asArray(null)).toEqual([]);
  });

  it('asString coerces or uses fallback', () => {
    expect(asString(42)).toBe('42');
    expect(asString(null, 'fb')).toBe('fb');
  });

  it('asNumber rejects non-finite values', () => {
    expect(asNumber('3.5')).toBe(3.5);
    expect(asNumber('nope', 9)).toBe(9);
  });

  it('asBoolean parses common literals', () => {
    expect(asBoolean(true)).toBe(true);
    expect(asBoolean('true')).toBe(true);
    expect(asBoolean(0)).toBe(false);
    expect(asBoolean('maybe', true)).toBe(true);
  });

  it('asDisposable detects cleanup hooks', () => {
    expect(asDisposable({ dispose: () => {} })).toBeTruthy();
    expect(asDisposable('x')).toBeNull();
  });
});
