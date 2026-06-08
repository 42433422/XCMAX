import { describe, expect, it } from 'vitest'
import { friendlyMermaidRenderError, sanitizeMermaidSource } from './mermaidSanitize'

describe('sanitizeMermaidSource', () => {
  it('leaves clean labels unchanged', () => {
    const src = 'flowchart LR\nA[Foo] --> B[Bar]'
    expect(sanitizeMermaidSource(src)).toBe(src)
  })

  it('quotes bracket labels with parentheses', () => {
    const src = 'flowchart LR\nA[Foo (Bar)] --> B[Done]'
    expect(sanitizeMermaidSource(src)).toBe(
      'flowchart LR\nA["Foo (Bar)"] --> B[Done]',
    )
  })

  it('quotes round-shape labels with colons', () => {
    const src = 'flowchart TB\nA(开始: register) --> B(结束)'
    expect(sanitizeMermaidSource(src)).toBe(
      'flowchart TB\nA("开始: register") --> B("结束")',
    )
  })

  it('escapes inner quotes via #quot;', () => {
    const src = 'flowchart LR\nA[Hello "world"]'
    expect(sanitizeMermaidSource(src)).toBe(
      'flowchart LR\nA["Hello #quot;world#quot;"]',
    )
  })

  it('keeps already-quoted labels untouched', () => {
    const src = 'flowchart LR\nA["Foo (Bar)"] --> B["x: y"]'
    expect(sanitizeMermaidSource(src)).toBe(src)
  })

  it('does not touch edge pipe labels or styles', () => {
    const src = [
      'flowchart LR',
      'A -->|click: go| B',
      'style A fill:#fff,stroke:#333',
    ].join('\n')
    expect(sanitizeMermaidSource(src)).toBe(src)
  })

  it('strips stray triple-backtick fences', () => {
    const src = '```mermaid\nflowchart LR\nA --> B\n```'
    expect(sanitizeMermaidSource(src)).toBe('flowchart LR\nA --> B')
  })

  it('quotes ASCII-id labels with CJK text', () => {
    const src = 'flowchart LR\nB[解析工具] --> C[保存 txt]'
    expect(sanitizeMermaidSource(src)).toBe(
      'flowchart LR\nB["解析工具"] --> C["保存 txt"]',
    )
  })

  it('quotes ASCII-id labels with semicolons', () => {
    const src = 'flowchart LR\nA[step; next] --> B[end]'
    expect(sanitizeMermaidSource(src)).toBe(
      'flowchart LR\nA["step; next"] --> B[end]',
    )
  })

  it('fixes endsubgraph typo and unquoted subgraph titles', () => {
    const src = [
      'flowchart TD',
      '  subgraph upload["上传 Word 文件"]',
      '    A[上传] --> B[解析]',
      '  file"]endsubgraph 员工：文档文本提取员',
      '  B["解析工具"] --> C[保存 txt]',
    ].join('\n')
    const out = sanitizeMermaidSource(src)
    expect(out).toContain('\nend\n')
    expect(out).toContain('subgraph sg_1["员工：文档文本提取员"]')
    expect(out).toContain('B["解析工具"]')
  })

  it('wraps standalone subgraph title lines with colons', () => {
    const src = 'flowchart LR\nsubgraph 员工：文档文本提取员\nA --> B\nend'
    const out = sanitizeMermaidSource(src)
    expect(out).toContain('subgraph sg_1["员工：文档文本提取员"]')
  })
})

describe('friendlyMermaidRenderError', () => {
  it('maps lexical errors to Chinese hint', () => {
    expect(
      friendlyMermaidRenderError(new Error('Lexical error on line 5. Unrecognized text.')),
    ).toContain('流程图语法有误')
  })
})
