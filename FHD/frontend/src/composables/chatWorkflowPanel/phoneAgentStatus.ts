/**
 * useChatWorkflowPanel 拆分：PhoneAgent 状态类型与纯格式化函数（无状态、无副作用）。
 */

/** 与 GET /api/mod/sz-qsm-pro/phone-agent/status 的 data 对齐，并带 lastPolledAt */
export type PhoneAgentStatusPayload = {
  phone_channel?: 'wechat' | 'adb' | string
  running?: boolean
  window_monitor_available?: boolean
  audio_capture_available?: boolean
  asr_available?: boolean
  intent_handler_available?: boolean
  tts_available?: boolean
  vb_cable_available?: boolean
  /** 本机 TTS 写入的 VB 播放设备名（系统「播放」列表里那路，常见名含 CABLE Input） */
  vb_cable_playback_device_name?: string | null
  /** 当前写入采样率（与解码一致），多为 44100/48000 */
  vb_cable_stream_sample_hz?: number | null
  ffmpeg_on_path?: boolean
  /** ffmpeg 或 miniaudio 至少一种可用即可解码 MP3 */
  mp3_decode_available?: boolean
  /** 后端提示：微信麦克风须选 CABLE Output 对方才能听到合成音 */
  remote_hear_tts_hint?: string
  /** VB：以声音设置为准——CABLE Input 在播放侧、CABLE Output 在录制侧（勿按字面 Input=录制） */
  vb_cable_roles_zh?: string
  lastPolledAt?: number
  /** 后端 window_monitor 上报：识别到微信来电弹窗 */
  last_popup_detected_at_ms?: number
  last_popup_source?: string
  last_popup_title?: string
  last_popup_class_name?: string
  last_popup_hwnd?: number | null
  last_popup_w?: number | null
  last_popup_h?: number | null
  /** 后端上报：自动接听点击 */
  last_click_at_ms?: number | null
  last_click_ok?: boolean | null
  last_click_method?: string | null
  last_click_x?: number | null
  last_click_y?: number | null
  last_click_error?: string | null
  last_opening_at_ms?: number | null
  last_opening_ok?: boolean | null
  last_opening_error?: string | null
  last_call_ended_at_ms?: number | null
  last_call_end_reason?: string | null
  /** 最近一次对方语音 ASR 文本与时间（与 ⑤ 监控行对应） */
  last_asr_text?: string | null
  last_asr_at_ms?: number | null
  last_reply_text?: string | null
  last_reply_at_ms?: number | null
  last_pipeline_error?: string | null
  /** 兼容旧字段：与 phone_asr_rms_speech_hi 相同 */
  phone_asr_rms_silence_threshold?: number
  phone_asr_rms_speech_hi?: number
  phone_asr_rms_silence_lo?: number
  phone_capture_peak_rms_since_last_poll?: number
  phone_input_devices?: Array<{ index: number; name: string }>
  phone_asr_hint?: string
  /** wasapi_loopback | pyaudio | none */
  phone_capture_backend?: string
  /** false 表示采音线程已退出，RMS 会持续≈0 */
  phone_capture_thread_alive?: boolean | null
  /** 后端给出的采音故障说明（若有） */
  phone_capture_problem_zh?: string
  phone_audio_capture_started_ok?: boolean
  /** Whisper 模型名，如 tiny、base */
  phone_whisper_model?: string
  phone_whisper_backend?: string
  phone_whisper_device?: string
  phone_whisper_compute_type?: string
  /** 拉取 /phone-agent/status 失败时的原因（网络、HTTP、后端 message） */
  fetchError?: string
  phone_agent_manager_load_failed?: boolean
  phone_agent_manager_load_message?: string
  /** 后端 get_status() 抛错时由 /status 降级返回 */
  phone_agent_get_status_failed?: boolean
  phone_agent_get_status_message?: string
  phone_agent_status_route_failed?: boolean
  phone_agent_status_route_message?: string
  /** 最近一次 POST /start 失败或 start() 异常原因（便于「未运行」时对照） */
  phone_agent_last_start_error?: string | null
  /** 轮询瞬间是否检测到微信通话中界面（含手动接听） */
  phone_in_call_ui_visible?: boolean
  /** window_monitor 会话：自动接听成功后直至挂断 */
  phone_wechat_call_session_active?: boolean
  /** PhoneAgentManager：接听成功后的语音会话标志（与上项通常同步） */
  phone_agent_voice_session_active?: boolean
  adb_available?: boolean
  adb_device_connected?: boolean
  adb_device_serial?: string | null
  adb_call_state?: string | null
  adb_last_poll_at_ms?: number | null
  adb_last_answer_at_ms?: number | null
  adb_last_answer_ok?: boolean | null
  adb_last_error?: string | null
  /** 后端是否已安装 pywin32（微信来电窗口监控；与 TTS/VB 无关） */
  phone_pywin32_installed?: boolean
  /** 窗口监控不可用时的人读说明（例如缺 pywin32） */
  phone_window_monitor_hint_zh?: string | null
}

/** 是否进入「真实来电/通话」步骤进度（否则仅显示链路待命，不计百分比） */
export function phoneAgentWorkflowProgressShouldStart(ps: PhoneAgentStatusPayload | null | undefined): boolean {
  if (!ps?.running) return false
  if (ps.last_popup_detected_at_ms != null && ps.last_popup_detected_at_ms !== undefined) return true
  if (ps.last_click_at_ms != null && ps.last_click_at_ms !== undefined) return true
  if (ps.last_opening_at_ms != null && ps.last_opening_at_ms !== undefined) return true
  if (ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined) return true
  if (ps.phone_in_call_ui_visible === true) return true
  if (ps.phone_wechat_call_session_active === true) return true
  if (ps.phone_agent_voice_session_active === true) return true
  return false
}

/** 与后端 phone_agent 的 click_attempt.error 对齐，便于任务面板可读 */
export function formatPhoneClickError(code: string | null | undefined): string {
  const c = String(code || '').trim()
  if (!c) return ''
  const map: Record<string, string> = {
    wechat_not_minimized_manual_required: '微信主窗口需最小化或收进托盘后再自动接听',
    wechat_main_visible_manual_required: '微信主窗口需最小化或收进托盘后再自动接听',
    no_hwnd: '未取到来电窗口句柄，无法自动点击',
  }
  return map[c] || c
}

/** click_attempt.method：模板/坐标等方式说明 */
export function formatPhoneClickMethod(method: string | null | undefined): string {
  const m = String(method || '').trim()
  if (!m) return '—'
  const map: Record<string, string> = {
    fallback_geometry: '几何坐标兜底（未命中屏幕模板时）',
  }
  return map[m] || m
}

export function formatOpeningError(code: string | null | undefined): string {
  const c = String(code || '').trim()
  if (!c) return '原因未知，请看后端日志'
  const map: Record<string, string> = {
    vb_play_pcm_decode_failed: 'MP3解码失败：pip install miniaudio（可无 ffmpeg）后重启后端',
    tts_or_vb_unavailable: 'TTS 或 VB-Cable 未就绪',
    tts_synthesize_failed: 'TTS 合成失败',
  }
  return map[c] || c
}

export function formatCallEndReason(reason: string | null | undefined): string {
  const r = String(reason || '').trim()
  const map: Record<string, string> = {
    in_call_ui_gone: '通话界面已消失',
    in_call_ui_never_detected_timeout: '未识别到通话界面（已清空）',
  }
  return map[r] || r || '—'
}

export function formatPhonePipelineError(code: string | null | undefined): string {
  const c = String(code || '').trim()
  if (!c) return ''
  const map: Record<string, string> = {
    tts_vb_play_failed: 'TTS 已合成但 VB 解码/入队失败',
    tts_synthesize_failed: 'TTS 合成失败',
  }
  return map[c] || c
}
