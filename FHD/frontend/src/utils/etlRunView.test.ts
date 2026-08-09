import { describe, expect, it } from 'vitest'

import { tabForRunStatus } from './etlRunView'

describe('tabForRunStatus', () => {
  it.each(['queued', 'previewing'])('keeps %s runs in the upload workspace', (status) => {
    expect(tabForRunStatus(status)).toBe('upload')
  })

  it('opens a confirmed preview in the preview workspace', () => {
    expect(tabForRunStatus('preview_ready')).toBe('preview')
  })

  it.each(['executing', 'completed', 'failed', 'interrupted'])(
    'opens %s runs in history so the receipt stays visible',
    (status) => {
      expect(tabForRunStatus(status)).toBe('history')
    },
  )
})
