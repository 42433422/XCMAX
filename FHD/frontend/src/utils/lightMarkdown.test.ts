import { describe, expect, it } from 'vitest';
import { normalizeModelLineBreaks, renderMarkdown, stripInternalMarkers } from './lightMarkdown';

describe('lightMarkdown', () => {
  it('escapes raw html and renders bold', () => {
    const html = renderMarkdown('**hi** <script>alert(1)</script>');
    expect(html).toContain('<strong>hi</strong>');
    expect(html).not.toContain('<script>');
  });

  it('renders inline code and links safely', () => {
    const html = renderMarkdown('see [`code`](https://example.com) and `x`');
    expect(html).toContain('href="https://example.com"');
    expect(html).toContain('<code');
  });

  it('stripInternalMarkers removes plan blocks', () => {
    const src = 'hello <<<PLAN_DETAILS>>>secret<<<END_PLAN_DETAILS>>> world';
    expect(stripInternalMarkers(src)).toBe('hello  world');
  });

  it('normalizeModelLineBreaks converts br tags to newlines', () => {
    expect(normalizeModelLineBreaks('a<br>b<br/>c')).toBe('a\nb\nc');
  });
});
