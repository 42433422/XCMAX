import { describe, expect, it } from 'vitest';
import { formatTaskSourceLabel, formatTaskTime } from './chatTaskLabels';

describe('chatTaskLabels', () => {
  it('formatTaskTime returns empty for falsy ts', () => {
    expect(formatTaskTime(0)).toBe('');
  });

  it('formatTaskTime formats zh-CN clock', () => {
    const label = formatTaskTime(new Date('2026-06-14T08:30:00').getTime());
    expect(label).toMatch(/\d{1,2}:\d{2}/);
  });

  it('formatTaskSourceLabel maps known sources', () => {
    expect(formatTaskSourceLabel('workflow')).toBe('工作流');
    expect(formatTaskSourceLabel('wechat')).toBe('微信');
    expect(formatTaskSourceLabel('agent')).toBe('Agent');
    expect(formatTaskSourceLabel('unknown-src')).toBe('unknown-src');
    expect(formatTaskSourceLabel('')).toBe('—');
  });
});
