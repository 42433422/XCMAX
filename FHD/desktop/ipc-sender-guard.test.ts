import { describe, expect, it } from 'vitest'
import {
  isTrustedIpcSender,
  type IpcSenderProbe,
  type TrustedSenderWindow,
} from './ipc-sender-guard'

function fakeWindow(webContentsId: number, mainFrame: unknown): TrustedSenderWindow {
  return {
    isDestroyed: () => false,
    webContents: { id: webContentsId, mainFrame },
  }
}

function fakeEvent(senderId: number, senderFrame: IpcSenderProbe['senderFrame']): IpcSenderProbe {
  return { sender: { id: senderId }, senderFrame }
}

describe('isTrustedIpcSender（审计 R02 来源校验）', () => {
  const mainFrame = { url: 'http://127.0.0.1:17500/' }
  const window = fakeWindow(1, mainFrame)

  it('接受主窗口主框架的回环 http 来源', () => {
    expect(isTrustedIpcSender(fakeEvent(1, mainFrame), window)).toBe(true)
  })

  it('接受 localhost 与 ::1 回环来源', () => {
    for (const url of ['http://localhost:17500/x', 'http://[::1]:17500/']) {
      const frame = { url }
      expect(isTrustedIpcSender(fakeEvent(1, frame), fakeWindow(1, frame))).toBe(true)
    }
  })

  it('接受 file 协议 splash 来源', () => {
    const frame = { url: 'file:///Applications/XCAGI.app/Contents/Resources/splash.html' }
    expect(isTrustedIpcSender(fakeEvent(1, frame), fakeWindow(1, frame))).toBe(true)
  })

  it('拒绝非主窗口 webContents', () => {
    expect(isTrustedIpcSender(fakeEvent(2, mainFrame), window)).toBe(false)
  })

  it('拒绝子 frame（senderFrame 非主框架）', () => {
    const childFrame = { url: 'http://127.0.0.1:17500/embedded' }
    expect(isTrustedIpcSender(fakeEvent(1, childFrame), window)).toBe(false)
  })

  it('拒绝 senderFrame 缺失', () => {
    expect(isTrustedIpcSender(fakeEvent(1, null), window)).toBe(false)
  })

  it('拒绝导航后的外部 http 来源', () => {
    const evilFrame = { url: 'http://evil.example.com/' }
    expect(isTrustedIpcSender(fakeEvent(1, evilFrame), fakeWindow(1, evilFrame))).toBe(false)
  })

  it('拒绝 https 外部与 data: 注入来源', () => {
    for (const url of ['https://attacker.example/', 'data:text/html,<script>1</script>']) {
      const frame = { url }
      expect(isTrustedIpcSender(fakeEvent(1, frame), fakeWindow(1, frame))).toBe(false)
    }
  })

  it('拒绝非法/空 URL 的 frame', () => {
    for (const url of ['', 'not a url']) {
      const frame = { url }
      expect(isTrustedIpcSender(fakeEvent(1, frame), fakeWindow(1, frame))).toBe(false)
    }
  })

  it('主窗口销毁或不存在时一律拒绝', () => {
    expect(isTrustedIpcSender(fakeEvent(1, mainFrame), null)).toBe(false)
    const destroyed: TrustedSenderWindow = {
      isDestroyed: () => true,
      webContents: { id: 1, mainFrame },
    }
    expect(isTrustedIpcSender(fakeEvent(1, mainFrame), destroyed)).toBe(false)
  })
})
