import { describe, expect, it } from 'vitest'
import {
  planComposerAttachmentStrip,
  planHeaderFileStrip,
  planHeaderGeneratedStrip,
  WB_HEADER_FILE_STRIP_MAX_VISIBLE,
} from './workbenchFileStripPlan'

describe('planHeaderGeneratedStrip', () => {
  it('only counts generated files for top strip', () => {
    expect(planHeaderGeneratedStrip(5, 3)).toEqual({
      stripGeneratedCount: 3,
      overflowGeneratedCount: 2,
      overflowCount: 2,
    })
  })
})

describe('planComposerAttachmentStrip', () => {
  it('limits visible uploads in composer', () => {
    expect(planComposerAttachmentStrip(8, 5)).toEqual({
      visibleCount: 5,
      overflowCount: 3,
    })
  })
})

describe('planHeaderFileStrip', () => {
  it('shows up to max visible with attachments first', () => {
    expect(planHeaderFileStrip(2, 5, 3)).toEqual({
      stripAttachmentCount: 2,
      stripGeneratedCount: 1,
      overflowAttachmentCount: 0,
      overflowGeneratedCount: 4,
      overflowCount: 4,
    })
  })

  it('reserves one strip slot for generated when attachments fill the cap', () => {
    expect(planHeaderFileStrip(5, 2, 3)).toEqual({
      stripAttachmentCount: 2,
      stripGeneratedCount: 1,
      overflowAttachmentCount: 3,
      overflowGeneratedCount: 1,
      overflowCount: 4,
    })
  })

  it('defaults to WB_HEADER_FILE_STRIP_MAX_VISIBLE', () => {
    const p = planHeaderFileStrip(0, 10)
    expect(p.stripGeneratedCount).toBe(WB_HEADER_FILE_STRIP_MAX_VISIBLE)
    expect(p.overflowCount).toBe(10 - WB_HEADER_FILE_STRIP_MAX_VISIBLE)
  })
})
