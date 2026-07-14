import { describe, it, expect } from 'vitest'
import {
  isSafeMediaUrl,
  normalizeReleaseMedia,
  parseReleaseMediaFromYaml,
} from './release-media.js'

describe('release-media', () => {
  it('accepts https and localhost http only', () => {
    expect(isSafeMediaUrl('https://cdn.example.com/a.webp')).toBe(true)
    expect(isSafeMediaUrl('http://localhost:5173/a.webp')).toBe(true)
    expect(isSafeMediaUrl('http://evil.example.com/a.webp')).toBe(false)
    expect(isSafeMediaUrl('javascript:alert(1)')).toBe(false)
  })

  it('normalizes slides and drops unsafe urls', () => {
    const slides = normalizeReleaseMedia([
      {
        posterUrl: 'https://cdn.example.com/p1.webp',
        videoUrl: 'https://cdn.example.com/v1.mp4',
        caption: '功能 A',
      },
      { posterUrl: 'javascript:bad', caption: 'x' },
      { posterUrl: 'https://cdn.example.com/p2.webp', videoUrl: 'ftp://x/y' },
    ])
    expect(slides).toHaveLength(2)
    expect(slides[0].videoUrl).toContain('.mp4')
    expect(slides[1].videoUrl).toBeUndefined()
  })

  it('parses list and single-object yaml blocks', () => {
    const listYaml = `version: 1.0.0
releaseMedia:
  - posterUrl: https://cdn.example.com/a.webp
    videoUrl: https://cdn.example.com/a.mp4
    caption: 拟人系统
  - posterUrl: https://cdn.example.com/b.webp
    caption: 弹窗居中
files:
  - url: app.zip
`
    const slides = parseReleaseMediaFromYaml(listYaml)
    expect(slides).toHaveLength(2)
    expect(slides[0].caption).toBe('拟人系统')
    expect(slides[1].videoUrl).toBeUndefined()

    const singleYaml = `releaseMedia:
  posterUrl: https://cdn.example.com/only.webp
  caption: only
files:
  - url: app.zip
`
    expect(parseReleaseMediaFromYaml(singleYaml)).toEqual([
      { posterUrl: 'https://cdn.example.com/only.webp', caption: 'only' },
    ])

    const quotedYaml = `releaseMedia:
  - posterUrl: "https://cdn.example.com/a.webp"
    videoUrl: "https://cdn.example.com/a.mp4"
    caption: demo
files:
  - url: app.zip
`
    expect(parseReleaseMediaFromYaml(quotedYaml)[0]).toMatchObject({
      posterUrl: 'https://cdn.example.com/a.webp',
      videoUrl: 'https://cdn.example.com/a.mp4',
      caption: 'demo',
    })
  })
})
