export type HealthPresentationTone = 'online' | 'degraded' | 'offline' | 'unknown'

export type HealthPresentation = {
  label: string
  detail: string
  tone: HealthPresentationTone
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : []
}

export function presentHealth(payload: unknown, requestOk = true): HealthPresentation {
  if (!requestOk) return { label: '状态未知', detail: '暂时无法读取系统健康状态', tone: 'unknown' }

  const data = objectValue(payload)
  const runtime = objectValue(data.runtime)
  const components = objectValue(runtime.components)
  const requiredFailures = Object.entries(components)
    .filter(([, value]) => {
      const component = objectValue(value)
      return component.required === true && component.ok === false
    })
    .map(([name]) => name)
  const status = String(data.status || '').toLowerCase()
  const runtimeStatus = String(runtime.status || '').toLowerCase()
  const reasons = stringList(data.degradedReasons || data.degraded_reasons)

  if ((runtimeStatus && runtimeStatus !== 'healthy') || requiredFailures.length) {
    const detail = requiredFailures.length ? `关键组件异常：${requiredFailures.join('、')}` : `运行状态：${runtimeStatus || '异常'}`
    return { label: '系统异常', detail, tone: 'offline' }
  }

  if (status === 'healthy') return { label: '系统正常', detail: '核心服务运行正常', tone: 'online' }

  if (status === 'degraded') {
    const onlyLlmUnavailable = reasons.length > 0 && reasons.every((reason) => reason === 'LLM_RUNTIME_UNAVAILABLE')
    if (onlyLlmUnavailable) {
      return { label: '基础功能正常', detail: 'AI 服务待检查', tone: 'degraded' }
    }
    return {
      label: '部分功能受限',
      detail: reasons.length ? reasons.join('、') : '部分服务尚未就绪',
      tone: 'degraded',
    }
  }

  return { label: '状态未知', detail: '健康状态返回值不完整', tone: 'unknown' }
}
