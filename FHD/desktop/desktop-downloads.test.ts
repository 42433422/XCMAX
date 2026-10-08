import { afterEach, describe, expect, it, vi } from 'vitest'
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { Session } from 'electron'
import { configureDesktopDownloads } from './desktop-downloads'

const folders: string[] = []
afterEach(() => { for (const folder of folders.splice(0)) fs.rmSync(folder, { recursive: true, force: true }) })
function setup() {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-download-test-'))
  folders.push(folder)
  const session = new EventEmitter(), log = vi.fn()
  const register = () => configureDesktopDownloads(session as unknown as Session, () => folder, log)
  const download = (name = '商品清单报表.xlsx') => {
    const item = Object.assign(new EventEmitter(), { getFilename: () => name, setSavePath: vi.fn(), cancel: vi.fn() })
    session.emit('will-download', {}, item)
    return item
  }
  return { folder, session, log, register, download }
}

describe('desktop business report downloads', () => {
  it('preserves an existing report and separates concurrent downloads before either writes', () => {
    const f = setup(), original = path.join(f.folder, '商品清单报表.xlsx')
    fs.writeFileSync(original, 'original report')
    f.register()
    const first = f.download(), second = f.download()
    const a = first.setSavePath.mock.calls[0][0], b = second.setSavePath.mock.calls[0][0]
    fs.writeFileSync(a, 'new report 1'); fs.writeFileSync(b, 'new report 2')
    expect(fs.readFileSync(original, 'utf8')).toBe('original report')
    expect(path.basename(a)).toBe('商品清单报表 (1).xlsx')
    expect(path.basename(b)).toBe('商品清单报表 (2).xlsx')
    expect(fs.readFileSync(a, 'utf8')).toBe('new report 1')
    expect(fs.readFileSync(b, 'utf8')).toBe('new report 2')
    first.emit('done', {}, 'completed'); second.emit('done', {}, 'completed')
  })

  it('does not register twice when the main window is recreated on the same session', () => {
    const f = setup(); f.register(); f.register()
    const item = f.download()
    expect(item.setSavePath).toHaveBeenCalledTimes(1)
    item.emit('done', {}, 'completed')
    expect(f.log).toHaveBeenCalledTimes(1)
  })

  it('separates pending case aliases on Mac case-insensitive volumes', () => {
    const f = setup(); f.register()
    const first = f.download('report.xlsx'), second = f.download('REPORT.XLSX')
    expect(path.basename(first.setSavePath.mock.calls[0][0])).toBe('report.xlsx')
    expect(path.basename(second.setSavePath.mock.calls[0][0])).toBe('REPORT (1).XLSX')
    first.emit('done', {}, 'cancelled'); second.emit('done', {}, 'cancelled')
  })

  it('releases a cancelled reservation so a retry can use an unwritten filename', () => {
    const f = setup(); f.register()
    const first = f.download(); first.emit('done', {}, 'cancelled')
    const retry = f.download()
    expect(retry.setSavePath.mock.calls[0][0]).toBe(first.setSavePath.mock.calls[0][0])
    retry.emit('done', {}, 'interrupted')
  })

  it('cancels explicitly if a safe destination cannot be selected', () => {
    const f = setup()
    configureDesktopDownloads(f.session as unknown as Session, () => { throw Error('downloads unavailable') }, f.log)
    const item = f.download()
    expect(item.cancel).toHaveBeenCalledTimes(1)
    expect(item.setSavePath).not.toHaveBeenCalled()
    expect(f.log).toHaveBeenCalledWith('[download] interrupted: downloads unavailable\n')
  })
})
