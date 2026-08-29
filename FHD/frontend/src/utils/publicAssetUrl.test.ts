import { describe, expect, it } from 'vitest'
import { publicAssetUrl } from './publicAssetUrl'

describe('publicAssetUrl', () => {
  it('keeps root deployments rooted at the site origin', () => {
    expect(publicAssetUrl('/ai-butler-female-avatar-v1.png', '/')).toBe('/ai-butler-female-avatar-v1.png')
  })

  it('prefixes assets with the administration build base', () => {
    expect(publicAssetUrl('/ai-butler-male-avatar-v1.jpg', '/admin/')).toBe('/admin/ai-butler-male-avatar-v1.jpg')
  })

  it('keeps relative desktop build bases relative', () => {
    expect(publicAssetUrl('ai-butler-female-avatar-v1.png', './')).toBe('./ai-butler-female-avatar-v1.png')
  })
})
