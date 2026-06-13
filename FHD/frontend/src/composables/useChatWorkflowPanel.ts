import { watch, type Ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore, workflowAiEmployeesStorageKey } from '@/stores/workflowAiEmployees'
import {
  buildModWorkflowPanelMeta,
  findWorkflowEmployeeEntry,
  resolvePhoneAgentApiBase,
  listPhoneAgentEmployeeIds,
  resolvePhoneChannelForEmployee,
} from '@/utils/modWorkflowEmployees'
import { isCoreWorkflowEmployeeId, isCoreWorkflowModInstalled } from '@/constants/coreWorkflowMod'
import {
  appendCoreWorkflowSummaryParts,
  buildCoreWorkflowMonitorLine,
  buildCoreWorkflowStepsForEmployee,
  computeCoreWorkflowCurrentHint,
  computeCoreWorkflowProgressState,
  computeCoreWorkflowStageLine,
  computeWorkflowProgressFromSteps,
  mergeCorePayloadFromExisting,
  type WorkflowMonitorPayload,
  type WorkflowStepRow,
} from '@/workflow/coreWorkflowMonitor'
import {
  buildLabelPrintHostUpdate,
  buildReceiptFeedbackHostUpdate,
  buildWechatMonitorUpdate,
  dispatchCoreWorkflowModRun,
  runLabelPrintSideEffect,
} from '@/workflow/coreWorkflowDispatcher'
import { formatWorkflowClock } from '@/workflow/coreWorkflowPrefs'
import type { TaskItem } from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'

export type PhoneAgentStatusPayload = {
  phone_channel?: 'wechat' | 'adb' | string
  running?: boolean
  window_monitor_available?: boolean
  audio_capture_available?: boolean
  asr_available?: boolean
  intent_handler_available?: boolean
  tts_available?: boolean
  vb_cable_available?: boolean
  vb_cable_playback_device_name?: string | null
  vb_cable_stream_sample_hz?: number | null
  ffmpeg_on_path?: boolean
  mp3_decode_available?: boolean
  remote_hear_tts_hint?: string
  vb_cable_roles_zh?: string
  lastPolledAt?: number
  last_popup_detected_at_ms?: number
  last_popup_source?: string
  last_popup_title?: string
  last_popup_class_name?: string
  last_popup_hwnd?: number | null
  last_popup_w?: number | null
  last_popup_h?: number | null
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
  last_asr_text?: string | null
  last_asr_at_ms?: number | null
  last_reply_text?: string | null
  last_reply_at_ms?: number | null
  last_pipeline_error?: string | null
  phone_asr_rms_silence_threshold?: number
  phone_asr_rms_speech_hi?: number
  phone_asr_rms_silence_lo?: number
  phone_capture_peak_rms_since_last_poll?: number
  phone_input_devices?: Array<{ index: number; name: string }>
  phone_asr_hint?: string
  phone_capture_backend?: string
  phone_capture_thread_alive?: boolean | null
  phone_capture_problem_zh?: string
  phone_audio_capture_started_ok?: boolean
  phone_whisper_model?: string
  phone_whisper_backend?: string
  phone_whisper_device?: string
  phone_whisper_compute_type?: string
  fetchError?: string
  phone_agent_manager_load_failed?: boolean
  phone_agent_manager_load_message?: string
  phone_agent_get_status_failed?: boolean
  phone_agent_get_status_message?: string
  phone_agent_status_route_failed?: boolean
  phone_agent_status_route_message?: string
  phone_agent_last_start_error?: string | null
  phone_in_call_ui_visible?: boolean
  phone_wechat_call_session_active?: boolean
  phone_agent_voice_session_active?: boolean
  adb_available?: boolean
  adb_device_connected?: boolean
  adb_device_serial?: string | null
  adb_call_state?: string | null
  adb_last_poll_at_ms?: number | null
  adb_last_answer_at_ms?: number | null
  adb_last_answer_ok?: boolean | null
  adb_last_error?: string | null
  phone_pywin32_installed?: boolean
  phone_window_monitor_hint_zh?: string | null
}

export interface UseChatWorkflowPanelDeps {
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  taskFilter: Ref<'all' | 'running' | 'success' | 'failed'>
  currentTask: Ref<ShipmentTask | null>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  sortTaskList: () => void
  createTaskId: (prefix: string) => string
  persistTaskPanelStateForSession: (targetSessionId?: string) => void
  showTaskConfirm: (task: unknown) => void
  emitAssistantPush: (payload?: Record<string, unknown>) => void
  maybeCloseAssistantFloatForShipmentTask: (task: unknown, autoAction: unknown) => void
}

export function useChatWorkflowPanel(deps: UseChatWorkflowPanelDeps) {
  const modsStore = useModsStore()
  const workflowAiEmployeesStore = useWorkflowAiEmployeesStore()
  const {
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    upsertTask,
    sortTaskList,
    createTaskId,
    persistTaskPanelStateForSession,
    showTaskConfirm,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
  } = deps

  /** 副窗星标轮询 + 微信 AI 员工链路：写入右侧任务列表（仅 API/事件，不模拟点击） */
  function onWechatAiTaskEnqueue(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const msg = String(d.messageText || '').trim()
    const contactId = String(d.contactId ?? '').trim()
    if (!msg && !contactId) return
    const taskId = createTaskId('wechat_ai')
    const name = String(d.contactName || '星标联系人').trim()
    const title = `微信消息处理 · ${name}`
    const lines: string[] = []
    if (msg) lines.push(`最新消息：${msg}`)
    lines.push(`预处理意图：${String(d.intentLabel || '—').trim()}`)
    const idetail = String(d.intentDetail || '').trim()
    if (idetail) lines.push(idetail)
    const pi = String(d.primaryIntent || '').trim()
    if (pi) lines.push(`primary_intent：${pi}`)
    const toolKey = String(d.toolKey || '').trim()
    if (toolKey) lines.push(`tool_key：${toolKey}`)
    upsertTask({
      id: taskId,
      type: 'wechat_intent',
      source: 'wechat',
      title,
      status: 'success',
      progress: 100,
      stage: d.sourceApi === 'intent_test' ? '专业模式·意图 API' : '本地规则预处理',
      summary: lines.join('\n'),
      payload: { ...d }
    })

    const wf = taskList.value.find((t) => t.id === 'workflow_emp_wechat_msg')
    if (wf) {
      const line = `${name}：${msg.replace(/\s+/g, ' ').slice(0, 120)}`
      dispatchCoreWorkflowModRun(isCoreWorkflowModInstalled(modsStore.modsForUi), 'wechat_msg', {
        action: 'enqueue_ack',
        contact: name,
        line,
      })
      upsertWorkflowEmployeeTask('wechat_msg', {
        lastWechat: {
          at: Date.now(),
          line,
        },
      })
    }
  }

  /** 微信星标链路解析出可开单话术时，右侧「当前任务」展示与对话内一致的发货单预览 */
  function onWechatShipmentPreviewTask(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const task = d.task
    if (!task || task.type !== 'shipment_generate') return
    const contact = String(d.contactName || '').trim()
    const hint =
      '\n\n可在左侧对话发送「再加 / 删除第几行 / 改成…」调整明细后再点确认执行。（与智能对话内改预览一致）'
    const baseDesc = String(task.description || '').trim()
    const next = {
      ...task,
      title: contact ? `${task.title}（微信 · ${contact}）` : `${task.title}（微信消息）`,
      description: `${baseDesc}${hint}`,
      payload: {
        ...(task.payload || {}),
        wechat_preview_source: {
          contactName: d.contactName,
          contactId: d.contactId,
          messageText: d.messageText,
        },
      },
    }
    showTaskConfirm(next)
    maybeCloseAssistantFloatForShipmentTask(next, null)
    emitAssistantPush({
      title: '微信发货单预览',
      description: contact
        ? `来自 ${contact}，请在右侧任务面板确认或先对话改明细`
        : '请在右侧任务面板确认或先对话改明细',
    })
  }

  async function onWorkflowLabelPrintSignal(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!enabled.label_print) return
    if (!taskList.value.some((t) => t.id === 'workflow_emp_label_print')) return
    const modInstalled = isCoreWorkflowModInstalled(modsStore.modsForUi)
    dispatchCoreWorkflowModRun(modInstalled, 'label_print', { action: 'signal_ack', ...d })
    upsertWorkflowEmployeeTask('label_print', buildLabelPrintHostUpdate(d))
    await runLabelPrintSideEffect(d)
  }

  /** 星标微信命中收货/对账类意图时，写入收货确认工作流 */
  function onWorkflowReceiptFeedbackSignal(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!enabled.receipt_confirm) return
    if (!taskList.value.some((t) => t.id === 'workflow_emp_receipt_confirm')) return
    const modInstalled = isCoreWorkflowModInstalled(modsStore.modsForUi)
    const host = buildReceiptFeedbackHostUpdate(d)
    dispatchCoreWorkflowModRun(modInstalled, 'receipt_confirm', {
      action: 'feedback_ack',
      line: host.lastReceiptFeedback.line,
      detail: host.lastReceiptFeedback.detail,
    })
    upsertWorkflowEmployeeTask('receipt_confirm', { lastReceiptFeedback: host.lastReceiptFeedback })
    emitAssistantPush({
      title: host.pushTitle,
      description: host.pushDescription,
      feature: 'assistant',
    })
  }

  /** 与副窗「一键托管」员工开关一致：启用后在任务面板展示工作流状态 */

  function resolveWorkflowEmployeePanelMeta(empId: string): { title: string; summary: string } | null {
    const modMap = buildModWorkflowPanelMeta(modsStore.modsForUi)
    return modMap[empId] || null
  }

  /** 关闭 Mod 界面或 manifest 无该员工时，去掉任务面板中已无 meta 的工作流项 */
  function pruneStaleWorkflowEmployeeTasks() {
    for (let i = taskList.value.length - 1; i >= 0; i--) {
      const t = taskList.value[i]
      if (t?.type !== 'workflow_employee') continue
      const id = t.id
      if (typeof id !== 'string' || !id.startsWith('workflow_emp_')) continue
      const empId = id.slice('workflow_emp_'.length)
      if (resolveWorkflowEmployeePanelMeta(empId)) continue
      taskList.value.splice(i, 1)
      if (activeTaskId.value === id) {
        activeTaskId.value = taskList.value[0]?.id || ''
      }
    }
  }

  /** 与 GET /api/mod/sz-qsm-pro/phone-agent/status 的 data 对齐，并带 lastPolledAt */
  type PhoneAgentStatusPayload = {
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
  function phoneAgentWorkflowProgressShouldStart(ps: PhoneAgentStatusPayload | null | undefined): boolean {
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
  function formatPhoneClickError(code: string | null | undefined): string {
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
  function formatPhoneClickMethod(method: string | null | undefined): string {
    const m = String(method || '').trim()
    if (!m) return '—'
    const map: Record<string, string> = {
      fallback_geometry: '几何坐标兜底（未命中屏幕模板时）',
    }
    return map[m] || m
  }

  function formatOpeningError(code: string | null | undefined): string {
    const c = String(code || '').trim()
    if (!c) return '原因未知，请看后端日志'
    const map: Record<string, string> = {
      vb_play_pcm_decode_failed: 'MP3解码失败：pip install miniaudio（可无 ffmpeg）后重启后端',
      tts_or_vb_unavailable: 'TTS 或 VB-Cable 未就绪',
      tts_synthesize_failed: 'TTS 合成失败',
    }
    return map[c] || c
  }

  function formatCallEndReason(reason: string | null | undefined): string {
    const r = String(reason || '').trim()
    const map: Record<string, string> = {
      in_call_ui_gone: '通话界面已消失',
      in_call_ui_never_detected_timeout: '未识别到通话界面（已清空）',
    }
    return map[r] || r || '—'
  }

  function formatPhonePipelineError(code: string | null | undefined): string {
    const c = String(code || '').trim()
    if (!c) return ''
    const map: Record<string, string> = {
      tts_vb_play_failed: 'TTS 已合成但 VB 解码/入队失败',
      tts_synthesize_failed: 'TTS 合成失败',
    }
    return map[c] || c
  }

  const PHONE_AGENT_POLL_MS = 2000
  let phoneAgentPollTimer: number | null = null

  function resolvePhoneChannelByEmployee(empId: string): 'wechat' | 'adb' {
    return resolvePhoneChannelForEmployee(modsStore.modsForUi, empId)
  }

  /** 所有已启用的电话类员工（manifest 含 phone_agent API）；无 manifest 时不算启用 */
  function getEnabledPhoneEmployeeIds(): string[] {
    const enabled = readWorkflowEmployeeEnabledMap()
    const out: string[] = []
    for (const empId of listPhoneAgentEmployeeIds(modsStore.modsForUi)) {
      if (enabled[empId] && resolveWorkflowEmployeePanelMeta(empId)) out.push(empId)
    }
    return out
  }

  /** 与 manifest 对齐；原版模式或未加载 Mod 时返回空字符串，禁止隐式请求 /api/mod/* */
  function getPhoneAgentApiBase(empId: string): string {
    const e = findWorkflowEmployeeEntry(modsStore.modsForUi, empId)
    if (e) {
      const b = resolvePhoneAgentApiBase(e, e.modId)
      if (b) return b
    }
    return ''
  }

  /** 与 TopAssistantFloat 一致：启用微信电话员工时应启动后端 phone-agent。重启 run.py 后 _running 为 false，仅靠 localStorage 开关不会再次 POST /start，故在轮询侧兜底。 */
  async function requestPhoneAgentStart(empId: string): Promise<void> {
    const base = getPhoneAgentApiBase(empId).replace(/\/+$/, '')
    if (!base) return
    const ch = resolvePhoneChannelByEmployee(empId)
    try {
      const resp = await fetch(`${base}/start?channel=${ch}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel: ch }),
      })
      const raw = await resp.text()
      let data: { success?: boolean; message?: string; error?: string } = {}
      try {
        data = raw ? (JSON.parse(raw) as typeof data) : {}
      } catch {
        data = {}
      }
      if (!data.success) {
        const msg =
          (typeof data.message === 'string' && data.message.trim()) ||
          (typeof data.error === 'string' && data.error.trim()) ||
          (resp.ok ? '未知错误' : `HTTP ${resp.status}`)
        const hint = !raw.trim().startsWith('{') ? raw.slice(0, 200) : ''
        console.warn('[奇士美 PRO] phone-agent/start:', msg + (hint ? ` | body: ${hint}` : ''))
      }
    } catch (e) {
      console.warn('[奇士美 PRO] phone-agent/start 请求失败:', e)
    }
  }

  async function fetchPhoneAgentStatusPayload(empId: string): Promise<PhoneAgentStatusPayload> {
    const base = getPhoneAgentApiBase(empId).replace(/\/+$/, '')
    const lastPolledAt = Date.now()
    if (!base) {
      return { lastPolledAt, running: false, fetchError: '当前为原版模式或未加载 Mod，无电话扩展接口' }
    }
    const ch = resolvePhoneChannelByEmployee(empId)
    try {
      const r = await fetch(`${base}/status?channel=${ch}`)
      const j = await r.json().catch(() => ({}))
      if (j?.success && j?.data && typeof j.data === 'object') {
        return { ...j.data, lastPolledAt } as PhoneAgentStatusPayload
      }
      const msg =
        typeof j?.message === 'string' && j.message.trim()
          ? j.message.trim()
          : !r.ok
            ? r.status === 404
              ? `HTTP 404（请确认路径为 ${base}/status，勿使用 /statu 等拼写错误）`
              : `HTTP ${r.status}`
            : '响应缺少 data'
      return { lastPolledAt, running: false, fetchError: msg }
    } catch (e) {
      const err = e instanceof Error ? e.message : String(e)
      return { lastPolledAt, running: false, fetchError: err }
    }
  }

  function stopPhoneAgentStatusPoll() {
    if (phoneAgentPollTimer) {
      window.clearInterval(phoneAgentPollTimer)
      phoneAgentPollTimer = null
    }
  }

  async function pollPhoneAgentStatusForEnabledEmployees(): Promise<void> {
    const ids = getEnabledPhoneEmployeeIds()
    if (ids.length === 0) {
      stopPhoneAgentStatusPoll()
      return
    }
    const enabled = readWorkflowEmployeeEnabledMap()
    for (const empId of ids) {
      if (!enabled[empId]) continue
      await requestPhoneAgentStart(empId)
      let ps = await fetchPhoneAgentStatusPayload(empId)
      if (!ps.fetchError && !ps.running) {
        await requestPhoneAgentStart(empId)
        ps = await fetchPhoneAgentStatusPayload(empId)
      }
      upsertWorkflowEmployeeTask(empId, { phoneStatus: ps })
    }
  }

  function startPhoneAgentStatusPoll() {
    stopPhoneAgentStatusPoll()
    void pollPhoneAgentStatusForEnabledEmployees()
    phoneAgentPollTimer = window.setInterval(() => {
      void pollPhoneAgentStatusForEnabledEmployees()
    }, PHONE_AGENT_POLL_MS)
  }

  function buildWorkflowMonitorLine(
    empId: string,
    steps: WorkflowStepRow[],
    monitor?: WorkflowMonitorPayload,
    lastWechat?: { at: number; line: string },
    lastLabelPrint?: { at: number; line: string },
    lastShipmentAudit?: { at: number; line: string; detail?: string },
    lastReceiptFeedback?: { at: number; line: string; detail?: string },
    phoneStatus?: PhoneAgentStatusPayload
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
          ? ` · Whisper=${String(ps.phone_whisper_model).trim()}${
              ps.phone_whisper_backend ? `(${ps.phone_whisper_backend})` : ''
            }`
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
      const titleShort = String(ps.last_popup_title || '').replace(/\s+/g, ' ').slice(0, 36)
      const inCallSig =
        ps.phone_in_call_ui_visible === true ||
        ps.phone_wechat_call_session_active === true ||
        ps.phone_agent_voice_session_active === true
      const step1 = ps.last_popup_detected_at_ms
        ? `① 识别弹窗：已识别 · ${formatWorkflowClock(ps.last_popup_detected_at_ms)} · ${ps.last_popup_source || '—'}${titleShort ? ` · ${titleShort}` : ''}`
        : inCallSig
          ? '① 识别弹窗：无弹窗时间戳，但当前可见通话界面或会话（常见于手动接听）'
          : '① 识别弹窗：尚未识别（来电时此处应出现时间；若一直没有请看后端日志）'
      let step2 = '② 点击接听：尚未执行'
      if (ps.last_click_at_ms != null && ps.last_click_at_ms !== undefined) {
        const ok = ps.last_click_ok === true
        const m = formatPhoneClickMethod(ps.last_click_method)
        const xy =
          ps.last_click_x != null && ps.last_click_y != null ? ` · 坐标(${ps.last_click_x},${ps.last_click_y})` : ''
        const errRaw = formatPhoneClickError(ps.last_click_error)
        const err = errRaw ? ` · ${errRaw.slice(0, 120)}` : ''
        step2 = `② 点击接听：${ok ? '已执行' : '失败'} · ${formatWorkflowClock(ps.last_click_at_ms)} · ${m}${xy}${err}`
      } else if (inCallSig) {
        step2 = '② 点击接听：无自动点击记录，但已判定通话中（可能手动接听或未上报点击）'
      }
      const playDev = (ps.vb_cable_playback_device_name || '').trim() || 'CABLE Input'
      const hz =
        typeof ps.vb_cable_stream_sample_hz === 'number' && ps.vb_cable_stream_sample_hz > 0
          ? `${ps.vb_cable_stream_sample_hz} Hz`
          : '—'
      const noMp3 =
        ps.mp3_decode_available === false ||
        (ps.mp3_decode_available === undefined && ps.ffmpeg_on_path === false)
      const ff = noMp3 ? ' · MP3 解码依赖未就绪（pip install miniaudio）' : ''
      let step3 = `③ 对方听合成音：微信麦克风须选「CABLE Output」。TTS 写入「${playDev}」@ ${hz}${ff}`
      if (ps.last_opening_at_ms != null && ps.last_opening_at_ms !== undefined) {
        const oOk = ps.last_opening_ok === true
        const oErr = (ps.last_opening_error || '').trim()
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
        const raw = String(ps.last_asr_text || '').replace(/\s+/g, ' ').trim()
        const slice = raw.slice(0, 80)
        step5 = `⑤ 对方语音(ASR)：${formatWorkflowClock(ps.last_asr_at_ms)} · 「${slice}${
          raw.length > 80 ? '…' : ''
        }」`
      }
      let step6 = '⑥ 回复→VB：尚无（需先有 ASR 并完成意图与 TTS）'
      if (ps.last_reply_at_ms != null && ps.last_reply_at_ms !== undefined) {
        const raw = String(ps.last_reply_text || '').replace(/\s+/g, ' ').trim()
        const slice = raw.length ? raw.slice(0, 80) : '（空）'
        const pe = (ps.last_pipeline_error || '').trim()
        const peShow = pe ? ` · ${formatPhonePipelineError(pe).slice(0, 72)}` : ''
        step6 = `⑥ 回复→VB：${formatWorkflowClock(ps.last_reply_at_ms)} · 「${slice}${
          raw.length > 80 ? '…' : ''
        }」${peShow}`
      } else if (
        (ps.last_pipeline_error || '').trim() &&
        ps.last_asr_at_ms != null &&
        ps.last_asr_at_ms !== undefined
      ) {
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
      const problemLine =
        problemZh.length > 0 ? problemZh.slice(0, 240) + (problemZh.length > 240 ? '…' : '') : ''
      const wmHint = String(ps.phone_window_monitor_hint_zh || '').trim()
      const wmHintLine =
        wmHint.length > 0 ? wmHint.slice(0, 360) + (wmHint.length > 360 ? '…' : '') : ''
      const detailLines = [wmHintLine, diagLine, problemLine, step1, step2, step3, step5, step6, step4].filter(
        Boolean,
      )
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
    }
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
        ps != null && (ps as PhoneAgentStatusPayload).last_click_at_ms != null &&
        (ps as PhoneAgentStatusPayload).last_click_at_ms !== undefined
      const clickOk = (ps as PhoneAgentStatusPayload | undefined)?.last_click_ok === true
      const hasAsr =
        ps != null && ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined
      const hasOpening =
        ps != null && ps.last_opening_at_ms != null && ps.last_opening_at_ms !== undefined
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
          status: !ps
            ? 'pending'
            : clickOk || answered
              ? 'done'
              : clickTried && !clickOk
                ? 'active'
                : popupOrCallUi
                  ? 'active'
                  : 'pending',
        },
        {
          id: 'wp6',
          label:
            ps?.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined
              ? `⑥ 音频→ASR→回复：已识别「${String(ps.last_asr_text || '').replace(/\s+/g, ' ').trim().slice(0, 36)}${
                  String(ps.last_asr_text || '').length > 36 ? '…' : ''
                }」`
              : '⑥ 音频采集 → ASR → 意图 → TTS → VB-Cable',
          status: !ps || !run || !wm
            ? 'pending'
            : hasAsr
              ? 'done'
              : pipelineReady
                ? 'active'
                : 'active',
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
          label: answerTried
            ? `④ 自动接听：${answerOk ? '已执行成功' : '执行失败'}`
            : '④ 自动接听指令（振铃时触发）',
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
    phoneStatus?: PhoneAgentStatusPayload
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
        const tail = err
          ? ` 启动失败原因：${err.length > 200 ? `${err.slice(0, 200)}…` : err}`
          : ''
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
        ps.phone_in_call_ui_visible === true ||
        ps.phone_wechat_call_session_active === true ||
        ps.phone_agent_voice_session_active === true
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
    phoneStatus?: PhoneAgentStatusPayload
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

  function readWorkflowEmployeeEnabledMap(): Record<string, boolean> {
    return { ...workflowAiEmployeesStore.enabled }
  }

  function upsertWorkflowEmployeeTask(
    empId: string,
    opts?: {
      lastWechat?: { at: number; line: string }
      lastLabelPrint?: { at: number; line: string }
      lastShipmentAudit?: { at: number; line: string; detail?: string }
      lastReceiptFeedback?: { at: number; line: string; detail?: string }
      monitor?: WorkflowMonitorPayload | null
      phoneStatus?: PhoneAgentStatusPayload | null
    }
  ) {
    const taskId = `workflow_emp_${empId}`
    const existing = taskList.value.find((t) => t.id === taskId)
    const coreCtx = mergeCorePayloadFromExisting(
      empId,
      opts,
      existing?.payload as Record<string, unknown> | undefined,
    )
    const lastWechat = coreCtx.lastWechat
    const lastLabelPrint = coreCtx.lastLabelPrint
    const lastShipmentAudit = coreCtx.lastShipmentAudit
    const lastReceiptFeedback = coreCtx.lastReceiptFeedback

    let monitor: WorkflowMonitorPayload | undefined
    if (opts && 'monitor' in opts && opts.monitor !== undefined) {
      monitor = opts.monitor === null ? undefined : opts.monitor
    } else if (empId === 'wechat_msg' && existing?.payload?.monitor) {
      monitor = existing.payload.monitor as WorkflowMonitorPayload
    }

    let phoneStatus: PhoneAgentStatusPayload | undefined
    if (opts && 'phoneStatus' in opts && opts.phoneStatus !== undefined) {
      phoneStatus = opts.phoneStatus === null ? undefined : opts.phoneStatus
    } else if (listPhoneAgentEmployeeIds(modsStore.modsForUi).includes(empId) && existing?.payload?.phoneStatus) {
      phoneStatus = existing.payload.phoneStatus as PhoneAgentStatusPayload
    }

    const steps = buildWorkflowStepsForEmployee(empId, {
      ...(lastWechat ? { lastWechat } : {}),
      ...(lastLabelPrint ? { lastLabelPrint } : {}),
      ...(lastShipmentAudit ? { lastShipmentAudit } : {}),
      ...(lastReceiptFeedback ? { lastReceiptFeedback } : {}),
      ...(phoneStatus ? { phoneStatus } : {}),
    })

    /** 微信员工：仅在实际「接收到新消息并完成一轮意图预处理」后才显示步骤进度，避免监控阶段出现 50% 等误导 */
    let progressPct = 0
    let progressLabel = ''
    let workflowProgressStarted = true
    if (isCoreWorkflowEmployeeId(empId)) {
      const prog = computeCoreWorkflowProgressState(empId, steps, coreCtx)
      progressPct = prog.progressPct
      progressLabel = prog.progressLabel
      workflowProgressStarted = prog.workflowProgressStarted
    } else if (resolvePhoneChannelByEmployee(empId) === 'wechat') {
      const ps = phoneStatus
      const psBad =
        !ps ||
        !!(ps.fetchError && String(ps.fetchError).trim()) ||
        ps.phone_agent_get_status_failed ||
        ps.phone_agent_status_route_failed ||
        ps.phone_agent_manager_load_failed
      const started = !psBad && phoneAgentWorkflowProgressShouldStart(ps)
      if (!started) {
        progressPct = 0
        progressLabel = !ps
          ? '正在同步后端 phone-agent 状态…'
          : psBad
            ? '无法计算进度：请先排除状态接口或管理器异常'
            : !ps.running
              ? (() => {
                  const err = String(ps.phone_agent_last_start_error || '').trim()
                  return err
                    ? `待命：未运行 — ${err.length > 60 ? `${err.slice(0, 60)}…` : err}`
                    : '待命：phone-agent 未运行（多为音频采集未启动，见后端日志）'
                })()
              : '待命：链路就绪，等待来电或通话界面（下次轮询会检测微信通话窗）'
        workflowProgressStarted = false
      } else {
        const p = computeWorkflowProgressFromSteps(steps)
        progressPct = p.pct
        progressLabel = p.label
        workflowProgressStarted = true
      }
    } else if (resolvePhoneChannelByEmployee(empId) === 'adb') {
      const ps = phoneStatus
      const started = !!(ps && ps.running && ps.adb_device_connected)
      if (!started) {
        progressPct = 0
        progressLabel = !ps
          ? '正在同步 ADB 电话状态…'
          : !ps.running
            ? '待命：ADB 链路未运行'
            : !ps.adb_available
              ? '待命：未检测到 adb'
              : '待命：等待设备在线'
        workflowProgressStarted = false
      } else {
        const p = computeWorkflowProgressFromSteps(steps)
        progressPct = p.pct
        progressLabel = p.label
        workflowProgressStarted = true
      }
    } else {
      const p = computeWorkflowProgressFromSteps(steps)
      progressPct = p.pct
      progressLabel = p.label
    }

    const workflowProgressIdle = !workflowProgressStarted

    const monitorLine = buildWorkflowMonitorLine(
      empId,
      steps,
      monitor,
      lastWechat,
      lastLabelPrint,
      lastShipmentAudit,
      lastReceiptFeedback,
      phoneStatus
    )
    const hint = computeWorkflowCurrentHint(
      empId,
      steps,
      lastWechat,
      monitor,
      lastLabelPrint,
      lastShipmentAudit,
      lastReceiptFeedback,
      phoneStatus
    )
    const meta = resolveWorkflowEmployeePanelMeta(empId)
    if (!meta) return
    const summaryParts = [meta.summary]
    appendCoreWorkflowSummaryParts(empId, summaryParts, coreCtx)
    if (resolvePhoneChannelByEmployee(empId) === 'wechat' && phoneStatus) {
      const ps = phoneStatus
      const bits = [
        ps.running ? '运行中' : '未运行',
        ps.window_monitor_available ? '窗口监控 OK' : '窗口监控不可用',
        ps.lastPolledAt ? `上次同步 ${formatWorkflowClock(ps.lastPolledAt)}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
      summaryParts.push(`电话业务员状态：${bits}`)
      if (ps.last_popup_detected_at_ms) {
        summaryParts.push(
          `识别弹窗：${formatWorkflowClock(ps.last_popup_detected_at_ms)} · ${ps.last_popup_source || '—'} · ${String(ps.last_popup_title || '').slice(0, 60)}`
        )
      }
      if (ps.last_click_at_ms != null && ps.last_click_at_ms !== undefined) {
        summaryParts.push(
          `接听点击：${ps.last_click_ok ? '成功' : '失败'} · ${formatWorkflowClock(ps.last_click_at_ms)} · ${ps.last_click_method || '—'}`
        )
      }
      if (ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined && (ps.last_asr_text || '').trim()) {
        summaryParts.push(
          `对方语音(ASR) ${formatWorkflowClock(ps.last_asr_at_ms)}：${String(ps.last_asr_text).slice(0, 160)}${
            String(ps.last_asr_text).length > 160 ? '…' : ''
          }`
        )
      }
      if (ps.last_reply_at_ms != null && ps.last_reply_at_ms !== undefined && (ps.last_reply_text || '').trim()) {
        summaryParts.push(
          `回复送 VB ${formatWorkflowClock(ps.last_reply_at_ms)}：${String(ps.last_reply_text).slice(0, 160)}${
            String(ps.last_reply_text).length > 160 ? '…' : ''
          }`
        )
      }
    }
    if (resolvePhoneChannelByEmployee(empId) === 'adb' && phoneStatus) {
      const ps = phoneStatus
      const bits = [
        ps.running ? '运行中' : '未运行',
        ps.adb_available ? 'ADB OK' : 'ADB 不可用',
        ps.adb_device_connected ? `设备 ${ps.adb_device_serial || 'online'}` : '无在线设备',
        ps.adb_call_state ? `状态 ${String(ps.adb_call_state).toUpperCase()}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
      summaryParts.push(`真实电话状态：${bits}`)
      if (ps.adb_last_error) {
        summaryParts.push(`最近错误：${String(ps.adb_last_error).slice(0, 120)}`)
      }
    }

    upsertTask({
      id: taskId,
      type: 'workflow_employee',
      source: 'system',
      title: meta.title,
      status: 'running',
      progress: progressPct,
      stage: computeWorkflowStageLine(
        empId,
        lastWechat,
        lastLabelPrint,
        lastShipmentAudit,
        lastReceiptFeedback,
        phoneStatus
      ),
      summary: summaryParts.join('\n\n'),
      payload: {
        employeeId: empId,
        workflowSteps: steps,
        workflowCurrentHint: hint,
        workflowProgressPct: progressPct,
        workflowProgressLabel: progressLabel,
        workflowProgressIdle,
        workflowProgressStarted,
        workflowMonitorLine: monitorLine,
        ...(lastWechat ? { lastWechat } : {}),
        ...(lastLabelPrint ? { lastLabelPrint } : {}),
        ...(lastShipmentAudit ? { lastShipmentAudit } : {}),
        ...(lastReceiptFeedback ? { lastReceiptFeedback } : {}),
        ...(monitor ? { monitor } : {}),
        ...(phoneStatus ? { phoneStatus } : {}),
      },
    })
  }

  function onWechatStarFeedPolled(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!enabled.wechat_msg) return
    if (!taskList.value.some((t) => t.id === 'workflow_emp_wechat_msg')) return
    upsertWorkflowEmployeeTask('wechat_msg', buildWechatMonitorUpdate(d))
  }

  function syncWorkflowEmployeePanelTasks(enabled: Record<string, boolean>) {
    const merged = { ...readWorkflowEmployeeEnabledMap(), ...enabled }
    const modMeta = buildModWorkflowPanelMeta(modsStore.modsForUi)
    const allEmpIds = new Set([...Object.keys(modMeta)])
    for (const empId of allEmpIds) {
      const taskId = `workflow_emp_${empId}`
      if (merged[empId]) {
        if (resolveWorkflowEmployeePanelMeta(empId)) {
          upsertWorkflowEmployeeTask(empId)
        }
      } else {
        const idx = taskList.value.findIndex((t) => t.id === taskId)
        if (idx !== -1) {
          taskList.value.splice(idx, 1)
          if (activeTaskId.value === taskId) {
            activeTaskId.value = taskList.value[0]?.id || ''
          }
        }
      }
    }
    pruneStaleWorkflowEmployeeTasks()
    sortTaskList()
    if (getEnabledPhoneEmployeeIds().length > 0) {
      if (!phoneAgentPollTimer) startPhoneAgentStatusPoll()
    } else {
      stopPhoneAgentStatusPoll()
    }
  }

  function resyncEnabledWorkflowEmployeeTasks() {
    const enabled = readWorkflowEmployeeEnabledMap()
    const modMeta = buildModWorkflowPanelMeta(modsStore.modsForUi)
    const allEmpIds = new Set([...Object.keys(modMeta)])
    for (const empId of allEmpIds) {
      if (enabled[empId] && resolveWorkflowEmployeePanelMeta(empId)) {
        upsertWorkflowEmployeeTask(empId)
      }
    }
    pruneStaleWorkflowEmployeeTasks()
    sortTaskList()
  }

  function onWorkflowAiEmployeesChanged(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const en = d.enabled
    if (en && typeof en === 'object') {
      syncWorkflowEmployeePanelTasks(en as Record<string, boolean>)
      return
    }
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
  }

  function onWorkflowEmployeesStorage(e: StorageEvent) {
    if (e.key !== workflowAiEmployeesStorageKey()) return
    workflowAiEmployeesStore.reloadFromLocalStorage()
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
  }

  function onStarRefreshOrIntentChangedForWorkflow() {
    resyncEnabledWorkflowEmployeeTasks()
  }

  /**
   * 兜底同步：避免仅靠自定义事件导致偶发漏同步（例如页面切换后返回聊天页）。
   * 只要本地存在已启用员工，就从 storage 重建任务面板常驻项。
   */
  function ensureWorkflowEmployeePanelTasksFromStorage() {
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!Object.values(enabled).some(Boolean)) return
    syncWorkflowEmployeePanelTasks(enabled)
  }

  function onWindowFocusForWorkflowTasks() {
    ensureWorkflowEmployeePanelTasksFromStorage()
  }

  function onVisibilityChangeForWorkflowTasks() {
    if (document.visibilityState === 'visible') {
      ensureWorkflowEmployeePanelTasksFromStorage()
    }
  }

  function registerWorkflowPanelWatchers(
    persistTaskPanelStateForSession: (targetSessionId?: string) => void,
    currentTask: { value: ShipmentTask | null },
  ) {
watch(
  [taskList, activeTaskId, expandedTaskIds, taskFilter, currentTask],
  () => {
    persistTaskPanelStateForSession()
  },
  { deep: true }
)

watch(
  () => modsStore.modsForWorkflowUi,
  (mods) => {
    workflowAiEmployeesStore.hydrateFromMods(mods)
    workflowAiEmployeesStore.pruneOrphanWorkflowEmployeeToggles(mods)
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
  },
  { deep: true }
)

watch(
  () => workflowAiEmployeesStore.enabled,
  () => {
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
  },
  { deep: true }
)
  }

  function mountWorkflowPanel() {
    window.addEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTaskEnqueue)
    window.addEventListener('xcagi:wechat-shipment-preview-task', onWechatShipmentPreviewTask)
    window.addEventListener('xcagi:workflow-label-print-signal', onWorkflowLabelPrintSignal)
    window.addEventListener('xcagi:workflow-receipt-feedback-signal', onWorkflowReceiptFeedbackSignal)
    window.addEventListener('xcagi:workflow-ai-employees-changed', onWorkflowAiEmployeesChanged)
    window.addEventListener('storage', onWorkflowEmployeesStorage)
    window.addEventListener('xcagi:auto-refresh-wechat-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.addEventListener('xcagi:pro-intent-experience-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.addEventListener('xcagi:wechat-star-feed-polled', onWechatStarFeedPolled)
    window.addEventListener('focus', onWindowFocusForWorkflowTasks)
    document.addEventListener('visibilitychange', onVisibilityChangeForWorkflowTasks)
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
    window.setTimeout(() => ensureWorkflowEmployeePanelTasksFromStorage(), 120)
  }

  function unmountWorkflowPanel() {
    window.removeEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTaskEnqueue)
    window.removeEventListener('xcagi:wechat-shipment-preview-task', onWechatShipmentPreviewTask)
    window.removeEventListener('xcagi:workflow-label-print-signal', onWorkflowLabelPrintSignal)
    window.removeEventListener('xcagi:workflow-receipt-feedback-signal', onWorkflowReceiptFeedbackSignal)
    window.removeEventListener('xcagi:workflow-ai-employees-changed', onWorkflowAiEmployeesChanged)
    window.removeEventListener('storage', onWorkflowEmployeesStorage)
    window.removeEventListener('xcagi:auto-refresh-wechat-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.removeEventListener('xcagi:pro-intent-experience-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.removeEventListener('xcagi:wechat-star-feed-polled', onWechatStarFeedPolled)
    window.removeEventListener('focus', onWindowFocusForWorkflowTasks)
    document.removeEventListener('visibilitychange', onVisibilityChangeForWorkflowTasks)
    stopPhoneAgentStatusPoll()
  }

  return {
    onWechatAiTaskEnqueue,
    readWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask,
    syncWorkflowEmployeePanelTasks,
    mountWorkflowPanel,
    unmountWorkflowPanel,
    registerWorkflowPanelWatchers,
  }
}
