import { describe, it, expect, vi } from 'vitest'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true }),
    post: vi.fn().mockResolvedValue({ success: true }),
  },
}))

import { traditionalApi } from './traditional'
import { api } from './core'

describe('traditionalApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('list calls api.get with default path', async () => {
    await traditionalApi.list()
    expect(api.get).toHaveBeenCalledWith('/api/traditional-mode/list', { path: '' })
  })

  it('list calls api.get with custom path', async () => {
    await traditionalApi.list('/custom/path')
    expect(api.get).toHaveBeenCalledWith('/api/traditional-mode/list', { path: '/custom/path' })
  })

  it('read calls api.get with file param', async () => {
    await traditionalApi.read('test.txt')
    expect(api.get).toHaveBeenCalledWith('/api/traditional-mode/read', { file: 'test.txt' }, {})
  })

  it('read includes cacheBust param when provided', async () => {
    await traditionalApi.read('test.txt', undefined, 'abc123')
    expect(api.get).toHaveBeenCalledWith('/api/traditional-mode/read', { file: 'test.txt', v: 'abc123' }, {})
  })

  it('read passes options', async () => {
    const options = { signal: new AbortController().signal }
    await traditionalApi.read('test.txt', options)
    expect(api.get).toHaveBeenCalledWith('/api/traditional-mode/read', { file: 'test.txt' }, options)
  })

  it('write calls api.post with data', async () => {
    await traditionalApi.write({ file: 'test.txt', data: 'content', type: 'text' })
    expect(api.post).toHaveBeenCalledWith('/api/traditional-mode/write', {
      file: 'test.txt',
      data: 'content',
      type: 'text',
    })
  })

  it('mkdir calls api.post with data', async () => {
    await traditionalApi.mkdir({ path: '/base', name: 'newdir' })
    expect(api.post).toHaveBeenCalledWith('/api/traditional-mode/mkdir', {
      path: '/base',
      name: 'newdir',
    })
  })

  it('rename calls api.post with data', async () => {
    await traditionalApi.rename({ path: '/base', old_name: 'old.txt', new_name: 'new.txt' })
    expect(api.post).toHaveBeenCalledWith('/api/traditional-mode/rename', {
      path: '/base',
      old_name: 'old.txt',
      new_name: 'new.txt',
    })
  })

  it('delete calls api.post with data', async () => {
    await traditionalApi.delete({ path: '/base', name: 'file.txt' })
    expect(api.post).toHaveBeenCalledWith('/api/traditional-mode/delete', {
      path: '/base',
      name: 'file.txt',
    })
  })

  it('delete includes rel_target when provided', async () => {
    await traditionalApi.delete({ path: '/base', name: 'file.txt', rel_target: '/base/file.txt' })
    expect(api.post).toHaveBeenCalledWith('/api/traditional-mode/delete', {
      path: '/base',
      name: 'file.txt',
      rel_target: '/base/file.txt',
    })
  })

  it('upload calls api.post with FormData', async () => {
    const file = new File(['content'], 'test.txt', { type: 'text/plain' })
    await traditionalApi.upload('/upload/path', file)
    expect(api.post).toHaveBeenCalledWith('/api/traditional-mode/upload', expect.any(FormData))
  })

  it('watch calls api.get with default path', async () => {
    await traditionalApi.watch()
    expect(api.get).toHaveBeenCalledWith('/api/traditional-mode/watch', { path: '' })
  })

  it('watch calls api.get with custom path', async () => {
    await traditionalApi.watch('/watch/path')
    expect(api.get).toHaveBeenCalledWith('/api/traditional-mode/watch', { path: '/watch/path' })
  })
})
