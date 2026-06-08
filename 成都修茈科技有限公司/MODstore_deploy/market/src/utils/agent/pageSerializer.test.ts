import { describe, expect, it, vi } from 'vitest'
import { serializeVisibleDom } from './pageSerializer'

describe('serializeVisibleDom', () => {
  it('returns empty string for empty page', () => {
    document.body.innerHTML = ''
    const result = serializeVisibleDom()
    expect(result).toContain('当前路径：')
  })

  it('includes page title', () => {
    document.title = 'Test Page'
    const result = serializeVisibleDom()
    expect(result).toContain('页面标题：Test Page')
  })

  it('includes headings', () => {
    document.body.innerHTML = '<h1>Main</h1><h2>Sub</h2><h3>Detail</h3>'
    const result = serializeVisibleDom()
    expect(result).toContain('Main')
    expect(result).toContain('Sub')
    expect(result).toContain('Detail')
  })

  it('includes visible buttons', () => {
    document.body.innerHTML = '<button>Click Me</button><a class="btn">Link Btn</a>'
    const result = serializeVisibleDom()
    expect(result).toContain('Click Me')
    expect(result).toContain('Link Btn')
  })

  it('includes input placeholders', () => {
    document.body.innerHTML = '<input placeholder="Search..."><textarea placeholder="Enter text"></textarea>'
    const result = serializeVisibleDom()
    expect(result).toContain('Search...')
    expect(result).toContain('Enter text')
  })

  it('includes table headers', () => {
    document.body.innerHTML = '<table><tr><th>Name</th><th>Age</th></tr></table>'
    const result = serializeVisibleDom()
    expect(result).toContain('Name')
    expect(result).toContain('Age')
  })

  it('includes main content', () => {
    document.body.innerHTML = '<main>This is the main content of the page with some text.</main>'
    const result = serializeVisibleDom()
    expect(result).toContain('页面主要内容')
  })

  it('excludes hidden elements', () => {
    const btn = document.createElement('button')
    btn.textContent = 'Hidden'
    btn.style.display = 'none'
    document.body.innerHTML = ''
    document.body.appendChild(btn)
    const result = serializeVisibleDom()
    expect(result).not.toContain('Hidden')
  })

  it('limits headings to 8', () => {
    let html = ''
    for (let i = 0; i < 12; i++) html += `<h2>Heading ${i}</h2>`
    document.body.innerHTML = html
    const result = serializeVisibleDom()
    expect(result).toContain('Heading 7')
  })

  it('handles page without title', () => {
    document.title = ''
    document.body.innerHTML = '<p>Content</p>'
    const result = serializeVisibleDom()
    expect(result).not.toContain('页面标题：')
  })
})
