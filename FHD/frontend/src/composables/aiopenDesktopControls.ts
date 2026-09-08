/** Native commands share the authenticated screen queue; no arbitrary IPC channel calls. */
type DesktopBridge = {
  getAppIdentity?: () => Promise<unknown>
  getUpdateStatus?: () => Promise<unknown>
  getUpdateObservation?: () => Promise<unknown>
  getAutoLaunch?: () => Promise<boolean>
  setAutoLaunch?: (enabled: boolean) => Promise<unknown>
  checkForUpdates?: () => Promise<unknown>
  downloadUpdate?: () => Promise<unknown>
  installUpdate?: () => Promise<unknown>
}

function rejected(result: unknown): boolean {
  return result === false || Boolean(result && typeof result === 'object' && (('ok' in result && result.ok === false) || ('success' in result && result.success === false)))
}

export async function executeDesktopControl(action: string, params: Record<string, unknown>, assertCurrent: () => void): Promise<Record<string, unknown>> {
  const bridge = (window as Window & { xcagiDesktop?: DesktopBridge }).xcagiDesktop
  if (!bridge) return { success: false, code: 'DESKTOP_REQUIRED', message: '当前窗口没有桌面原生桥接' }
  assertCurrent()
  if (action === 'desktop_info') {
    if (!bridge.getAppIdentity || !bridge.getUpdateStatus || !bridge.getAutoLaunch) {
      return { success: false, code: 'DESKTOP_BRIDGE_OUTDATED', message: '当前桌面桥接缺少所需接口' }
    }
    const identity = await bridge.getAppIdentity()
    assertCurrent()
    const update = bridge.getUpdateObservation
      ? await bridge.getUpdateObservation()
      : { legacy_status: await bridge.getUpdateStatus(), observation_complete: false }
    assertCurrent()
    const autoLaunch = await bridge.getAutoLaunch()
    assertCurrent()
    if (typeof autoLaunch !== 'boolean') throw new Error('桌面返回的开机启动状态无效')
    return { success: true, identity, update, auto_launch: autoLaunch, verification: 'native_readback' }
  }
  if (action === 'desktop_auto_launch') {
    if (typeof params.enabled !== 'boolean') throw new Error('enabled 必须是布尔值')
    if (!bridge.setAutoLaunch || !bridge.getAutoLaunch) throw new Error('当前桌面不支持开机启动设置')
    const result = await bridge.setAutoLaunch(params.enabled)
    assertCurrent()
    if (rejected(result)) return { success: false, result, verification: 'native_rejected' }
    const actual = await bridge.getAutoLaunch()
    assertCurrent()
    return { success: actual === params.enabled, enabled: actual, verification: 'native_readback' }
  }
  if (action === 'desktop_update') {
    const operation = params.operation
    const method = operation === 'check' ? bridge.checkForUpdates : operation === 'download' ? bridge.downloadUpdate : operation === 'install' ? bridge.installUpdate : undefined
    if (!method) throw new Error('更新操作无效或当前桌面不支持该操作')
    const result = await method.call(bridge)
    assertCurrent()
    if (rejected(result)) {
      return { success: false, operation, result, verification: 'native_rejected' }
    }
    if (result && typeof result === 'object' && 'skipped' in result && result.skipped === true) {
      return { success: false, code: 'UPDATE_SKIPPED', operation, result, verification: 'not_executed' }
    }
    return { success: true, operation, result, verification: 'native_request_returned', requires_followup: true }
  }
  throw new Error('未知桌面操作')
}
