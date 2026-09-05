/** Translate service health into a state users can act on without exposing internal errors. */
export function runtimeHealthPresentation(data, connection = 'ready') {
  if (connection === 'checking') {
    return { tone: 'pending', text: '正在检查服务', detail: '正在确认业务服务与 AI 能力是否就绪。' }
  }
  if (connection === 'offline') {
    return { tone: 'offline', text: '服务连接中断', detail: '暂时无法连接业务服务。打开设置检查连接，恢复后会自动重新检查。' }
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
    const onlyLocalAi = reasons.length === 1 && reasons[0] === 'LLM_RUNTIME_UNAVAILABLE'
    return onlyLocalAi
      ? { tone: 'warning', text: '部分 AI 能力未就绪', detail: '业务服务可连接，本地 AI 运行能力尚未就绪。云端模型是否可用请在设置的模型服务中确认。' }
      : { tone: 'warning', text: '部分服务异常', detail: '服务当前以降级状态运行，部分能力可能不可用。请打开设置检查相关服务。' }
  }
  if (['healthy', 'ok'].includes(status)) {
    return { tone: 'online', text: '系统正常', detail: '最近一次检查：业务服务及健康接口报告的依赖均正常。点击打开系统设置。' }
  }
  return { tone: 'pending', text: '服务状态待确认', detail: '尚未取得有效的服务健康状态。请打开设置检查，系统会自动重试。' }
}
