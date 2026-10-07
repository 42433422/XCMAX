import { describe, expect, it } from 'vitest'
import { useWorkflowPanelDisplay } from './useWorkflowPanelDisplay'
import type { PhoneAgentStatusPayload } from './phoneAgentStatus'
import type { ModInfo } from '@/types/modInfo'

function panel(channel = 'wechat', loaded = true) {
  const employee = { id: 'customer-call', label: '客户电话员工', phone_channel: channel, phone_agent_api_base: '/api/mod/customer-service/phone-agent/' }
  const mod: ModInfo = { id: 'customer-service', name: '客户服务', version: '1', author: 'test', description: '', workflow_employees: [employee] }
  return useWorkflowPanelDisplay({ getModsForUi: () => loaded ? [mod] : [] })
}
function display(status?: PhoneAgentStatusPayload, channel = 'wechat', loaded = true) {
  const ui = panel(channel, loaded)
  const steps = ui.buildWorkflowStepsForEmployee('customer-call', { phoneStatus: status })
  return {
    steps,
    monitor: ui.buildWorkflowMonitorLine('customer-call', steps, undefined, undefined, undefined, undefined, undefined, status),
    hint: ui.computeWorkflowCurrentHint('customer-call', steps, undefined, undefined, undefined, undefined, undefined, status),
    stage: ui.computeWorkflowStageLine('customer-call', undefined, undefined, undefined, undefined, status),
  }
}

describe('Loaded employee state presentation', () => {
  it('keeps an unloaded extension distinct from a connecting authorized extension', () => {
    const absent = display(undefined, 'wechat', false)
    expect(absent.monitor).toContain('已关闭 Mod 界面')
    expect(absent.hint).toContain('未加载 Mod 电话扩展')
    expect(panel('wechat', false).getPhoneAgentApiBase('customer-call')).toBe('')
    const loaded = display()
    expect(loaded.monitor).toBe('电话状态同步中…')
    expect(loaded.hint).toContain('/api/mod/customer-service/phone-agent/status')
    expect(loaded.steps.map((step) => step.status)).toEqual(['done', 'pending', 'pending', 'pending', 'pending', 'pending'])
    expect(loaded.stage).toBe('待命 · 同步状态中')
  })

  it.each([true, false])('reports a failed status fetch with loaded=%s instead of healthy status', (loaded) => {
    const result = display({ fetchError: 'HTTP 502' }, 'wechat', loaded)
    expect(result.monitor).toContain('无法拉取')
    expect(result.monitor).toContain('HTTP 502')
    expect(result.hint).toBe('状态接口异常：HTTP 502')
  })

  it.each([
    ['phone_agent_get_status_failed', 'phone_agent_get_status_message', 'get_status'],
    ['phone_agent_status_route_failed', 'phone_agent_status_route_message', '接口异常'],
    ['phone_agent_manager_load_failed', 'phone_agent_manager_load_message', '管理器未加载'],
  ] as const)('reports %s with its backend detail or a log fallback', (flag, message, text) => {
    const unavailable = display({ [flag]: true })
    expect(unavailable.monitor).toContain(text)
    expect(unavailable.monitor).toContain('见后端日志')
    expect(unavailable.hint).toContain('见后端日志')
    const detail = display({ [flag]: true, [message]: '业务服务未启动' })
    expect(detail.monitor).toContain('业务服务未启动')
    expect(detail.hint).toContain('业务服务未启动')
  })

  it('keeps a stopped process in standby and bounds a verbose start failure', () => {
    const result = display({ running: false, phone_agent_last_start_error: 'x'.repeat(220) })
    expect(result.stage).toContain('待命 · 未运行')
    expect(result.stage.length).toBeLessThan(100)
    expect(result.monitor).toContain('phone-agent 未运行')
    expect(result.monitor).toContain('…')
    expect(result.hint).toContain('启动失败原因')
    expect(display({ running: false }).stage).toBe('待命 · phone-agent 未运行')
  })

  it('shows an unavailable window monitor as unavailable rather than call readiness', () => {
    const result = display({ running: true, window_monitor_available: false, phone_pywin32_installed: false })
    expect(result.hint).toContain('窗口监控不可用')
    expect(result.monitor).toContain('未检测到 pywin32')
    expect(result.stage).toBe('运行中 · 窗口监控不可用')
    expect(result.steps[2].status).toBe('active')
    expect(result.steps[5].status).toBe('pending')
  })

  it.each(['phone_in_call_ui_visible', 'phone_wechat_call_session_active', 'phone_agent_voice_session_active'] as const)('recognizes an established call from %s without inventing an automatic click', (signal) => {
    const result = display({ running: true, window_monitor_available: true, [signal]: true })
    expect(result.stage).toBe('运行中 · 通话中（等待对方语音/ASR）')
    expect(result.hint).toContain('当前处于通话阶段')
    expect(result.monitor).toContain('无自动点击记录')
    expect(result.steps[4].status).toBe('done')
  })

  it('keeps an idle ready chain waiting for a call and lists only available components', () => {
    const result = display({ running: true, window_monitor_available: true, audio_capture_available: true, asr_available: true, intent_handler_available: true, tts_available: true, vb_cable_available: true })
    expect(result.hint).toContain('音频采集、ASR、意图、TTS、VB-Cable')
    expect(result.stage).toBe('运行中 · 等待来电并尝试自动接听')
    expect(result.steps[3].status).toBe('active')
    expect(result.steps[4].status).toBe('pending')
    expect(display({ running: true, window_monitor_available: true }).hint).toContain('语音链路组件状态未知')
  })

  it.each([
    ['wasapi_loopback', 'WASAPI扬声器回环'], ['pyaudio', 'PyAudio·输入'], ['none', '未就绪(none)'],
  ])('reports the actual %s capture backend and finite audio thresholds', (backend, expected) => {
    const result = display({ running: true, phone_capture_backend: backend, phone_capture_peak_rms_since_last_poll: 121.6, phone_asr_rms_speech_hi: 100.2, phone_asr_rms_silence_lo: 80.7,
      phone_whisper_model: ' tiny ', phone_whisper_backend: 'cpu', lastPolledAt: 1 })
    expect(result.monitor).toContain(expected)
    expect(result.monitor).toContain('RMS峰值≈122')
    expect(result.monitor).toContain('语音段阈值≥100')
    expect(result.monitor).toContain('句末静音<81')
    expect(result.monitor).toContain('Whisper=tiny(cpu)')
    expect(result.monitor).toContain('上次同步')
  })

  it('reports a dead capture thread and legacy RMS thresholds without hiding the failure', () => {
    const result = display({ running: true, phone_capture_thread_alive: false, phone_capture_peak_rms_since_last_poll: 0, phone_asr_rms_silence_threshold: 110, phone_whisper_model: 'base' })
    expect(result.monitor).toContain('线程已退出')
    expect(result.monitor).toContain('RMS峰值≈0')
    expect(result.monitor).toContain('语音段阈值≥110')
    expect(result.monitor).toContain('句末静音<95')
    expect(result.monitor).toContain('Whisper=base')
  })

  it.each([true, false])('reports a real automatic answer attempt ok=%s with its coordinates and error', (ok) => {
    const result = display({ running: true, window_monitor_available: true, last_popup_detected_at_ms: 1, last_popup_source: 'wechat', last_popup_title: '验收  来电',
      last_click_at_ms: 2, last_click_ok: ok, last_click_method: 'fallback_geometry', last_click_x: 10, last_click_y: 20, last_click_error: ok ? '' : 'no_hwnd' })
    expect(result.monitor).toContain('已识别')
    expect(result.monitor).toContain('坐标(10,20)')
    expect(result.monitor).toContain(ok ? '点击接听：已执行' : '点击接听：失败')
    expect(result.steps[4].status).toBe(ok ? 'done' : 'active')
    if (!ok) expect(result.monitor).toContain('未取到来电窗口句柄')
  })

  it.each([true, false])('shows the acknowledged opening playback result ok=%s', (ok) => {
    const result = display({ running: true, last_opening_at_ms: 3, last_opening_ok: ok, last_opening_error: 'test playback unavailable' })
    expect(result.monitor).toContain(ok ? '开场白：已播到 VB' : '开场白：失败')
    expect(result.steps[4].status).toBe('done')
  })

  it('keeps ASR evidence and a failed reply distinct and truncates verbose diagnostic text', () => {
    const result = display({ running: true, window_monitor_available: true, last_asr_at_ms: 4, last_asr_text: '客户订单'.repeat(30), last_pipeline_error: '模型不可用',
      phone_capture_problem_zh: 'p'.repeat(250), phone_window_monitor_hint_zh: 'h'.repeat(370) })
    expect(result.stage).toBe('运行中 · 已收对方语音(ASR)')
    expect(result.monitor).toContain('回复→VB：失败')
    expect(result.monitor).toContain('模型不可用')
    expect(result.monitor).toContain('客户订单')
    expect(result.monitor).toContain('…')
    expect(result.steps[5].status).toBe('done')
  })

  it('shows reply and call-end receipts, including an empty acknowledged reply', () => {
    const result = display({ running: true, last_reply_at_ms: 5, last_reply_text: '', last_pipeline_error: 'TTS unavailable', last_call_ended_at_ms: 6, last_call_end_reason: 'remote_hangup' })
    expect(result.monitor).toContain('「（空）」')
    expect(result.monitor).toContain('TTS unavailable')
    expect(result.monitor).toContain('通话结束')
    const long = display({ last_reply_at_ms: 5, last_reply_text: '回复'.repeat(50) })
    expect(long.monitor).toContain('…')
  })

  it.each([{ mp3_decode_available: false }, { ffmpeg_on_path: false }])('explains unavailable playback dependencies', (flags) => {
    const result = display({ ...flags, vb_cable_playback_device_name: '测试播放设备', vb_cable_stream_sample_hz: 48000 })
    expect(result.monitor).toContain('测试播放设备')
    expect(result.monitor).toContain('48000 Hz')
    expect(result.monitor).toContain('MP3 解码依赖未就绪')
  })

  it.each([
    [undefined, '待命 · 同步状态中', '正在连接'],
    [{ running: false }, '待命 · ADB 链路未运行', '请在一键托管启用'],
    [{ running: false, adb_last_error: '设备离线' }, '待命 · ADB 链路未运行', '设备离线'],
    [{ running: true }, '异常 · adb 不可用', '未检测到 adb'],
    [{ running: true, adb_available: true }, '运行中 · 等待设备在线', '未发现在线设备'],
    [{ running: true, adb_available: true, adb_device_connected: true, adb_call_state: 'RINGING' }, '运行中 · 来电振铃（自动接听）', '检测到来电振铃'],
    [{ running: true, adb_available: true, adb_device_connected: true, adb_call_state: 'OFFHOOK' }, '运行中 · 通话中', '通话中'],
    [{ running: true, adb_available: true, adb_device_connected: true }, '运行中 · 设备在线等待来电', '等待来电'],
  ] as Array<[PhoneAgentStatusPayload | undefined, string, string]>)('presents the actual device connection state: %s', (status, stage, hint) => {
    const result = display(status, 'adb')
    expect(result.stage).toBe(stage)
    expect(result.hint).toContain(hint)
    expect(result.steps).toHaveLength(6)
    expect(result.monitor).toContain('真实电话业务员')
  })

  it('shows an acknowledged device answer and subsequent call-state synchronization', () => {
    const result = display({ running: true, adb_available: true, adb_device_connected: true, adb_device_serial: 'test-device', adb_call_state: 'OFFHOOK', adb_last_answer_at_ms: 1, adb_last_answer_ok: true, adb_last_poll_at_ms: 2 }, 'adb')
    expect(result.steps[1].label).toContain('test-device')
    expect(result.steps.slice(1).map((step) => step.status)).toEqual(['done', 'done', 'done', 'done', 'active'])
    expect(result.monitor).toContain('状态回写已同步')
    expect(display({ fetchError: 'offline' }, 'adb').hint).toBe('状态接口异常：offline')
  })
})
