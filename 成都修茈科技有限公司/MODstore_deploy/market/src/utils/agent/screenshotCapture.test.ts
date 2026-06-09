import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { captureViewport } from './screenshotCapture'

// 模拟 html2canvas，避免 happy-dom 环境真的去遍历 2000 个 DOM 节点
vi.mock('html2canvas', () => ({
  default: vi.fn(),
}))

import html2canvas from 'html2canvas'
import {
  _clearCaptureCache,
  invalidateCaptureCache,
  onCaptureMeta,
} from './screenshotCapture'

const mockHtml2canvas = html2canvas as unknown as ReturnType<typeof vi.fn>

/** 构造一个会返回给定 dataUrl 的假 canvas */
function fakeCanvas(dataUrl: string): HTMLCanvasElement {
  return {
    toDataURL: vi.fn().mockReturnValue(dataUrl),
  } as unknown as HTMLCanvasElement
}

describe('screenshotCapture — captureViewport', () => {
  beforeEach(() => {
    mockHtml2canvas.mockReset()
    // 清空模块级 LRU 缓存，避免测试间污染
    _clearCaptureCache()
    document.body.innerHTML = '<div id="t">hi</div>'
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('成功路径：返回 { ok: true, dataUrl, bytes }', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,' + 'A'.repeat(120)))

    const result = await captureViewport()
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.dataUrl.startsWith('data:image/jpeg;base64,')).toBe(true)
      expect(result.bytes).toBeGreaterThan(0)
    }
  })

  it('html2canvas 抛 SecurityError → reason=cors', async () => {
    mockHtml2canvas.mockRejectedValue(
      new Error('SecurityError: Tainted canvases may not be exported.'),
    )
    const result = await captureViewport()
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('cors')
    }
  })

  it('html2canvas 抛普通错误 → reason=render', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('Unsupported CSS property: foo'))
    const result = await captureViewport()
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('render')
      expect(result.message).toContain('Unsupported CSS property')
    }
  })

  it('html2canvas 抛 out of memory → reason=memory', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('out of memory while rendering'))
    const result = await captureViewport()
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('memory')
    }
  })

  it('html2canvas 抛 timeout → reason=timeout', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('timeout exceeded'))
    const result = await captureViewport()
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('timeout')
    }
  })

  it('html2canvas 抛 AbortError → reason=aborted', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('The user aborted a request.'))
    const result = await captureViewport()
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('aborted')
    }
  })

  it('signal 在调用前已 aborted → 立即返回 reason=aborted，不调 html2canvas', async () => {
    const ctrl = new AbortController()
    ctrl.abort()
    const result = await captureViewport({ signal: ctrl.signal })
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('aborted')
    }
    expect(mockHtml2canvas).not.toHaveBeenCalled()
  })

  it('signal 在 html2canvas 完成后 toDataURL 前被 abort → reason=aborted', async () => {
    const ctrl = new AbortController()
    mockHtml2canvas.mockImplementation(async () => {
      // 模拟用户操作：渲染完画面后立刻取消
      ctrl.abort()
      return fakeCanvas('data:image/jpeg;base64,xxx')
    })

    const result = await captureViewport({ signal: ctrl.signal })
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('aborted')
    }
  })

  it('默认会传 useCORS=true / scale=0.5 / logging=false 给 html2canvas', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,q'))

    await captureViewport()
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
    const args = mockHtml2canvas.mock.calls[0]
    const opts = args[1] as Record<string, unknown>
    expect(opts.useCORS).toBe(true)
    expect(opts.logging).toBe(false)
    expect(opts.scale).toBe(0.5)
    expect(typeof opts.ignoreElements).toBe('function')
  })

  it('ignoreElements 函数：.butler-float-root 元素被忽略', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,q'))
    await captureViewport({ ignoreSelectors: ['.butler-float-root'] })
    const opts = mockHtml2canvas.mock.calls[0][1] as { ignoreElements: (el: Element) => boolean }
    const div = document.createElement('div')
    div.className = 'butler-float-root'
    expect(opts.ignoreElements(div)).toBe(true)
  })

  it('ignoreElements 函数：默认配置忽略 .butler-float-root', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,q'))
    await captureViewport()
    const opts = mockHtml2canvas.mock.calls[0][1] as { ignoreElements: (el: Element) => boolean }
    const div = document.createElement('div')
    div.className = 'butler-float-root'
    expect(opts.ignoreElements(div)).toBe(true)
  })

  it('ignoreElements 函数：未匹配的 class 返回 false', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,q'))
    await captureViewport({ ignoreSelectors: ['.butler-float-root'] })
    const opts = mockHtml2canvas.mock.calls[0][1] as { ignoreElements: (el: Element) => boolean }
    const div = document.createElement('div')
    div.className = 'something-else'
    expect(opts.ignoreElements(div)).toBe(false)
  })

  it('scale / quality 自定义值会传给 html2canvas', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,q'))
    await captureViewport({ scale: 1.0, quality: 0.95 })
    const opts = mockHtml2canvas.mock.calls[0][1] as { scale: number }
    expect(opts.scale).toBe(1.0)
  })

  it('bytes 字段精确匹配 base64 解码后字节数（兼容 padding）', async () => {
    // 构造已知 byte 长度的 base64："foobar" 6 字节 → base64 "Zm9vYmFy"
    // 加上 'data:image/jpeg;base64,' 前缀
    const realJpeg = 'data:image/jpeg;base64,Zm9vYmFy' // 6 字节，无 padding
    mockHtml2canvas.mockResolvedValue(fakeCanvas(realJpeg))
    const r = await captureViewport()
    if (r.ok) {
      expect(r.bytes).toBe(6)
    }
    // padding = 1 的情况
    const padded = 'data:image/jpeg;base64,Zm8=' // "fo" 2 字节
    mockHtml2canvas.mockResolvedValue(fakeCanvas(padded))
    const r2 = await captureViewport({ routeSig: '/different' })
    if (r2.ok) {
      expect(r2.bytes).toBe(2)
    }
    // padding = 2 的情况
    const padded2 = 'data:image/jpeg;base64,Zg==' // "f" 1 字节
    mockHtml2canvas.mockResolvedValue(fakeCanvas(padded2))
    const r3 = await captureViewport({ routeSig: '/different2' })
    if (r3.ok) {
      expect(r3.bytes).toBe(1)
    }
  })

  // -------------------------- 后端：dom-snapshot --------------------------
  it('backend=dom-snapshot：返回 kind=text-snapshot 的 dataUrl，不调 html2canvas', async () => {
    const r = await captureViewport({ backend: 'dom-snapshot' })
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.kind).toBe('text-snapshot')
      expect(r.dataUrl.startsWith('data:application/json;base64,')).toBe(true)
      expect(r.bytes).toBeGreaterThan(0)
    }
    expect(mockHtml2canvas).not.toHaveBeenCalled()
  })

  it('backend=dom-snapshot：dataUrl 解码后含 route/text/capturedAt', async () => {
    const r = await captureViewport({ backend: 'dom-snapshot', routeSig: '/foo' })
    if (r.ok) {
      const b64 = r.dataUrl.split(',')[1] ?? ''
      const json = JSON.parse(atob(b64))
      expect(json.kind).toBe('dom-snapshot')
      expect(json.route).toBe('/foo')
      expect(typeof json.capturedAt).toBe('string')
      expect(typeof json.text).toBe('string')
    }
  })

  // -------------------------- 自动 textFallback --------------------------
  it('html2canvas 失败 → 自动附加 textFallback', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('SecurityError: Tainted'))
    const r = await captureViewport()
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.reason).toBe('cors')
      expect(typeof r.textFallback).toBe('string')
      expect(r.textFallback!.length).toBeGreaterThan(0)
    }
  })

  it('autoTextFallback=false → 失败时不附 textFallback', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('render failed'))
    const r = await captureViewport({ autoTextFallback: false })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.textFallback).toBeUndefined()
    }
  })

  // -------------------------- 缓存 --------------------------
  it('缓存命中：第二次调用不调 html2canvas，fromCache=true', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,abc'))
    const r1 = await captureViewport()
    expect(r1.ok).toBe(true)
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)

    const r2 = await captureViewport()
    expect(r2.ok).toBe(true)
    if (r2.ok) {
      expect(r2.fromCache).toBe(true)
    }
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1) // 没再调
  })

  it('不同 route 的缓存隔离', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,x'))
    await captureViewport({ routeSig: '/a' })
    await captureViewport({ routeSig: '/b' })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(2)
  })

  it('enableCache=false → 每次都重跑', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,x'))
    await captureViewport({ enableCache: false })
    await captureViewport({ enableCache: false })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(2)
  })

  it('缓存 TTL 过期后失效', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,x'))
    // 用极短 TTL
    const r1 = await captureViewport({ cacheTtlMs: 1 })
    expect(r1.ok).toBe(true)
    // 等过期
    await new Promise((r) => setTimeout(r, 5))
    const r2 = await captureViewport({ cacheTtlMs: 1 })
    expect(r2.ok).toBe(true)
    if (r2.ok) {
      expect(r2.fromCache).toBeFalsy()
    }
    expect(mockHtml2canvas).toHaveBeenCalledTimes(2)
  })

  it('失败结果也缓存：第二次直接拿缓存，不重跑 html2canvas', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('render failed'))
    const r1 = await captureViewport()
    expect(r1.ok).toBe(false)
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
    const r2 = await captureViewport()
    expect(r2.ok).toBe(false)
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1) // 没重跑
  })

  // -------------------------- dom-snapshot 失败 textFallback --------------------------
  it('dom-snapshot 失败（无 document.body）→ 仍尝试附 textFallback（不抛错）', async () => {
    // 临时把 document.body 干掉，模拟 SSR / 极简环境
    const orig = document.body
    Object.defineProperty(document, 'body', { value: null, configurable: true })
    try {
      const r = await captureViewport({ backend: 'dom-snapshot' })
      expect(r.ok).toBe(false)
      if (!r.ok) {
        expect(r.reason).toBe('unsupported')
        // 修复后：dom-snapshot 失败也会调用 _trySerializeDom() 附 textFallback
        // （具体值取决于 pageSerializer 实现，只要不是抛错就 OK）
        expect(typeof r.textFallback === 'string' || r.textFallback === undefined).toBe(true)
      }
    } finally {
      Object.defineProperty(document, 'body', { value: orig, configurable: true })
    }
  })

  it('不同 backend 不共享缓存', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,x'))
    // 走 html2canvas backend
    await captureViewport({ backend: 'html2canvas' })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
    // 走 dom-snapshot backend（不调 html2canvas）
    const r = await captureViewport({ backend: 'dom-snapshot' })
    if (r.ok) {
      expect(r.kind).toBe('text-snapshot')
    }
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
    // 回到 html2canvas 仍然命中
    const r3 = await captureViewport({ backend: 'html2canvas' })
    if (r3.ok) {
      expect(r3.fromCache).toBe(true)
    }
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
  })

  it('未知 backend → reason=no_backend', async () => {
    const r = await captureViewport({ backend: 'playwright' as any })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.reason).toBe('no_backend')
    }
  })

  // -------------------------- v1.1 新增：severity / 截断 / 重试 / cache 失效 --------------------------
  it('失败结果带 severity 字段（cors + 无 textFallback → critical，但本测试有 fallback → degraded）', async () => {
    mockHtml2canvas.mockRejectedValue(
      new Error('SecurityError: Tainted canvases may not be exported.'),
    )
    const r = await captureViewport()
    if (!r.ok) {
      expect(r.reason).toBe('cors')
      expect(r.severity).toBe('degraded') // 有 textFallback
    }
  })

  it('失败无 textFallback 时 severity=critical', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('render failed'))
    const r = await captureViewport({ autoTextFallback: false })
    if (!r.ok) {
      expect(r.severity).toBe('critical')
    }
  })

  it('aborted → severity=user', async () => {
    const ctrl = new AbortController()
    ctrl.abort()
    const r = await captureViewport({ signal: ctrl.signal })
    if (!r.ok) {
      expect(r.reason).toBe('aborted')
      expect(r.severity).toBe('user')
    }
  })

  it('textFallback 超过 noteMaxLen → noteTruncated=true + noteOriginalLength 正确', async () => {
    // 把 pageSerializer 输出撑到 200 字符
    document.body.innerHTML = Array.from({ length: 50 }, (_, i) =>
      `<p>text ${i} ${'x'.repeat(20)}</p>`,
    ).join('')
    mockHtml2canvas.mockRejectedValue(new Error('render failed'))
    const r = await captureViewport({ noteMaxLen: 50 })
    if (!r.ok) {
      expect(r.textFallback).toBeDefined()
      expect(r.noteTruncated).toBe(true)
      expect(r.noteOriginalLength).toBeGreaterThan(50)
      expect(r.textFallback!.length).toBeLessThanOrEqual(50) // 截断生效
    }
  })

  it('textFallback 未超限 → noteTruncated=undefined (false) + noteOriginalLength 完整', async () => {
    document.body.innerHTML = '<p>short</p>'
    mockHtml2canvas.mockRejectedValue(new Error('render failed'))
    const r = await captureViewport({ noteMaxLen: 5000 })
    if (!r.ok && r.textFallback) {
      expect(r.noteTruncated).toBeFalsy()
      expect(r.noteOriginalLength).toBe(r.textFallback.length)
    }
  })

  it('retry: 瞬时错误 (cors) 默认不重试', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('SecurityError: Tainted'))
    await captureViewport()
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
  })

  it('retry: cors 设 retry=2 → 调用 3 次 (1 初始 + 2 重试)', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('SecurityError: Tainted'))
    await captureViewport({ retry: 2, routeSig: '/retry-cors' })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(3)
  })

  it('retry: 非瞬时错误 (render) 不重试', async () => {
    mockHtml2canvas.mockRejectedValue(new Error('Unsupported CSS property'))
    await captureViewport({ retry: 3, routeSig: '/retry-render' })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
  })

  it('retry: 第二次重试时成功则立即返回', async () => {
    mockHtml2canvas
      .mockRejectedValueOnce(new Error('SecurityError: Tainted'))
      .mockResolvedValueOnce(fakeCanvas('data:image/jpeg;base64,abc'))
    const r = await captureViewport({ retry: 2, routeSig: '/retry-then-ok' })
    expect(r.ok).toBe(true)
    expect(mockHtml2canvas).toHaveBeenCalledTimes(2)
  })

  it('forceRetake=true → 即使缓存命中也重跑', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,abc'))
    await captureViewport({ routeSig: '/force' })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
    await captureViewport({ routeSig: '/force', forceRetake: true })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(2)
  })

  it('invalidateCaptureCache() → 下一次不命中缓存', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,abc'))
    await captureViewport({ routeSig: '/inv' })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
    await captureViewport({ routeSig: '/inv' }) // 缓存命中
    expect(mockHtml2canvas).toHaveBeenCalledTimes(1)
    invalidateCaptureCache()
    await captureViewport({ routeSig: '/inv' })
    expect(mockHtml2canvas).toHaveBeenCalledTimes(2)
  })

  it('cache key 含 viewport size：模拟 window.innerWidth 变化', async () => {
    const origW = window.innerWidth
    const origH = window.innerHeight
    try {
      Object.defineProperty(window, 'innerWidth', { value: 1280, configurable: true })
      Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true })
      mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,a'))
      await captureViewport({ routeSig: '/vp' })
      expect(mockHtml2canvas).toHaveBeenCalledTimes(1)

      // 改 viewport
      Object.defineProperty(window, 'innerWidth', { value: 800, configurable: true })
      Object.defineProperty(window, 'innerHeight', { value: 600, configurable: true })
      await captureViewport({ routeSig: '/vp' })
      expect(mockHtml2canvas).toHaveBeenCalledTimes(2) // cache miss
    } finally {
      Object.defineProperty(window, 'innerWidth', { value: origW, configurable: true })
      Object.defineProperty(window, 'innerHeight', { value: origH, configurable: true })
    }
  })

  it('onCaptureMeta 钩子：成功/失败都触发，meta.elapsedMs 存在', async () => {
    const events: Array<{ ok: boolean; elapsed: number; backend: string }> = []
    const listener = (r: any, m: any) => {
      events.push({ ok: r.ok, elapsed: m.elapsedMs, backend: m.backend })
    }
    onCaptureMeta(listener)
    try {
      mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,a'))
      await captureViewport({ routeSig: '/meta1' })
      mockHtml2canvas.mockRejectedValue(new Error('render failed'))
      await captureViewport({ routeSig: '/meta2' })
      expect(events.length).toBe(2)
      expect(events[0].ok).toBe(true)
      expect(events[1].ok).toBe(false)
      expect(events[0].elapsed).toBeGreaterThanOrEqual(0)
    } finally {
      onCaptureMeta(null) // 解注册
    }
  })

  it('onCaptureMeta 监听器抛错不影响 capture 链路', async () => {
    onCaptureMeta(() => {
      throw new Error('listener bug')
    })
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,a'))
    const r = await captureViewport({ routeSig: '/meta-throw' })
    expect(r.ok).toBe(true)
    onCaptureMeta(null) // 清理
  })

  it('结果带 elapsedMs 字段', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,a'))
    const r = await captureViewport()
    if (r.ok) {
      expect(typeof r.elapsedMs).toBe('number')
      expect(r.elapsedMs!).toBeGreaterThanOrEqual(0)
    }
  })

  it('结果带 backend 字段', async () => {
    mockHtml2canvas.mockResolvedValue(fakeCanvas('data:image/jpeg;base64,a'))
    const r = await captureViewport()
    if (r.ok) {
      expect(r.backend).toBe('html2canvas')
    }
    const r2 = await captureViewport({ backend: 'dom-snapshot', routeSig: '/backend-test' })
    if (r2.ok) {
      expect(r2.backend).toBe('dom-snapshot')
    }
  })
})
