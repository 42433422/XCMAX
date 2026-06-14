import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { isBenignLoadFailure, logLoadFailure } from './loadFailureLog';

describe('loadFailureLog', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'debug').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('treats missing sqlite table as benign', () => {
    expect(isBenignLoadFailure(new Error('no such table: purchase_units'))).toBe(true);
  });

  it('treats operational error and localized load messages as benign', () => {
    expect(isBenignLoadFailure(new Error('OperationalError: locked'))).toBe(true);
    expect(isBenignLoadFailure('服务未开放')).toBe(true);
    expect(isBenignLoadFailure('加载单位失败')).toBe(true);
    expect(isBenignLoadFailure('加载客户/购买单位失败')).toBe(true);
    expect(isBenignLoadFailure('HTTP 404 not found')).toBe(true);
  });

  it('treats normal failures as non-benign', () => {
    expect(isBenignLoadFailure(new Error('network timeout'))).toBe(false);
    expect(isBenignLoadFailure('')).toBe(false);
    expect(isBenignLoadFailure(null)).toBe(false);
  });

  it('logLoadFailure suppresses benign errors', () => {
    logLoadFailure('units', new Error('no such table: units'));
    expect(console.error).not.toHaveBeenCalled();
  });

  it('logLoadFailure logs unexpected errors', () => {
    logLoadFailure('units', new Error('network timeout'));
    expect(console.error).toHaveBeenCalledWith('units', expect.any(Error));
  });
});
