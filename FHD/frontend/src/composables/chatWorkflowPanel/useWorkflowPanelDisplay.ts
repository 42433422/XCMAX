/**
 * useChatWorkflowPanel 拆分：工作流面板展示构建（监控行 / 步骤行 / 当前提示 / 阶段行）。
 */
import {
  findWorkflowEmployeeEntry,
  resolvePhoneAgentApiBase,
  resolvePhoneChannelForEmployee,
} from '@/utils/modWorkflowEmployees'
import { isCoreWorkflowEmployeeId } from '@/constants/coreWorkflowMod'
import {
  buildCoreWorkflowMonitorLine,
  buildCoreWorkflowStepsForEmployee,
  computeCoreWorkflowCurrentHint,
  computeCoreWorkflowStageLine,
  type WorkflowMonitorPayload,
  type WorkflowStepRow,
} from '@/workflow/coreWorkflowMonitor'
import { formatWorkflowClock } from '@/workflow/coreWorkflowPrefs'
import type { useModsStore } from '@/stores/mods'
import {
  formatCallEndReason,
  formatOpeningError,
  formatPhoneClickError,
  formatPhoneClickMethod,
  formatPhonePipelineError,
  type PhoneAgentStatusPayload,
} from './phoneAgentStatus'

export interface WorkflowPanelDisplayDeps {
  getModsForUi: () => ReturnType<typeof useModsStore>['modsForUi']
}

export function useWorkflowPanelDisplay(deps: WorkflowPanelDisplayDeps) {
  const resolvePhoneChannelByEmployee = (empId: string): 'wechat' | 'adb' =>
    resolvePhoneChannelForEmployee(deps.getModsForUi(), empId)

  /** 与 manifest 对齐；原版模式或未加载 Mod 时返回空字符串，禁止隐式请求 /api/mod/* */
  const getPhoneAgentApiBase = (empId: string): string => {
    const e = findWorkflowEmployeeEntry(deps.getModsForUi(), empId)
    if (e) {
      const b = resolvePhoneAgentApiBase(e, e.modId)
      if (b) return b
    }
    return ''
  }

  function buildWorkflowMonitorLine(
    empId: string,
    steps: WorkflowStepRow[],
    monitor?: WorkflowMonitorPayload,
    lastWechat?: { at: number; line: string },
    lastLabelPrint?: { at: number; line: string },
    lastShipmentAudit?: { at: number; line: string; detail?: string },
    lastReceiptFeedback?: { at: number; line: string; detail?: string },
    phoneStatus?: PhoneAgentStatusPayload,
  ): string {
    if (isCoreWorkflowEmployeeId(empId)) {
      return buildCoreWorkflowMonitorLine(empId, monitor, {
        lastWechat,
        lastLabelPrint,
        lastShipmentAudit,
        lastReceiptFeedback,
      })
    }
    if (resolvePhoneChannelByEmployee(empId) === 'wechat') {
      const ps = phoneStatus
      const phoneBase = getPhoneAgentApiBase(empId).replace(/\/+$/, '')
      if (!ps) {
        if (!phoneBase) {
          return '当前为原版模式（已关闭 Mod 界面）：不包含微信电话扩展。'
        }
        return '电话状态同步中…'
      }
      if (ps.fetchError) {
        if (!phoneBase) {
          return `无法拉取 phone-agent：${ps.fetchError}`
        }
        return `无法拉取电话状态：${ps.fetchError}`
      }
      if (ps.phone_agent_get_status_failed) {
        return `phone-agent 状态异常（get_status）：${ps.phone_agent_get_status_message || '见后端日志'}`
      }
      if (ps.phone_agent_status_route_failed) {
        return `phone-agent 状态接口异常：${ps.phone_agent_status_route_message || '见后端日志'}`
      }
      if (ps.phone_agent_manager_load_failed) {
        return `phone-agent 管理器未加载：${ps.phone_agent_manager_load_message || '见后端日志（import_mod_backend_py services）'}`
      }
      const t = ps.lastPolledAt ? formatWorkflowClock(ps.lastPolledAt) : ''
      const run = ps.running
        ? 'phone-agent 运行中'
        : (() => {
            const err = String(ps.phone_agent_last_start_error || '').trim()
            if (err) {
              const short = err.length > 100 ? `${err.slice(0, 100)}…` : err
              return `phone-agent 未运行（${short}）`
            }
            return 'phone-agent 未运行'
          })()
      const wm = ps.window_monitor_available
        ? '窗口监控可用'
        : ps.phone_pywin32_installed === false
          ? '窗口监控不可用（未检测到 pywin32）'
          : '窗口监控不可用'
      const cap =
        ps.phone_capture_thread_alive === false && ps.running
          ? '采音=线程已退出（请重启电话业务员）'
          : ps.phone_capture_backend === 'wasapi_loopback'
            ? '采音=WASAPI扬声器回环'
            : ps.phone_capture_backend === 'pyaudio'
              ? '采音=PyAudio·输入'
              : ps.phone_capture_backend === 'none'
                ? '采音=未就绪(none)'
                : ''
      const tail = t ? ` · 上次同步 ${t}` : ''
      const wmModel =
        ps.phone_whisper_model && String(ps.phone_whisper_model).trim()
          ? ` · Whisper=${String(ps.phone_whisper_model).trim()}${ps.phone_whisper_backend ? `(${ps.phone_whisper_backend})` : ''}`
          : ''
      const head = `${run} · ${wm}${cap ? ` · ${cap}` : ''}${wmModel}${tail}`
      const speechHi =
        typeof ps.phone_asr_rms_speech_hi === 'number'
          ? ps.phone_asr_rms_speech_hi
          : typeof ps.phone_asr_rms_silence_threshold === 'number'
            ? ps.phone_asr_rms_silence_threshold
            : null
      const silenceLoRaw = typeof ps.phone_asr_rms_silence_lo === 'number' ? ps.phone_asr_rms_silence_lo : null
      const peak = typeof ps.phone_capture_peak_rms_since_last_poll === 'number' ? ps.phone_capture_peak_rms_since_last_poll : null
      const silenceLo = silenceLoRaw != null ? silenceLoRaw : 95
      const diagLine =
        peak != null && speechHi != null
          ? `采音诊断：RMS峰值≈${Math.round(peak)} · 语音段阈值≥${Math.round(speechHi)} · 句末静音<${Math.round(
              silenceLo,
            )}（峰值是轮询窗内最大块；分段用双阈值：对端小声需块 RMS 常≥语音阈值才会送 ASR；环境吵可调高两阈值）`
          : ''
      const titleShort = String(ps.last_popup_title || '')
        .replace(/\s+/g, ' ')
        .slice(0, 36)
      const inCallSig =
        ps.phone_in_call_ui_visible === true || ps.phone_wechat_call_session_active === true || ps.phone_agent_voice_session_active === true
      const step1 = ps.last_popup_detected_at_ms
        ? `① 识别弹窗：已识别 · ${formatWorkflowClock(ps.last_popup_detected_at_ms)} · ${ps.last_popup_source || '—'}${titleShort ? ` · ${titleShort}` : ''}`
        : inCallSig
          ? '① 识别弹窗：无弹窗时间戳，但当前可见通话界面或会话（常见于手动接听）'
          : '① 识别弹窗：尚未识别（来电时此处应出现时间；若一直没有请看后端日志）'
      let step2 = '② 点击接听：尚未执行'
      if (ps.last_click_at_ms != null && ps.last_click_at_ms !== undefined) {
        const ok = ps.last_click_ok === true
        const m = formatPhoneClickMethod(ps.last_click_method)
        const xy = ps.last_click_x != null && ps.last_click_y != null ? ` · 坐标(${ps.last_click_x},${ps.last_click_y})` : ''
        const errRaw = formatPhoneClickError(ps.last_click_error)
        const err = errRaw ? ` · ${errRaw.slice(0, 120)}` : ''
        step2 = `② 点击接听：${ok ? '已执行' : '失败'} · ${formatWorkflowClock(ps.last_click_at_ms)} · ${m}${xy}${err}`
      } else if (inCallSig) {
        step2 = '② 点击接听：无自动点击记录，但已判定通话中（可能手动接听或未上报点击）'
      }
      const playDev = (ps.vb_cable_playback_device_name || '').trim() || 'CABLE Input'
      const hz =
        typeof ps.vb_cable_stream_sample_hz === 'number' && ps.vb_cable_stream_sample_hz > 0 ? `${ps.vb_cable_stream_sample_hz} Hz` : '—'
      const noMp3 = ps.mp3_decode_available === false || (ps.mp3_decode_available === undefined && ps.ffmpeg_on_path === false)
      const ff = noMp3 ? ' · MP3 解码依赖未就绪（pip install miniaudio）' : ''
      let step3 = `③ 对方听合成音：微信麦克风须选「CABLE Output」。TTS 写入「${playDev}」@ ${hz}${ff}`
      if (ps.last_opening_at_ms != null && ps.last_opening_at_ms !== undefined) {
        const oOk = ps.last_opening_ok === true
        step3 = `③ 开场白：${oOk ? '已播到 VB' : '失败'} · ${formatWorkflowClock(ps.last_opening_at_ms)}${
          !oOk ? ` · ${formatOpeningError(ps.last_opening_error).slice(0, 120)}` : ''
        } · 若仍无声请检查微信麦克风是否为 CABLE Output`
      }
      const cap5 =
        ps.phone_capture_backend === 'wasapi_loopback'
          ? '采音=WASAPI扬声器回环'
          : ps.phone_capture_backend === 'pyaudio'
            ? '采音=PyAudio·输入'
            : '采音方式见上方'
      const pyaudioRemoteHint =
        ps.phone_capture_backend === 'pyaudio'
          ? ' · PyAudio 时：对端须从扬声器放出并被「立体声混音」或正确设备采到；或装 pywin32 后重启以恢复 WASAPI 回环（见状态里「谁进 ASR」）'
          : ''
      let step5 = `⑤ 对方语音→ASR：尚无识别结果（${cap5}；对端说话且 Whisper 出字后此处显示时间与文字。无字请对照：采音诊断、XCAGI_PHONE_RMS_SPEECH/SILENCE_LO、后端「句末静音送 ASR」与 Whisper 日志）${pyaudioRemoteHint}`
      if (ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined) {
        const raw = String(ps.last_asr_text || '')
          .replace(/\s+/g, ' ')
          .trim()
        const slice = raw.slice(0, 80)
        step5 = `⑤ 对方语音(ASR)：${formatWorkflowClock(ps.last_asr_at_ms)} · 「${slice}${raw.length > 80 ? '…' : ''}」`
      }
      let step6 = '⑥ 回复→VB：尚无（需先有 ASR 并完成意图与 TTS）'
      if (ps.last_reply_at_ms != null && ps.last_reply_at_ms !== undefined) {
        const raw = String(ps.last_reply_text || '')
          .replace(/\s+/g, ' ')
          .trim()
        const slice = raw.length ? raw.slice(0, 80) : '（空）'
        const pe = (ps.last_pipeline_error || '').trim()
        const peShow = pe ? ` · ${formatPhonePipelineError(pe).slice(0, 72)}` : ''
        step6 = `⑥ 回复→VB：${formatWorkflowClock(ps.last_reply_at_ms)} · 「${slice}${raw.length > 80 ? '…' : ''}」${peShow}`
      } else if ((ps.last_pipeline_error || '').trim() && ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined) {
        const pe = formatPhonePipelineError(ps.last_pipeline_error).slice(0, 120)
        step6 = `⑥ 回复→VB：失败 · ${pe}`
      }
      const step4 =
        ps.last_call_ended_at_ms != null && ps.last_call_ended_at_ms !== undefined
          ? `④ 通话结束：${formatWorkflowClock(ps.last_call_ended_at_ms)} · ${formatCallEndReason(
              ps.last_call_end_reason,
            )} · ①②③⑤⑥ 已初始化`
          : ''
      const problemZh = String(ps.phone_capture_problem_zh || '').trim()
      const problemLine = problemZh.length > 0 ? problemZh.slice(0, 240) + (problemZh.length > 240 ? '…' : '') : ''
      const wmHint = String(ps.phone_window_monitor_hint_zh || '').trim()
      const wmHintLine = wmHint.length > 0 ? wmHint.slice(0, 360) + (wmHint.length > 360 ? '…' : '') : ''
      const detailLines = [wmHintLine, diagLine, problemLine, step1, step2, step3, step5, step6, step4].filter(Boolean)
      if (import.meta.env.DEV) {
        return [head, ...detailLines].join('\n')
      }
      const asrShort =
        ps.last_asr_at_ms != null
          ? `ASR：${String(ps.last_asr_text || '')
              .replace(/\s+/g, ' ')
              .trim()
              .slice(0, 24)}`
          : ''
      return [head, asrShort].filter(Boolean).join(' · ')
    }
    if (resolvePhoneChannelByEmployee(empId) === 'adb') {
      const a = steps.find((s) => s.status === 'active')
      if (a) return `真实电话业务员运行中：${a.label.replace(/^[①②③④⑤⑥]\s*/, '')}`
      const d = steps.filter((s) => s.status === 'done').length
      return `真实电话业务员已启用：完成 ${d}/${steps.length} 步，等待来电触发下一阶段。`
    }
    const a = steps.find((s) => s.status === 'active')
    if (a) return `运行中：${a.label.replace(/^[①②③④⑤]\s*/, '')}`
    return '待命：等待对话或条件触发下一步。'
  }

  function buildWorkflowStepsForEmployee(
    empId: string,
    ctx?: {
      lastWechat?: { at: number; line: string }
      lastLabelPrint?: { at: number; line: string }
      lastShipmentAudit?: { at: number; line: string; detail?: string }
      lastReceiptFeedback?: { at: number; line: string; detail?: string }
      phoneStatus?: PhoneAgentStatusPayload
    },
  ): WorkflowStepRow[] {
    if (isCoreWorkflowEmployeeId(empId)) {
      return buildCoreWorkflowStepsForEmployee(empId, ctx)
    }
    if (resolvePhoneChannelByEmployee(empId) === 'wechat') {
      const ps = ctx?.phoneStatus
      const run = !!ps?.running
      const wm = !!ps?.window_monitor_available
      const popupDone = !!(ps as PhoneAgentStatusPayload | undefined)?.last_popup_detected_at_ms
      const inCallUi = (ps as PhoneAgentStatusPayload | undefined)?.phone_in_call_ui_visible === true
      const sessionActive =
        (ps as PhoneAgentStatusPayload | undefined)?.phone_wechat_call_session_active === true ||
        (ps as PhoneAgentStatusPayload | undefined)?.phone_agent_voice_session_active === true
      const clickTried =
        ps != null &&
        (ps as PhoneAgentStatusPayload).last_click_at_ms != null &&
        (ps as PhoneAgentStatusPayload).last_click_at_ms !== undefined
      const clickOk = (ps as PhoneAgentStatusPayload | undefined)?.last_click_ok === true
      const hasAsr = ps != null && ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined
      const hasOpening = ps != null && ps.last_opening_at_ms != null && ps.last_opening_at_ms !== undefined
      const answered = clickOk || inCallUi || hasAsr || sessionActive || hasOpening
      const popupOrCallUi = popupDone || inCallUi
      const pipelineReady = !!(
        ps?.audio_capture_available &&
        ps?.asr_available &&
        ps?.intent_handler_available &&
        ps?.tts_available &&
        ps?.vb_cable_available
      )
      return [
        { id: 'wp1', label: '① 副窗「一键托管」启用「微信电话对接业务员」', status: 'done' },
        {
          id: 'wp2',
          label: '② 后端 phone-agent 已启动',
          status: !ps ? 'pending' : run ? 'done' : 'active',
        },
        {
          id: 'wp3',
          label: '③ Win32 窗口监控可用（检测来电）',
          status: !ps ? 'pending' : run ? (wm ? 'done' : 'active') : 'pending',
        },
        {
          id: 'wp4',
          label: popupDone
            ? `④ 已识别来电弹窗（${(ps as PhoneAgentStatusPayload).last_popup_source || '—'}）`
            : inCallUi
              ? '④ 已检测到微信通话界面（手动接听或未记录来电弹窗时亦可识别）'
              : '④ 等待识别微信来电弹窗…',
          status: !ps ? 'pending' : popupOrCallUi ? 'done' : run && wm ? 'active' : 'pending',
        },
        {
          id: 'wp5',
          label: clickTried
            ? `⑤ 接听点击：${clickOk ? '已成功' : '已失败'}（${(ps as PhoneAgentStatusPayload).last_click_method || '—'}）`
            : answered
              ? '⑤ 通话已接通（自动未点接听或手动接听）'
              : '⑤ 等待执行接听点击…',
          status: !ps ? 'pending' : clickOk || answered ? 'done' : clickTried && !clickOk ? 'active' : popupOrCallUi ? 'active' : 'pending',
        },
        {
          id: 'wp6',
          label:
            ps?.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined
              ? `⑥ 音频→ASR→回复：已识别「${String(ps.last_asr_text || '')
                  .replace(/\s+/g, ' ')
                  .trim()
                  .slice(0, 36)}${String(ps.last_asr_text || '').length > 36 ? '…' : ''}」`
              : '⑥ 音频采集 → ASR → 意图 → TTS → VB-Cable',
          status: !ps || !run || !wm ? 'pending' : hasAsr ? 'done' : pipelineReady ? 'active' : 'active',
        },
      ]
    }
    if (resolvePhoneChannelByEmployee(empId) === 'adb') {
      const ps = ctx?.phoneStatus
      const run = !!ps?.running
      const adbOk = ps?.adb_available === true
      const devOk = ps?.adb_device_connected === true
      const callState = String(ps?.adb_call_state || 'UNKNOWN').toUpperCase()
      const answerTried = ps?.adb_last_answer_at_ms != null && ps?.adb_last_answer_at_ms !== undefined
      const answerOk = ps?.adb_last_answer_ok === true
      return [
        { id: 'rp1', label: '① 副窗启用「真实电话业务员」', status: 'done' },
        {
          id: 'rp2',
          label: devOk
            ? `② ADB 设备连通检查：已连接（${ps?.adb_device_serial || 'unknown'}）`
            : adbOk
              ? '② ADB 设备连通检查：已发现 adb，等待在线设备'
              : '② ADB 设备连通检查：等待 adb 可用',
          status: !ps ? 'pending' : devOk ? 'done' : run ? 'active' : 'active',
        },
        {
          id: 'rp3',
          label:
            callState === 'RINGING'
              ? '③ 来电状态：振铃中，准备自动接听'
              : callState === 'OFFHOOK'
                ? '③ 来电状态：已进入通话'
                : '③ 来电状态轮询中（等待振铃）',
          status: !ps || !run ? 'pending' : callState === 'OFFHOOK' ? 'done' : devOk ? 'active' : 'pending',
        },
        {
          id: 'rp4',
          label: answerTried ? `④ 自动接听：${answerOk ? '已执行成功' : '执行失败'}` : '④ 自动接听指令（振铃时触发）',
          status: !ps || !run ? 'pending' : answerOk ? 'done' : callState === 'RINGING' ? 'active' : 'pending',
        },
        {
          id: 'rp5',
          label: callState === 'OFFHOOK' ? '⑤ 通话已接通（保持状态监控）' : '⑤ 等待接通',
          status: !ps || !run ? 'pending' : callState === 'OFFHOOK' ? 'done' : 'pending',
        },
        {
          id: 'rp6',
          label:
            ps?.adb_last_poll_at_ms != null && ps.adb_last_poll_at_ms !== undefined
              ? `⑥ 状态回写已同步（${formatWorkflowClock(ps.adb_last_poll_at_ms)}）`
              : '⑥ 状态回写到任务面板',
          status: !ps || !run ? 'pending' : ps?.adb_last_poll_at_ms ? 'active' : 'pending',
        },
      ]
    }
    return []
  }

  function computeWorkflowCurrentHint(
    empId: string,
    steps: WorkflowStepRow[],
    lastWechat?: { at: number; line: string },
    monitor?: WorkflowMonitorPayload,
    lastLabelPrint?: { at: number; line: string },
    lastShipmentAudit?: { at: number; line: string; detail?: string },
    lastReceiptFeedback?: { at: number; line: string; detail?: string },
    phoneStatus?: PhoneAgentStatusPayload,
  ): string {
    if (isCoreWorkflowEmployeeId(empId)) {
      return computeCoreWorkflowCurrentHint(
        empId,
        {
          lastWechat,
          lastLabelPrint,
          lastShipmentAudit,
          lastReceiptFeedback,
        },
        monitor,
      )
    }
    if (resolvePhoneChannelByEmployee(empId) === 'wechat') {
      const ps = phoneStatus
      const phoneBase = getPhoneAgentApiBase(empId).replace(/\/+$/, '')
      if (!ps) {
        if (!phoneBase) {
          return '原版模式：未加载 Mod 电话扩展。'
        }
        return `正在连接后端状态；请确认 Mod 已加载且本机可访问 ${phoneBase}/status。`
      }
      if (ps.fetchError) {
        return `状态接口异常：${ps.fetchError}`
      }
      if (ps.phone_agent_get_status_failed) {
        return `get_status 失败：${ps.phone_agent_get_status_message || '见后端日志'}`
      }
      if (ps.phone_agent_status_route_failed) {
        return `路由异常：${ps.phone_agent_status_route_message || '见后端日志'}`
      }
      if (ps.phone_agent_manager_load_failed) {
        return `phone-agent 管理器未加载：${ps.phone_agent_manager_load_message || '见后端日志'}`
      }
      if (!ps.running) {
        const err = String(ps.phone_agent_last_start_error || '').trim()
        const tail = err ? ` 启动失败原因：${err.length > 200 ? `${err.slice(0, 200)}…` : err}` : ''
        return `phone-agent 未处于运行状态：请在一键托管中打开「微信电话对接业务员」，并检查运行后端的 Python 是否已安装 soundcard / 音频设备（详见后端日志）。${tail}`
      }
      if (!ps.window_monitor_available) {
        return '窗口监控不可用：请确认在 Windows 上运行且已安装 pywin32。'
      }
      const bits: string[] = []
      if (ps.audio_capture_available) bits.push('音频采集')
      if (ps.asr_available) bits.push('ASR')
      if (ps.intent_handler_available) bits.push('意图')
      if (ps.tts_available) bits.push('TTS')
      if (ps.vb_cable_available) bits.push('VB-Cable')
      const chain = bits.length ? `链路组件：${bits.join('、')}` : '语音链路组件状态未知'
      const inCall =
        ps.phone_in_call_ui_visible === true || ps.phone_wechat_call_session_active === true || ps.phone_agent_voice_session_active === true
      if (inCall) {
        return `当前处于通话阶段；${chain}。对方说话后将更新 ASR；若长期无文本请检查扬声器回环与 RMS 阈值（见状态里的采音说明）。`
      }
      return `来电时将尝试自动接听；${chain}。若无法接听，请更新微信 PC 版或查看后端接听按钮定位日志。`
    }
    if (resolvePhoneChannelByEmployee(empId) === 'adb') {
      const ps = phoneStatus
      if (!ps) return '正在连接 ADB 电话状态接口…'
      if (ps.fetchError) return `状态接口异常：${ps.fetchError}`
      if (!ps.running) {
        const err = String(ps.phone_agent_last_start_error || ps.adb_last_error || '').trim()
        return err ? `ADB 链路未运行：${err}` : 'ADB 链路未运行：请在一键托管启用真实电话业务员。'
      }
      if (!ps.adb_available) return '未检测到 adb，请确认 adb 已安装并在 PATH。'
      if (!ps.adb_device_connected) return 'adb 已可用，但未发现在线设备（请检查 USB 调试与授权）。'
      const st = String(ps.adb_call_state || 'UNKNOWN').toUpperCase()
      if (st === 'RINGING') return '检测到来电振铃，正在尝试自动接听。'
      if (st === 'OFFHOOK') return '通话中：ADB 状态轮询正常。'
      return '设备在线，等待来电（轮询中）。'
    }
    const active = steps.find((s) => s.status === 'active')
    if (active) return `当前步骤：${active.label.replace(/^[①②③④⑤]\s*/, '')}`
    return '工作流已启用，等待下一步触发。'
  }

  function computeWorkflowStageLine(
    empId: string,
    lastWechat?: { at: number; line: string },
    lastLabelPrint?: { at: number; line: string },
    lastShipmentAudit?: { at: number; line: string; detail?: string },
    lastReceiptFeedback?: { at: number; line: string; detail?: string },
    phoneStatus?: PhoneAgentStatusPayload,
  ): string {
    if (isCoreWorkflowEmployeeId(empId)) {
      return computeCoreWorkflowStageLine(empId, {
        lastWechat,
        lastLabelPrint,
        lastShipmentAudit,
        lastReceiptFeedback,
      })
    }
    if (resolvePhoneChannelByEmployee(empId) === 'wechat') {
      const ps = phoneStatus
      if (!ps) return '待命 · 同步状态中'
      if (!ps.running) {
        const err = String(ps.phone_agent_last_start_error || '').trim()
        if (err) {
          const short = err.length > 72 ? `${err.slice(0, 72)}…` : err
          return `待命 · 未运行（${short}）`
        }
        return '待命 · phone-agent 未运行'
      }
      if (ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined) {
        return '运行中 · 已收对方语音(ASR)'
      }
      if (
        ps.phone_in_call_ui_visible === true ||
        ps.phone_wechat_call_session_active === true ||
        ps.phone_agent_voice_session_active === true
      ) {
        return '运行中 · 通话中（等待对方语音/ASR）'
      }
      return ps.window_monitor_available ? '运行中 · 等待来电并尝试自动接听' : '运行中 · 窗口监控不可用'
    }
    if (resolvePhoneChannelByEmployee(empId) === 'adb') {
      const ps = phoneStatus
      if (!ps) return '待命 · 同步状态中'
      if (!ps.running) return '待命 · ADB 链路未运行'
      if (!ps.adb_available) return '异常 · adb 不可用'
      if (!ps.adb_device_connected) return '运行中 · 等待设备在线'
      const st = String(ps.adb_call_state || 'UNKNOWN').toUpperCase()
      if (st === 'RINGING') return '运行中 · 来电振铃（自动接听）'
      if (st === 'OFFHOOK') return '运行中 · 通话中'
      return '运行中 · 设备在线等待来电'
    }
    return '待命 · 等待对话触发'
  }

  return {
    resolvePhoneChannelByEmployee,
    getPhoneAgentApiBase,
    buildWorkflowMonitorLine,
    buildWorkflowStepsForEmployee,
    computeWorkflowCurrentHint,
    computeWorkflowStageLine,
  }
}
