import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { i18n } from '@/i18n'
import { DEPLOYMENT_MODES } from '@/constants/deploymentModes.generated'
import { useSettingsBasics } from './useSettingsBasics'

const boundary = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), alert: vi.fn() }))
vi.mock('@/api', () => ({ default: boundary }))
vi.mock('@/utils/appDialog', () => ({ appAlert: boundary.alert }))
let wrapper: VueWrapper | undefined
let settings: ReturnType<typeof useSettingsBasics>
beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  i18n.global.locale.value = 'zh-CN'
  boundary.alert.mockResolvedValue(undefined)
  boundary.post.mockResolvedValue({ success: true })
  vi.stubGlobal('xcagiDesktop', undefined)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals(); vi.restoreAllMocks() })
async function open() {
  wrapper = mount(defineComponent({ setup() { settings = useSettingsBasics(); return {} }, template: '<div />' }))
  await flushPromises()
  return settings
}

describe('Mac settings runtime boundaries', () => {
  it.each(['1.0.0.5', ''])('reads the installed shell version %s rather than package metadata', async (version) => {
    const identity = vi.fn().mockResolvedValue({ version })
    vi.stubGlobal('xcagiDesktop', { getAppIdentity: identity })
    const ui = await open()
    expect(identity).toHaveBeenCalledTimes(1)
    expect(ui.appVersionLabel.value).toBe(version || '—')
    expect(ui.isDesktopShell.value).toBe(true)
  })

  it('keeps a failed installed identity unknown', async () => {
    vi.stubGlobal('xcagiDesktop', { getAppIdentity: vi.fn().mockRejectedValue(new Error('identity unavailable')) })
    const ui = await open()
    expect(ui.appVersionLabel.value).toBe('—')
  })

  it('loads deployment details, the redacted database address and the restart requirement', async () => {
    const ui = await open()
    boundary.get.mockResolvedValue({ data: { success: true, desktopMode: true, currentMode: 'performance', modes: DEPLOYMENT_MODES,
      database: { storageMode: 'remote_postgresql', databaseUrlRedacted: 'postgresql://***@db/xcagi', postgresUrlRedacted: 'postgresql://***@db/xcagi' },
      syncPlan: { syncCommand: 'xcagi-sync --dry-run' }, restartRequired: true } })
    await ui.loadDesktopDatabaseStatus()
    expect(boundary.get).toHaveBeenCalledExactlyOnceWith('/api/desktop/deployment')
    expect(ui.deploymentMode.value).toBe('performance')
    expect(ui.currentDbPath.value).toBe('postgresql://***@db/xcagi')
    expect(ui.postgresConfigured.value).toBe(true)
    expect(ui.deploymentRestartRequired.value).toBe(true)
    expect(ui.databaseStorageLabel.value).toBe('远程 PostgreSQL')
    expect(ui.deploymentModeBadge.value).toContain('3级')
    expect(ui.deploymentTransitionText.value).not.toBe('')
  })

  it('normalizes an unsupported backend mode to safe local storage', async () => {
    const ui = await open()
    boundary.get.mockResolvedValue({ success: true, currentMode: 'unsupported', database: { storageMode: 'local_sqlite', sqlitePath: '/data/xcagi.db' } })
    await ui.loadDesktopDatabaseStatus()
    expect(ui.deploymentMode.value).toBe('safe')
    expect(ui.currentDbPath.value).toBe('/data/xcagi.db')
    expect(ui.aiMode.value).toBe('online')
    expect(ui.postgresConfigured.value).toBe(false)
    expect(ui.deploymentSyncCommand.value).toBe('')
  })

  it('falls back to an older desktop API and clears stale paths when the desktop disappears', async () => {
    const ui = await open()
    boundary.get.mockRejectedValueOnce(new Error('old backend')).mockResolvedValueOnce({ data: { desktopMode: true, storageMode: 'local_sqlite', database: '/old/xcagi.db' } })
    await ui.loadDesktopDatabaseStatus()
    expect(ui.desktopDatabaseVisible.value).toBe(true)
    expect(ui.currentDbPath.value).toBe('/old/xcagi.db')
    boundary.get.mockResolvedValue({ desktopMode: false })
    await ui.loadDesktopDatabaseStatus()
    expect(ui.desktopDatabaseVisible.value).toBe(false)
    expect(ui.currentDbPath.value).toBe('')
    expect(ui.databaseStorageLabel.value).toBe('')
  })

  it('prevents performance-mode writes until a PostgreSQL connection is configured', async () => {
    const ui = await open()
    ui.desktopDatabaseVisible.value = true
    ui.deploymentMode.value = 'performance'
    await ui.saveSettings()
    expect(boundary.put).not.toHaveBeenCalled()
    expect(boundary.post).not.toHaveBeenCalled()
    expect(boundary.alert).toHaveBeenCalledWith(expect.stringContaining('PostgreSQL'))
    expect(ui.loading.value).toBe(false)
  })

  it('saves a configured deployment, preserves its sync receipt, and announces the normalized assistant name', async () => {
    const ui = await open()
    ui.desktopDatabaseVisible.value = true
    ui.deploymentMode.value = 'performance'
    ui.postgresUrlDraft.value = '  postgresql://test@localhost/test_db  '
    ui.assistantName.value = '  Mac验收助手  '
    boundary.put.mockResolvedValue({ data: { success: true, database: { storageMode: 'remote_postgresql', databaseUrlRedacted: 'postgresql://***@localhost/test_db' }, restartRequired: true, syncPlan: { syncCommand: 'xcagi-sync --dry-run' } } })
    const notice = vi.fn()
    window.addEventListener('assistant-name-updated', notice)
    try {
      await ui.saveSettings()
      expect(boundary.put).toHaveBeenCalledExactlyOnceWith('/api/desktop/deployment', { mode: 'performance', postgresUrl: 'postgresql://test@localhost/test_db' })
      expect(boundary.post).toHaveBeenCalledWith('/api/preferences', { user_id: 'default', key: 'assistantName', value: 'Mac验收助手' })
      expect(localStorage.getItem('assistantName')).toBe('Mac验收助手')
      expect(notice.mock.calls[0][0].detail.name).toBe('Mac验收助手')
      expect(ui.postgresConfigured.value).toBe(true)
      expect(ui.deploymentRestartRequired.value).toBe(true)
      expect(ui.deploymentSyncCommand.value).toBe('xcagi-sync --dry-run')
      expect(boundary.alert).toHaveBeenCalledWith(expect.stringContaining('重启'))
      expect(ui.deploymentSaving.value).toBe(false)
    } finally { window.removeEventListener('assistant-name-updated', notice) }
  })

  it('preserves a current path when the save receipt has no database address and omits an empty draft', async () => {
    const ui = await open()
    ui.desktopDatabaseVisible.value = true
    ui.currentDbPath.value = '/data/xcagi.db'
    boundary.put.mockResolvedValue({ success: true })
    await ui.saveDeploymentSettings()
    expect(boundary.put).toHaveBeenCalledExactlyOnceWith('/api/desktop/deployment', { mode: 'safe' })
    expect(ui.currentDbPath.value).toBe('/data/xcagi.db')
    expect(ui.deploymentRestartRequired.value).toBe(false)
    expect(ui.deploymentStatusMessage.value).toBe('部署模式配置已写入。')
  })

  it('does not save preferences or publish success after a failed deployment write', async () => {
    const ui = await open()
    ui.desktopDatabaseVisible.value = true
    boundary.put.mockResolvedValue({ success: false })
    vi.spyOn(console, 'error').mockImplementation(() => {})
    await ui.saveSettings()
    expect(boundary.post).not.toHaveBeenCalled()
    expect(localStorage.getItem('assistantName')).toBeNull()
    expect(boundary.alert).toHaveBeenCalledWith(expect.stringContaining('失败'))
    expect(ui.deploymentSaving.value).toBe(false)
    expect(ui.loading.value).toBe(false)
  })

  it.each(['local', 'online'])('migrates a legacy %s model preference while retaining the assistant name', async (model) => {
    const ui = await open()
    boundary.get.mockResolvedValue({ success: true, preferences: { aiModel: model, assistantName: '升级前助手' } })
    await ui.loadPreferences()
    expect(ui.aiMode.value).toBe(model === 'local' ? 'offline' : 'online')
    expect(localStorage.getItem('assistantName')).toBe('升级前助手')
    expect(boundary.post).toHaveBeenCalledExactlyOnceWith('/api/preferences', { user_id: 'default', key: 'aiMode', value: model === 'local' ? 'offline' : 'online' })
  })

  it('clears a deferred-update marker before asking the installed shell to check', async () => {
    const check = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('xcagiDesktop', { checkForUpdates: check })
    sessionStorage.setItem('xcagi_desktop_update_dismiss_version', '1.0.0.5')
    const ui = await open()
    await ui.onCheckForUpdates()
    expect(check).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('xcagi_desktop_update_dismiss_version')).toBeNull()
    expect(ui.aboutUpdateMessage.value).toContain('已开始检查更新')
    expect(ui.aboutUpdateError.value).toBe(false)
    expect(ui.aboutUpdateBusy.value).toBe(false)
  })

  it.each([undefined, new Error('feed unavailable')])('reports an unavailable or failing update checker', async (failure) => {
    if (failure) vi.stubGlobal('xcagiDesktop', { checkForUpdates: vi.fn().mockRejectedValue(failure) })
    const ui = await open()
    await ui.onCheckForUpdates()
    expect(ui.aboutUpdateError.value).toBe(true)
    expect(ui.aboutUpdateBusy.value).toBe(false)
    expect(ui.aboutUpdateMessage.value).toContain(failure ? 'feed unavailable' : '不支持自动更新')
  })

  it('reads and saves the Mac login-item setting only after shell acknowledgement', async () => {
    const save = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('xcagiDesktop', { getAutoLaunch: vi.fn().mockResolvedValue(true), setAutoLaunch: save })
    const ui = await open()
    await ui.loadAutoLaunch()
    expect(ui.autoLaunch.value).toBe(true)
    await ui.onAutoLaunchChange(false)
    expect(save).toHaveBeenCalledExactlyOnceWith(false)
    expect(ui.autoLaunch.value).toBe(false)
    expect(ui.autoLaunchMessage.value).toBe('开机自启动设置已保存')
  })

  it.each(['rejected', 'exception', 'no-reason'])('rolls back an unsuccessful %s Mac login-item change', async (failure) => {
    const save = failure === 'exception' ? vi.fn().mockRejectedValue(new Error('shell unavailable')) : vi.fn().mockResolvedValue({ ok: false, reason: failure === 'rejected' ? '系统拒绝' : '' })
    vi.stubGlobal('xcagiDesktop', { getAutoLaunch: vi.fn().mockRejectedValue(new Error('unavailable')), setAutoLaunch: save })
    const ui = await open()
    await ui.loadAutoLaunch()
    expect(ui.autoLaunch.value).toBe(false)
    await ui.onAutoLaunchChange(true)
    expect(ui.autoLaunch.value).toBe(false)
    expect(ui.autoLaunchBusy.value).toBe(false)
    expect(ui.autoLaunchMessage.value).toContain('失败')
    if (failure === 'rejected') expect(ui.autoLaunchMessage.value).toContain('系统拒绝')
  })

  it('ignores login-item operations when the shell does not provide them', async () => {
    const ui = await open()
    await ui.loadAutoLaunch()
    await ui.onAutoLaunchChange(true)
    expect(ui.autoLaunch.value).toBe(false)
    expect(ui.autoLaunchBusy.value).toBe(false)
  })
})
