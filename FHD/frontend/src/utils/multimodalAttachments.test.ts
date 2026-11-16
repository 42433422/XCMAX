import { describe, expect, it } from 'vitest'
import { filesToMultimodalRows } from './multimodalAttachments'

function makeFile(name: string, type: string, content = 'x'): File {
  return new File([content], name, { type })
}

describe('multimodalAttachments', () => {
  it('rejects empty file list', async () => {
    const r = await filesToMultimodalRows([])
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('未选择')
  })

  it('rejects too many files', async () => {
    const files = Array.from({ length: 51 }, (_, i) => makeFile(`f${i}.png`, 'image/png'))
    const r = await filesToMultimodalRows(files)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('最多')
  })

  it('skips unsupported files and keeps the folder-relative path', async () => {
    const image = makeFile('a.png', 'image/png')
    Object.defineProperty(image, 'webkitRelativePath', { value: 'batch/a.png' })
    const r = await filesToMultimodalRows([image, makeFile('a.exe', 'application/octet-stream')], {
      skipUnsupported: true,
    })
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.rows).toHaveLength(1)
      expect(r.rows[0].filename).toBe('batch/a.png')
    }
  })

  it('rejects unsupported extension', async () => {
    const r = await filesToMultimodalRows([makeFile('a.exe', 'application/octet-stream')])
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('不支持')
  })

  it('accepts a plain text log', async () => {
    const r = await filesToMultimodalRows([makeFile('a.txt', 'text/plain')])
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.rows[0].kind).toBe('log')
  })

  it('accepts png image', async () => {
    const r = await filesToMultimodalRows([makeFile('a.png', 'image/png')])
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.rows[0].kind).toBe('image')
      expect(r.rows[0].data_url).toMatch(/^data:image\/png;base64,/)
    }
  })

  it('accepts pdf', async () => {
    const r = await filesToMultimodalRows([makeFile('doc.pdf', 'application/pdf')])
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.rows[0].kind).toBe('pdf')
  })
})
