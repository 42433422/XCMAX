/**
 * Coverage ramp 测试：utils/index.ts
 *
 * 目标：覆盖所有导出函数的全部分支
 * - escapeHtml：null/undefined/特殊字符/普通字符串
 * - generateSessionId：格式与唯一性
 * - getFilenameFromDisposition：null/UTF-8 成功/UTF-8 解码失败/plain 匹配/无匹配
 * - downloadBlob：创建链接、点击、清理
 * - formatDate / formatTime：各种日期输入
 * - debounce：延迟调用、清除、多次调用
 * - throttle：首次立即调用、限流期内不调用、限流结束后恢复
 *
 * 铁律4：纯工具函数无需 mock；downloadBlob 仅 mock DOM 边界
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  escapeHtml,
  generateSessionId,
  getFilenameFromDisposition,
  downloadBlob,
  formatDate,
  formatTime,
  debounce,
  throttle,
} from './index'

describe('utils/index — coverage ramp', () => {
  // ── escapeHtml ────────────────────────────────────────────────

  describe('escapeHtml', () => {
    it('null 转为空字符串', () => {
      expect(escapeHtml(null)).toBe('')
    })

    it('undefined 转为空字符串', () => {
      expect(escapeHtml(undefined)).toBe('')
    })

    it('转义 & 符号', () => {
      expect(escapeHtml('a&b')).toBe('a&amp;b')
    })

    it('转义 < 符号', () => {
      expect(escapeHtml('a<b')).toBe('a&lt;b')
    })

    it('转义 > 符号', () => {
      expect(escapeHtml('a>b')).toBe('a&gt;b')
    })

    it('转义 " 符号', () => {
      expect(escapeHtml('a"b')).toBe('a&quot;b')
    })

    it('转义 \' 符号', () => {
      expect(escapeHtml("a'b")).toBe('a&#39;b')
    })

    it('同时转义所有特殊字符', () => {
      expect(escapeHtml('<div class="a">&\'test\'</div>')).toBe(
        '&lt;div class=&quot;a&quot;&gt;&amp;&#39;test&#39;&lt;/div&gt;',
      )
    })

    it('数字被 String 转换后返回', () => {
      expect(escapeHtml(123)).toBe('123')
    })

    it('普通字符串原样返回', () => {
      expect(escapeHtml('hello world')).toBe('hello world')
    })

    it('空字符串返回空字符串', () => {
      expect(escapeHtml('')).toBe('')
    })
  })

  // ── generateSessionId ─────────────────────────────────────────

  describe('generateSessionId', () => {
    it('返回以 session_ 开头的字符串', () => {
      const id = generateSessionId()
      expect(id.startsWith('session_')).toBe(true)
    })

    it('包含时间戳和随机部分', () => {
      const id = generateSessionId()
      // 格式：session_<timestamp>_<random>
      const parts = id.split('_')
      expect(parts).toHaveLength(3)
      expect(parts[0]).toBe('session')
      expect(parts[1]).toMatch(/^\d+$/)
      expect(parts[2].length).toBeGreaterThan(0)
    })

    it('多次调用生成不同 ID', () => {
      const id1 = generateSessionId()
      const id2 = generateSessionId()
      expect(id1).not.toBe(id2)
    })
  })

  // ── getFilenameFromDisposition ────────────────────────────────

  describe('getFilenameFromDisposition', () => {
    it('disposition 为 null 时返回默认文件名', () => {
      expect(getFilenameFromDisposition(null)).toBe('下载文件.xlsx')
    })

    it('disposition 为空字符串时返回默认文件名', () => {
      expect(getFilenameFromDisposition('')).toBe('下载文件.xlsx')
    })

    it('自定义 fallback', () => {
      expect(getFilenameFromDisposition(null, 'default.pdf')).toBe('default.pdf')
    })

    it('UTF-8 编码的文件名被正确解码', () => {
      const encoded = encodeURIComponent('测试文件.xlsx')
      const disposition = `attachment; filename*=UTF-8''${encoded}`
      expect(getFilenameFromDisposition(disposition)).toBe('测试文件.xlsx')
    })

    it('UTF-8 编码但解码失败时回退到 plain 匹配', () => {
      // 包含 % 但不是合法的 URI 编码 → decodeURIComponent 抛错 → 进入 plain 分支
      const disposition = `attachment; filename*=UTF-8''%E4%BD; filename=fallback.xlsx`
      // %E4%BD 不是完整的 UTF-8 序列，decodeURIComponent 会抛错
      // 然后回退到 plain filename 匹配
      expect(getFilenameFromDisposition(disposition)).toBe('fallback.xlsx')
    })

    it('plain filename 匹配（不带引号）', () => {
      const disposition = 'attachment; filename=report.pdf'
      expect(getFilenameFromDisposition(disposition)).toBe('report.pdf')
    })

    it('plain filename 匹配（带引号）', () => {
      const disposition = 'attachment; filename="report.pdf"'
      expect(getFilenameFromDisposition(disposition)).toBe('report.pdf')
    })

    it('UTF-8 和 plain 都无匹配时返回 fallback', () => {
      const disposition = 'attachment; size=1024'
      expect(getFilenameFromDisposition(disposition)).toBe('下载文件.xlsx')
    })

    it('UTF-8 匹配优先于 plain 匹配', () => {
      const encoded = encodeURIComponent('优先文件.xlsx')
      const disposition = `attachment; filename*=UTF-8''${encoded}; filename=plain.xlsx`
      expect(getFilenameFromDisposition(disposition)).toBe('优先文件.xlsx')
    })

    it('UTF-8 匹配但 group 为空时回退到 plain', () => {
      // filename*=UTF-8'' 后面紧跟分号（空值）→ utf8Match[1] 为空
      // 实际正则 ([^;]+) 要求至少一个字符，所以空值不会匹配
      // 这里测试 UTF-8 部分有值但解码失败的场景
      const disposition = `attachment; filename*=UTF-8''%ZZ; filename=plain.xlsx`
      expect(getFilenameFromDisposition(disposition)).toBe('plain.xlsx')
    })
  })

  // ── downloadBlob ──────────────────────────────────────────────

  describe('downloadBlob', () => {
    let createObjectURLSpy: ReturnType<typeof vi.spyOn>
    let revokeObjectURLSpy: ReturnType<typeof vi.spyOn>
    let clickSpy: ReturnType<typeof vi.spyOn>
    let removeSpy: ReturnType<typeof vi.spyOn>
    let appendChildSpy: ReturnType<typeof vi.spyOn>

    beforeEach(() => {
      // jsdom 未实现 URL.createObjectURL / revokeObjectURL，先注入桩
      if (typeof URL.createObjectURL !== 'function') {
        Object.defineProperty(URL, 'createObjectURL', {
          value: () => 'blob:mock-url',
          configurable: true,
          writable: true,
        })
      }
      if (typeof URL.revokeObjectURL !== 'function') {
        Object.defineProperty(URL, 'revokeObjectURL', {
          value: () => undefined,
          configurable: true,
          writable: true,
        })
      }
      createObjectURLSpy = vi
        .spyOn(URL, 'createObjectURL')
        .mockReturnValue('blob:mock-url')
      revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
      clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
      removeSpy = vi.spyOn(Element.prototype, 'remove').mockImplementation(() => undefined)
      appendChildSpy = vi.spyOn(document.body, 'appendChild').mockImplementation(() => null as never)
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('创建对象 URL 并触发点击下载', () => {
      const blob = new Blob(['data'], { type: 'text/plain' })
      downloadBlob(blob, 'test.txt')

      expect(createObjectURLSpy).toHaveBeenCalledWith(blob)
      expect(clickSpy).toHaveBeenCalled()
    })

    it('设置链接的 href 和 download 属性', () => {
      const blob = new Blob(['data'])
      downloadBlob(blob, 'report.pdf')

      // appendChild 被调用，传入的是 <a> 元素
      const link = appendChildSpy.mock.calls[0][0] as HTMLAnchorElement
      expect(link.href).toBe('blob:mock-url')
      expect(link.download).toBe('report.pdf')
      expect(link.style.display).toBe('none')
    })

    it('setTimeout 后移除链接并释放 URL', async () => {
      const blob = new Blob(['data'])
      downloadBlob(blob, 'test.txt')

      // setTimeout(..., 0) 尚未执行
      expect(removeSpy).not.toHaveBeenCalled()
      expect(revokeObjectURLSpy).not.toHaveBeenCalled()

      // 等待 setTimeout(0) 执行
      await new Promise((resolve) => setTimeout(resolve, 10))

      expect(removeSpy).toHaveBeenCalled()
      expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url')
    })
  })

  // ── formatDate ────────────────────────────────────────────────

  describe('formatDate', () => {
    it('格式化 Date 对象', () => {
      const date = new Date(2026, 0, 15) // 2026-01-15
      const result = formatDate(date)
      // zh-CN locale 格式：2026/01/15
      expect(result).toMatch(/2026.*01.*15/)
    })

    it('格式化时间戳数字', () => {
      const timestamp = new Date(2026, 5, 1).getTime()
      const result = formatDate(timestamp)
      expect(result).toMatch(/2026.*06.*01/)
    })

    it('格式化日期字符串', () => {
      const result = formatDate('2026-06-19')
      expect(result).toMatch(/2026.*06.*19/)
    })
  })

  // ── formatTime ────────────────────────────────────────────────

  describe('formatTime', () => {
    it('格式化 Date 对象', () => {
      const date = new Date(2026, 0, 1, 14, 30)
      const result = formatTime(date)
      expect(result).toMatch(/14.*30/)
    })

    it('格式化时间戳数字', () => {
      const timestamp = new Date(2026, 0, 1, 9, 5).getTime()
      const result = formatTime(timestamp)
      expect(result).toMatch(/09.*05/)
    })

    it('格式化日期时间字符串', () => {
      const result = formatTime('2026-06-19T14:30:00')
      expect(result).toMatch(/14.*30/)
    })
  })

  // ── debounce ──────────────────────────────────────────────────

  describe('debounce', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('在 wait 毫秒后调用函数', () => {
      const func = vi.fn()
      const debounced = debounce(func, 100)

      debounced()
      expect(func).not.toHaveBeenCalled()

      vi.advanceTimersByTime(100)
      expect(func).toHaveBeenCalledOnce()
    })

    it('连续调用时只执行最后一次', () => {
      const func = vi.fn()
      const debounced = debounce(func, 100)

      debounced('a')
      debounced('b')
      debounced('c')

      vi.advanceTimersByTime(100)
      expect(func).toHaveBeenCalledOnce()
      expect(func).toHaveBeenCalledWith('c')
    })

    it('在 wait 内再次调用会重置计时器', () => {
      const func = vi.fn()
      const debounced = debounce(func, 100)

      debounced()
      vi.advanceTimersByTime(50)
      expect(func).not.toHaveBeenCalled()

      debounced()
      vi.advanceTimersByTime(50)
      expect(func).not.toHaveBeenCalled()

      vi.advanceTimersByTime(50)
      expect(func).toHaveBeenCalledOnce()
    })

    it('传递多个参数', () => {
      const func = vi.fn()
      const debounced = debounce(func, 100)

      debounced(1, 'two', { three: 3 })
      vi.advanceTimersByTime(100)

      expect(func).toHaveBeenCalledWith(1, 'two', { three: 3 })
    })

    it('不调用时函数不执行', () => {
      const func = vi.fn()
      const debounced = debounce(func, 100)

      vi.advanceTimersByTime(500)
      expect(func).not.toHaveBeenCalled()
    })
  })

  // ── throttle ──────────────────────────────────────────────────

  describe('throttle', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('首次调用立即执行', () => {
      const func = vi.fn()
      const throttled = throttle(func, 100)

      throttled()
      expect(func).toHaveBeenCalledOnce()
    })

    it('限流期内不重复执行', () => {
      const func = vi.fn()
      const throttled = throttle(func, 100)

      throttled()
      throttled()
      throttled()

      expect(func).toHaveBeenCalledOnce()
    })

    it('限流结束后恢复执行', () => {
      const func = vi.fn()
      const throttled = throttle(func, 100)

      throttled()
      vi.advanceTimersByTime(100)
      throttled()

      expect(func).toHaveBeenCalledTimes(2)
    })

    it('传递参数和 this 上下文', () => {
      const func = vi.fn()
      const throttled = throttle(func, 100)
      const ctx = { name: 'ctx' }

      throttled.call(ctx, 'arg1', 'arg2')
      expect(func).toHaveBeenCalledWith('arg1', 'arg2')
      expect(func.mock.instances[0]).toBe(ctx)
    })

    it('限流期内多次调用后只恢复一次执行', () => {
      const func = vi.fn()
      const throttled = throttle(func, 100)

      throttled()
      // 限流期内多次调用
      throttled()
      throttled()
      throttled()
      // 限流结束
      vi.advanceTimersByTime(100)

      // 仍然只执行了一次（首次调用）
      expect(func).toHaveBeenCalledOnce()

      // 限流结束后再次调用才会执行第二次
      throttled()
      expect(func).toHaveBeenCalledTimes(2)
    })
  })
})
