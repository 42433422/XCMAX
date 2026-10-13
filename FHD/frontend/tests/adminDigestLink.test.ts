import { expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useDigestPanel } from '../../admin-console/src/views/serverFunctions/useDigestPanel'
vi.mock('@/api', () => ({ api: { get: vi.fn() } }))
it.each(['http://127.0.0.1:8788', 'http://localhost:9999', ''])('opens the public market with internal API %s', (base) => {
  const panel = useDigestPanel(ref('digests'))
  panel.digestApiBase.value = base
  expect(panel.marketWebFromDigest.value).toBe('https://xiu-ci.com/market')
  if (base) expect(panel.identityBadgeTitle.value).not.toContain(`${base}/market`)
})
