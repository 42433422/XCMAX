import { describe, expect, it } from 'vitest';
import { sanitizeMermaidSource, friendlyMermaidRenderError } from './mermaidSanitize';

describe('sanitizeMermaidSource', () => {
  it('strips surrounding code fences', () => {
    const out = sanitizeMermaidSource('```mermaid\ngraph TD\nA-->B\n```');
    expect(out).not.toContain('```');
    expect(out).toContain('graph TD');
  });

  it('quotes labels containing CJK characters', () => {
    const out = sanitizeMermaidSource('graph TD\nA[开始]');
    expect(out).toContain('A["开始"]');
  });

  it('quotes labels with problematic characters', () => {
    const out = sanitizeMermaidSource('graph TD\nA[a:b]');
    expect(out).toContain('A["a:b"]');
  });

  it('leaves plain ASCII labels untouched', () => {
    const out = sanitizeMermaidSource('graph TD\nA[start]-->B[end node]');
    expect(out).toContain('A[start]');
  });

  it('does not double-quote already quoted labels', () => {
    const out = sanitizeMermaidSource('graph TD\nA["已引"]');
    expect(out).toContain('A["已引"]');
    expect(out).not.toContain('""');
  });

  it('converts endsubgraph to end', () => {
    const out = sanitizeMermaidSource('subgraph x\nA\nendsubgraph');
    expect(out).toContain('end');
    expect(out).not.toContain('endsubgraph');
  });

  it('wraps a CJK subgraph title with generated id', () => {
    const out = sanitizeMermaidSource('subgraph 员工组\nA[x]\nend');
    expect(out).toMatch(/subgraph sg_\d+\["员工组"\]/);
  });

  it('escapes inner double quotes', () => {
    const out = sanitizeMermaidSource('graph TD\nA[说"你好"]');
    expect(out).toContain('#quot;');
  });

  it('handles round and curly node shapes', () => {
    const out = sanitizeMermaidSource('graph TD\nA(开始)-->B{判断}');
    expect(out).toContain('A("开始")');
    expect(out).toContain('B{"判断"}');
  });

  it('coerces null input to empty result', () => {
    expect(sanitizeMermaidSource(null as never)).toBe('');
  });
});

describe('friendlyMermaidRenderError', () => {
  it('returns default for empty input', () => {
    expect(friendlyMermaidRenderError('')).toContain('详细');
  });

  it('maps lexical error', () => {
    expect(friendlyMermaidRenderError(new Error('Lexical error on line 3'))).toContain('语法有误');
  });

  it('maps parse error', () => {
    expect(friendlyMermaidRenderError(new Error('Parse error near'))).toContain('结构无法解析');
  });

  it('returns short message verbatim', () => {
    expect(friendlyMermaidRenderError('boom')).toBe('boom');
  });

  it('truncates long messages', () => {
    const long = 'x'.repeat(200);
    const out = friendlyMermaidRenderError(long);
    expect(out.length).toBeLessThanOrEqual(118);
    expect(out.endsWith('…')).toBe(true);
  });
});
