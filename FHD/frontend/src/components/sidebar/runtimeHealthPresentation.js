/** Translate service health into a state users can act on without exposing internal errors. */
export function runtimeHealthPresentation(data, connection = 'ready') {
  if (connection === 'reachable') {
    return { tone: 'pending', text: '服务可连接，状态待确认', detail: '接口已响应，整体健康状态仍待健康检查确认。' }
  }
  if (connection === 'checking') {
    return { tone: 'pending', text: '正在检查服务', detail: '正在确认业务服务与 AI 能力是否就绪。' }
  }
  if (connection === 'offline') {
    // Soft copy: health probe failed — do not claim total product outage (voice/API may still work).
    return {
      tone: 'offline',
      text: '健康检查未响应',
      detail: '最近一次服务健康检查未成功。这不等于全部功能不可用；若语音或其它接口仍可用，请稍后自动重试或打开设置检查连接。',
    }
  }
  const status = String(data?.status || '').toLowerCase()
  const runtime = data?.runtime || {}
  const reasons = Array.isArray(data?.degradedReasons) ? data.degradedReasons : []
  const blockers = Array.isArray(runtime.blockers) ? runtime.blockers : []
  const failed = ['error', 'unhealthy', 'failed'].includes(status)
    || ['error', 'unhealthy', 'failed'].includes(String(runtime.status || '').toLowerCase())
    || blockers.length > 0
  if (failed) {
    return { tone: 'offline', text: '业务服务异常', detail: '业务服务存在阻断问题。请打开设置检查服务状态，处理后再执行业务操作。' }
  }
  if (status === 'degraded' || runtime.status === 'degraded' || reasons.length) {
    const modelStatus = data?.sessionModel?.status
    if (modelStatus === 'login_required' || modelStatus === 'auth_error') {
      return { tone: 'warning', text: 'AI 账号连接异常', detail: '当前登录会话未通过模型服务验证。请在系统设置检查账号连接后重试。' }
    }
    if (modelStatus === 'configuration_error') {
      return { tone: 'warning', text: '默认 AI 配置不可用', detail: '当前账号的默认模型配置未通过检查。请在系统设置的模型服务中选择可用模型或跟随平台默认。' }
    }
    if (modelStatus === 'connection_error') {
      return { tone: 'warning', text: 'AI 服务连接未完成', detail: '暂时无法确认当前账号的模型服务连接，系统会自动重试。请在系统设置检查连接。' }
    }
    const onlyAi = reasons.length === 1 && reasons[0] === 'LLM_RUNTIME_UNAVAILABLE'
    return onlyAi
      ? { tone: 'warning', text: '部分 AI 能力未就绪', detail: '业务服务可连接，尚未确认可用的模型配置。请打开系统设置检查当前账号的模型服务。' }
      : { tone: 'warning', text: '部分服务异常', detail: '服务当前以降级状态运行，部分能力可能不可用。请打开设置检查相关服务。' }
  }
  if (['healthy', 'ok'].includes(status)) {
    return { tone: 'online', text: '系统正常', detail: data?.sessionModel?.status === 'configured'
      ? '业务服务正常，当前账号的模型配置已确认；实际模型响应以具体任务为准。'
      : '最近一次检查：业务服务及健康接口报告的依赖均正常。点击打开系统设置。' }
  }
  return { tone: 'pending', text: '服务状态待确认', detail: '尚未取得有效的服务健康状态。请打开设置检查，系统会自动重试。' }
}
