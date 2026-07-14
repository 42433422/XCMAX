import { describe, it, expect } from 'vitest'
import { normalizeReleaseMedia } from './releaseMedia'

describe('normalizeReleaseMedia', () => {
  it('keeps only safe https posters', () => {
    expect(
      normalizeReleaseMedia({
        posterUrl: 'https://xiu-ci.com/media/a.webp',
        videoUrl: 'https://xiu-ci.com/media/a.mp4',
        caption: 'demo',
      }),
    ).toEqual([
      {
        posterUrl: 'https://xiu-ci.com/media/a.webp',
        videoUrl: 'https://xiu-ci.com/media/a.mp4',
        caption: 'demo',
      },
    ])
  })
})
