import { describe, it, expect, vi, beforeEach } from 'vitest'
import { usePageAnalyzer } from './usePageAnalyzer'

// vue-router 最小 mock：仅取 fullPath
vi.mock('vue-router', () => ({
  useRoute: () => ({ fullPath: '/workbench/mod/testmod' }),
}))

vi.mock('../../utils/agent/pageSerializer', () => ({
  serializeVisibleDom: () => '页面标题：测试页\n当前路径：/workbench/mod/testmod',
}))

vi.mock('../../utils/agent/screenshotCapture', () => ({
  captureViewport: vi.fn(),
}))

import { captureViewport } from '../../utils/agent/screenshotCapture'
const mockCapture = captureViewport as unknown as ReturnType<typeof vi.fn>

describe('usePageAnalyzer', () => {
  beforeEach(() => {
    mockCapture.mockReset()
  })

  it('getPageContext 返回带路由前缀的 DOM 串', () => {
    const { getPageContext } = usePageAnalyzer()
    const text = getPageContext()
    expect(text).toContain('路由：/workbench/mod/testmod')
    expect(text).toContain('页面标题：测试页')
  })

  it('getPageContext 默认对 PII 做脱敏（redact=true）', () => {
    // 验证 redact 流程在无 PII 时不报错
    const { getPageContext } = usePageAnalyzer()
    const text = getPageContext()
    expect(typeof text).toBe('string')
    expect(text).toContain('路由：/workbench/mod/testmod')
  })

  it('getPageContext({ redact: false }) 跳过脱敏', () => {
    const { getPageContext } = usePageAnalyzer()
    const textOn = getPageContext({ redact: true })
    const textOff = getPageContext({ redact: false })
    // 当前 mock 的 DOM 没 PII，两者一致
    expect(textOn).toBe(textOff)
  })

  it('getPageContextWithScreenshot 成功（image） → 透传 CaptureResult', async () => {
    mockCapture.mockResolvedValue({
      ok: true,
      kind: 'image',
      dataUrl: 'data:image/jpeg;base64,xxx',
      bytes: 100,
    })
    const { getPageContextWithScreenshot } = usePageAnalyzer()
    const out = await getPageContextWithScreenshot()
    expect(out.textSummary).toContain('路由：')
    expect(out.screenshot.ok).toBe(true)
    if (out.screenshot.ok) {
      expect(out.screenshot.kind).toBe('image')
      expect(out.screenshot.dataUrl).toContain('base64,')
    }
  })

  it('getPageContextWithScreenshot 成功（text-snapshot） → 透传 kind', async () => {
    mockCapture.mockResolvedValue({
      ok: true,
      kind: 'text-snapshot',
      dataUrl: 'data:application/json;base64,eyJrbmluZCI6InRleHQifQ==',
      bytes: 13,
    })
    const { getPageContextWithScreenshot } = usePageAnalyzer()
    const out = await getPageContextWithScreenshot()
    if (out.screenshot.ok) {
      expect(out.screenshot.kind).toBe('text-snapshot')
    }
  })

  it('getPageContextWithScreenshot 失败带 textFallback → 透传', async () => {
    mockCapture.mockResolvedValue({
      ok: false,
      reason: 'cors',
      message: 'tainted canvas',
      textFallback: '页面标题：测试页',
    })
    const { getPageContextWithScreenshot } = usePageAnalyzer()
    const out = await getPageContextWithScreenshot()
    expect(out.screenshot.ok).toBe(false)
    if (!out.screenshot.ok) {
      expect(out.screenshot.reason).toBe('cors')
      expect(out.screenshot.message).toBe('tainted canvas')
      expect(out.screenshot.textFallback).toBe('页面标题：测试页')
    }
    // textSummary 必须仍可用——下游 LLM 链路至少还有文本上下文
    expect(out.textSummary.length).toBeGreaterThan(0)
  })

  it('screenshot options 透传给 captureViewport', async () => {
    mockCapture.mockResolvedValue({
      ok: true,
      kind: 'image',
      dataUrl: 'data:image/jpeg;base64,x',
      bytes: 1,
    })
    const { getPageContextWithScreenshot } = usePageAnalyzer()
    await getPageContextWithScreenshot({
      screenshot: { scale: 1.0, quality: 0.9, ignoreSelectors: ['.x'] },
    })
    expect(mockCapture).toHaveBeenCalledWith({
      scale: 1.0,
      quality: 0.9,
      ignoreSelectors: ['.x'],
    })
  })

  it('backend 选项透传', async () => {
    mockCapture.mockResolvedValue({
      ok: true,
      kind: 'text-snapshot',
      dataUrl: 'data:application/json;base64,e30=',
      bytes: 2,
    })
    const { getPageContextWithScreenshot } = usePageAnalyzer()
    await getPageContextWithScreenshot({ screenshot: { backend: 'dom-snapshot' } })
    expect(mockCapture).toHaveBeenCalledWith({ backend: 'dom-snapshot' })
  })
})
