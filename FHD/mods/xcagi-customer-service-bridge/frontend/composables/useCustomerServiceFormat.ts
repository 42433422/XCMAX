/**
 * 内部客服页的纯格式化/解析辅助函数。
 * 无任何外部响应式状态依赖，可独立测试。
 */

export function formatPassivePollTime(iso?: string) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

export function financeTrackLabel(track: string) {
  if (track === 'contract') return '合同'
  if (track === 'token') return 'Token'
  return track || '—'
}

export function formatLedgerYuan(cents: number) {
  return (Number(cents || 0) / 100).toFixed(2)
}

export function formatLedgerTime(raw?: string) {
  if (!raw) return '—'
  const d = new Date(raw)
  return Number.isNaN(d.getTime()) ? raw : d.toLocaleString()
}

export function formatAuditCodeFromLandingId(landingId: unknown) {
  const n = Number(landingId)
  if (!Number.isFinite(n) || n <= 0) return ''
  return `XC-${String(Math.floor(n)).padStart(6, '0')}`
}

export function parseIntakeMessageSections(message: string): Array<{ label: string; value: string }> {
  const text = (message || '').trim()
  if (!text.includes('■')) return []
  const rows: Array<{ label: string; value: string }> = []
  const chunks = text.split(/\n(?=■\s*)/)
  for (const chunk of chunks) {
    const block = chunk.trim()
    if (!block.startsWith('■')) continue
    const lines = block.split('\n')
    const title = lines[0].replace(/^■\s*/, '').trim()
    const body = lines.slice(1).join('\n').trim()
    if (title) rows.push({ label: title, value: body || '—' })
  }
  return rows
}

export function intakeFormPreviewRows(
  form: Record<string, unknown> | null | undefined,
  opts: { auditCode?: string; submittedAt?: string } = {},
) {
  if (!form) return null
  const rows: Array<{ label: string; value: string }> = []
  const code = (opts.auditCode || '').trim() || formatAuditCodeFromLandingId(form.landing_contact_id)
  if (code) rows.push({ label: '审核码', value: code })
  if (opts.submittedAt) rows.push({ label: '提交时间', value: formatPassivePollTime(opts.submittedAt) })
  const name = String(form.name || '').trim()
  const company = String(form.company || '').trim()
  const email = String(form.email || '').trim()
  const phone = String(form.phone || '').trim()
  const message = String(form.message || '').trim()
  if (name) rows.push({ label: '称呼', value: name })
  if (company) rows.push({ label: '公司', value: company })
  if (email) rows.push({ label: '邮箱', value: email })
  if (phone) rows.push({ label: '电话', value: phone })
  const os = String(form.desktop_os || '').trim()
  if (os === 'mac' || os === 'win') {
    rows.push({ label: '电脑系统', value: os === 'mac' ? 'macOS' : 'Windows' })
  }
  if (form.need_mobile === false) {
    rows.push({ label: '手机端', value: '不需要' })
  } else if (form.need_mobile === true || form.need_mobile === undefined) {
    const msgMobile = message.match(/手机端[：:]\s*(需要|不需要)/)
    if (msgMobile && msgMobile[1] === '不需要') {
      rows.push({ label: '手机端', value: '不需要' })
    } else {
      rows.push({ label: '手机端', value: '需要 Android' })
    }
  }
  const sections = parseIntakeMessageSections(message)
  if (sections.length) {
    rows.push(...sections)
  } else if (message) {
    rows.push({ label: '需求说明', value: message })
  }
  return rows.length ? rows : null
}

/** 从 pipeline 中提取公司名（需求表单公司名 > ERP 客户名） */
export function intakeCompanyName(
  pipeline: { intake_form?: { company?: string } | null; erp_customer_name?: string },
): string {
  const form = pipeline.intake_form
  return (
    String(form?.company || '').trim()
    || String(pipeline.erp_customer_name || '').trim()
  )
}

/** 与 displayNameFromPipeline 一致：公司名 > ERP 客户名 > pipeline 用户名 > 登录用户名 */
export function displayNameFromPipeline(
  p: Record<string, unknown>,
  loginUsername: string,
): string {
  const form = p.intake_form as { company?: string } | null | undefined
  const company = String(form?.company || '').trim()
  if (company) return company
  const erp = String(p.erp_customer_name || '').trim()
  if (erp) return erp
  const login = String(loginUsername || '').trim()
  const pipeUser = String(p.username || '').trim()
  if (pipeUser && (!login || pipeUser.toLowerCase() !== login.toLowerCase())) return pipeUser
  return login
}