/** Self-contained runtime UI using host SDK v1; no host rebuild or remote code. */
export async function mount(root, sdk) {
  if (sdk.version !== 1) throw new Error('此扩展需要宿主 SDK v1')
  const node = (tag, text = '') => { const value = document.createElement(tag); value.textContent = text; return value }
  const page = node('section')
  page.style.cssText = 'max-width:860px;margin:auto;display:grid;gap:20px;color:var(--text-primary,#172554)'
  const title = node('h1', '太阳鸟考勤转换')
  const status = node('p', '正在读取当前账号配置…'); status.setAttribute('role', 'status')
  const output = node('div')
  page.append(title, node('p', '使用当前账号的人员名单、模板与班制规则生成考勤表。'), status)
  root.append(page)
  let policy = {}
  const controls = []
  const action = (label, callback) => {
    const button = node('button', label)
    button.type = 'button'
    button.style.cssText = 'padding:10px 16px;border:0;border-radius:8px;background:#2563eb;color:white;cursor:pointer'
    button.addEventListener('click', async () => {
      controls.forEach((control) => { control.disabled = true })
      try { await callback() } catch (error) { if (!sdk.signal.aborted) status.textContent = error.message || '操作失败，请重试' }
      finally { controls.forEach((control) => { control.disabled = false }) }
    }, { signal: sdk.signal })
    controls.push(button)
    return button
  }
  const field = (label, type) => {
    const wrap = node('label', label)
    const input = node('input'); input.type = type
    input.style.cssText = 'display:block;margin-top:8px;padding:8px;max-width:100%;border:1px solid #cbd5e1;border-radius:6px'
    wrap.append(input); page.append(wrap); return input
  }
  const request = async (path, init) => {
    const response = await sdk.request(path, init)
    const body = await response.json()
    if (!response.ok || body.success !== true) throw new Error(typeof body.detail === 'string' ? body.detail : body.message || '操作未成功')
    return body
  }
  const template = field('考勤模板（含明细工作表）', 'file'); template.accept = '.xlsx'
  const replace = field('我确认替换当前账号的现有模板', 'checkbox')
  page.append(action('保存模板', async () => {
    if (!template.files?.[0]) throw new Error('请选择考勤模板')
    const form = new FormData(); form.append('file', template.files[0]); form.append('replace_existing', String(replace.checked))
    await request('/attendance/template', { method: 'POST', body: form }); status.textContent = '模板已保存'
  }))
  const input = field('钉钉考勤文件', 'file'); input.accept = '.xlsx,.xlsm,.xls'
  const month = field('考勤月份', 'month')
  page.append(action('转换考勤表', async () => {
    if (!input.files?.[0]) throw new Error('请选择考勤文件')
    status.textContent = '正在转换考勤表…'; output.replaceChildren()
    const form = new FormData(); form.append('file', input.files[0]); form.append('month', month.value)
    const result = (await request('/attendance/convert-upload', { method: 'POST', body: form })).data
    const path = result.download_path
    if (typeof path !== 'string' || !path.startsWith(`/api/mod/${sdk.modId}/attendance/download?file=output-`)) throw new Error('转换结果缺少有效下载地址')
    const link = node('a', '下载转换后的考勤表'); link.href = path; link.download = ''
    output.append(link)
    status.textContent = `转换完成：${result.employees_matched} 人，${result.rows_used_for_template} 条考勤记录。`
  }), output)
  page.append(node('h2', '转换规则'))
  const segments = field('工作日正班时段（逗号分隔）', 'text')
  const keywords = field('适用考勤组（逗号分隔）', 'text')
  const sunday = field('周日按加班处理', 'checkbox')
  page.append(action('保存转换规则', async () => {
    const value = { ...policy, weekday_segments: segments.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean), company_factory_group_keywords: keywords.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean), sunday_empty_schedule: sunday.checked, sunday_map_sqrt_to_star: sunday.checked }
    policy = (await request('/attendance/policy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ attendance_policy: value }) })).attendance_policy
    status.textContent = '转换规则已保存'
  }))
  try {
    const result = (await request('/attendance/rules')).data
    policy = result.attendance_policy || {}
    segments.value = (policy.weekday_segments || ['08:00-12:00', '13:30-17:30']).join(', ')
    keywords.value = (policy.company_factory_group_keywords || ['公司-考勤', '公司正班', '惠州工厂-正班', '工厂正班']).join(', ')
    sunday.checked = policy.sunday_empty_schedule !== false
    status.textContent = `当前账号人员 ${result.roster_count} 人；${result.template_ready ? '模板已就绪' : '请先保存或安装考勤模板'}。`
  } catch (error) { if (!sdk.signal.aborted) status.textContent = error.message }
  return () => page.remove()
}
