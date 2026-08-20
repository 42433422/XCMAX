import { describe, expect, it } from 'vitest'
import { isKellaiImagePlaceholder, resolveKellaiMessageImageSrc } from './kellaiMessageMedia'

describe('kellaiMessageMedia', () => {
  it('resolves metadata.media_url', () => {
    expect(
      resolveKellaiMessageImageSrc({
        content: '[图片]',
        content_type: 'image',
        metadata: { media_url: 'https://cdn.example.com/a.png' },
      }),
    ).toBe('https://cdn.example.com/a.png')
  })

  it('resolves content when content_type is image', () => {
    expect(
      resolveKellaiMessageImageSrc({
        content: 'https://mmbiz.qpic.cn/xxx',
        content_type: 'image',
      }),
    ).toBe('https://mmbiz.qpic.cn/xxx')
  })

  it('does not treat plain text as image', () => {
    expect(
      resolveKellaiMessageImageSrc({
        content: '请问什么时候交货？',
        content_type: 'text',
      }),
    ).toBe('')
  })

  it('detects image placeholders', () => {
    expect(isKellaiImagePlaceholder('[图片]')).toBe(true)
    expect(isKellaiImagePlaceholder('图片')).toBe(true)
    expect(isKellaiImagePlaceholder('你好')).toBe(false)
  })
})
