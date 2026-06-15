import { describe, expect, it } from 'vitest';
import {
  sanitizeChatBubbleHtml,
  sanitizeChatBubbleMarkdown,
  sanitizeTaskSummaryHtml,
} from './sanitizeHtml';

describe('sanitizeChatBubbleHtml', () => {
  it('returns empty string for null/empty', () => {
    expect(sanitizeChatBubbleHtml(null)).toBe('');
    expect(sanitizeChatBubbleHtml('')).toBe('');
  });

  it('strips script tags', () => {
    const out = sanitizeChatBubbleHtml('<p>hi</p><script>alert(1)</script>');
    expect(out).toContain('<p>hi</p>');
    expect(out).not.toContain('<script>');
  });

  it('removes inline event handlers', () => {
    const out = sanitizeChatBubbleHtml('<a href="#" onclick="evil()">x</a>');
    expect(out).not.toContain('onclick');
  });

  it('keeps allowed formatting tags', () => {
    const out = sanitizeChatBubbleHtml('<strong>bold</strong> <em>i</em>');
    expect(out).toContain('<strong>bold</strong>');
    expect(out).toContain('<em>i</em>');
  });
});

describe('sanitizeChatBubbleMarkdown', () => {
  it('renders markdown bold into strong', () => {
    const out = sanitizeChatBubbleMarkdown('**bold**');
    expect(out).toContain('<strong>bold</strong>');
  });

  it('returns empty for blank input', () => {
    expect(sanitizeChatBubbleMarkdown('')).toBe('');
    expect(sanitizeChatBubbleMarkdown(null)).toBe('');
  });

  it('converts model literal br tags into line breaks', () => {
    const out = sanitizeChatBubbleMarkdown('第一行<br><br>- 列表项');
    expect(out).not.toContain('&lt;br');
    expect(out).not.toContain('<br>');
    expect(out).toContain('列表项');
    expect(out).toMatch(/<li[^>]*>/);
  });
});

describe('sanitizeTaskSummaryHtml', () => {
  it('returns empty when no summary', () => {
    expect(sanitizeTaskSummaryHtml({})).toBe('');
    expect(sanitizeTaskSummaryHtml({ summary: '' })).toBe('');
  });

  it('sanitizes generic summary', () => {
    const out = sanitizeTaskSummaryHtml({ type: 'generic', summary: '<p>ok</p><script>x</script>' });
    expect(out).toContain('<p>ok</p>');
    expect(out).not.toContain('<script>');
  });

  it('keeps interactive inputs inside a sales-contract preview', () => {
    const html =
      '<div class="sales-contract-excel-preview">' +
      '<input class="sales-contract-excel-preview__qty-input" type="number" onchange="f()" />' +
      '</div>';
    const out = sanitizeTaskSummaryHtml({ type: 'sales_contract', summary: html });
    expect(out).toContain('input');
    expect(out).toContain('onchange');
  });

  it('strips handlers when type is not sales_contract', () => {
    const html =
      '<div class="sales-contract-excel-preview">' +
      '<input class="sales-contract-excel-preview__qty-input" onchange="f()" /></div>';
    const out = sanitizeTaskSummaryHtml({ type: 'other', summary: html });
    expect(out).not.toContain('onchange');
  });
});
