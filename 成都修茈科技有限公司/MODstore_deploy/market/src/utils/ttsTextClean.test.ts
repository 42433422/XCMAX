import { describe, it, expect } from 'vitest'
import { cleanTextForTts } from './ttsTextClean'

describe('cleanTextForTts', () => {
  it('returns clean text for plain text input', () => {
    expect(cleanTextForTts('Hello world')).toBe('Hello world')
  })

  it('returns empty string for empty input', () => {
    expect(cleanTextForTts('')).toBe('')
  })

  it('returns empty string for null input', () => {
    expect(cleanTextForTts(null as unknown as string)).toBe('')
  })

  it('returns empty string for undefined input', () => {
    expect(cleanTextForTts(undefined as unknown as string)).toBe('')
  })

  it('removes fenced code blocks', () => {
    const input = 'Before\n```js\nconst x = 1\n```\nAfter'
    const result = cleanTextForTts(input)
    expect(result).not.toContain('```')
    expect(result).not.toContain('const x')
    expect(result).toContain('Before')
    expect(result).toContain('After')
  })

  it('removes inline code', () => {
    const input = 'Use `npm install` to install'
    const result = cleanTextForTts(input)
    expect(result).not.toContain('`')
    expect(result).not.toContain('npm install')
  })

  it('removes image markdown', () => {
    const input = 'See ![alt text](https://example.com/img.png) here'
    const result = cleanTextForTts(input)
    expect(result).not.toContain('![')
    expect(result).not.toContain('example.com')
  })

  it('converts link markdown to link text', () => {
    const input = 'Visit [Google](https://google.com) now'
    const result = cleanTextForTts(input)
    expect(result).toContain('Google')
    expect(result).not.toContain('https://google.com')
    expect(result).not.toContain('](')
  })

  it('removes heading markers', () => {
    const input = '## Heading\n### Subheading'
    const result = cleanTextForTts(input)
    expect(result).not.toContain('#')
    expect(result).toContain('Heading')
    expect(result).toContain('Subheading')
  })

  it('removes unordered list markers', () => {
    const input = '- Item 1\n* Item 2\n+ Item 3'
    const result = cleanTextForTts(input)
    expect(result).not.toMatch(/^[-*+]\s/m)
    expect(result).toContain('Item 1')
    expect(result).toContain('Item 2')
    expect(result).toContain('Item 3')
  })

  it('removes ordered list markers', () => {
    const input = '1. First\n2. Second\n3. Third'
    const result = cleanTextForTts(input)
    expect(result).not.toMatch(/^\d+\.\s/m)
    expect(result).toContain('First')
    expect(result).toContain('Second')
  })

  it('removes blockquote markers', () => {
    const input = '> Quoted text\n> More quoted'
    const result = cleanTextForTts(input)
    expect(result).not.toContain('>')
    expect(result).toContain('Quoted text')
  })

  it('unwraps bold markers', () => {
    expect(cleanTextForTts('**bold text**')).toBe('bold text')
    expect(cleanTextForTts('__bold text__')).toBe('bold text')
  })

  it('unwraps italic markers', () => {
    expect(cleanTextForTts('*italic text*')).toBe('italic text')
    expect(cleanTextForTts('_italic text_')).toBe('italic text')
  })

  it('unwraps strikethrough markers', () => {
    expect(cleanTextForTts('~~struck text~~')).toBe('struck text')
  })

  it('removes emoji', () => {
    const input = 'Hello 😀 world 🎉'
    const result = cleanTextForTts(input)
    expect(result).not.toContain('😀')
    expect(result).not.toContain('🎉')
    expect(result).toContain('Hello')
    expect(result).toContain('world')
  })

  it('collapses multiple newlines into single', () => {
    const input = 'Line 1\n\n\n\nLine 2'
    const result = cleanTextForTts(input)
    expect(result).not.toMatch(/\n{2,}/)
  })

  it('collapses multiple spaces into single', () => {
    expect(cleanTextForTts('multiple    spaces')).toBe('multiple spaces')
  })

  it('trims leading and trailing whitespace', () => {
    expect(cleanTextForTts('  \n  text  \n  ')).toBe('text')
  })

  it('respects maxLen parameter', () => {
    const longText = 'a'.repeat(2000)
    const result = cleanTextForTts(longText, 100)
    expect(result.length).toBeLessThanOrEqual(100)
  })

  it('uses default maxLen of 1500', () => {
    const longText = 'a'.repeat(2000)
    const result = cleanTextForTts(longText)
    expect(result.length).toBeLessThanOrEqual(1500)
  })

  it('handles complex mixed markdown', () => {
    const input = `## Title

**Bold** and *italic* text.

- List item 1
- List item 2

\`\`\`
code block
\`\`\`

[Link](https://example.com) and ![image](img.png)

> Quote

Emoji: 🚀 done`

    const result = cleanTextForTts(input)
    expect(result).not.toContain('```')
    expect(result).not.toContain('**')
    expect(result).not.toContain('##')
    expect(result).not.toContain('](')
    expect(result).not.toContain('🚀')
    expect(result).toContain('Title')
    expect(result).toContain('Bold')
    expect(result).toContain('Link')
  })

  it('preserves Chinese characters', () => {
    const input = '这是一段中文文本'
    expect(cleanTextForTts(input)).toBe('这是一段中文文本')
  })

  it('preserves numbers and punctuation', () => {
    const input = 'Price: $100.00 (50% off)!'
    const result = cleanTextForTts(input)
    expect(result).toContain('100')
    expect(result).toContain('50%')
  })
})
