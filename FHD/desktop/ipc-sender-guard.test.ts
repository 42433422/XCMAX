import { describe, expect, it } from 'vitest'
import {
  isTrustedIpcSender as checkSender,
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

const policy = { port: 17500, splashUrl: 'file:///Applications/XCAGI.app/Contents/Resources/splash.html' }
function isTrustedIpcSender(event: IpcSenderProbe, window: TrustedSenderWindow | null) {
  return checkSender(event, window, policy)
}

describe('isTrustedIpcSender（审计 R02 来源校验）', () => {
  const mainFrame = { url: 'http://127.0.0.1:17500/' }
  const window = fakeWindow(1, mainFrame)

  it('接受主窗口主框架的回环 http 来源', () => {
    expect(isTrustedIpcSender(fakeEvent(1, mainFrame), window)).toBe(true)
  })

  it('接受配置端口的 localhost 来源', () => {
    for (const url of ['http://localhost:17500/x']) {
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


it.each([
  'http://127.0.0.1:17501/', 'http://localhost/', 'http://[::1]:17500/',
  'file:///tmp/splash.html',
  'file:///Applications/XCAGI.app/Contents/Resources/splash.html.evil',
  'file:///Applications/XCAGI.app/Contents/Resources/splash.html#untrusted',
])('拒绝未授权端口或其他文件: %s', (url) => {
  const frame = { url }
  expect(checkSender(fakeEvent(1, frame), fakeWindow(1, frame), policy)).toBe(false)
})

it('尊重非默认运行端口而不信任旧默认端口', () => {
  for (const [port, expected] of [[18500, true], [17500, false]] as const) {
    const frame = { url: `http://127.0.0.1:${port}/` }
    expect(checkSender(fakeEvent(1, frame), fakeWindow(1, frame), { ...policy, port: 18500 })).toBe(expected)
  }
})

it.each(['', 'not a URL', 'data:text/html,splash'])('无文件信任配置时拒绝文件: %s', (splashUrl) => {
  const frame = { url: policy.splashUrl }
  expect(checkSender(fakeEvent(1, frame), fakeWindow(1, frame), { ...policy, splashUrl })).toBe(false)
})


it.each(['http://127.0.0.1/', 'http://localhost:80/'])('allows configured default HTTP port only: %s', (url) => {
  const frame = { url }
  const event = fakeEvent(1, frame)
  const window = fakeWindow(1, frame)
  expect(checkSender(event, window, { ...policy, port: 80 })).toBe(true)
  expect(checkSender(event, window, policy)).toBe(false)
})
