import { computed, onMounted, ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

/** 钉钉考勤组（参考展示用）：模板消费 name / headcount / shift_type / lines。 */
interface TaiyangniaoScheduleGroup {
  [key: string]: unknown
  name?: unknown
  headcount?: unknown
  shift_type?: unknown
  lines?: string[]
}

/** 考勤规则接口 data（实际消费 lines / saturday_window_label / config / schedule_groups）。 */
interface AttendanceRulesData {
  [key: string]: unknown
  lines?: unknown
  saturday_window_label?: unknown
  config?: unknown
  schedule_groups?: TaiyangniaoScheduleGroup[]
}

// 拆分自 taiyangniao-pro HomeView.vue script（原第 162–367 行）；逻辑逐字迁移，行为不变。
export function useAttendanceHome() {
  // 原有考勤转换相关
  const file = ref<File | null>(null)
  const outputRelpath = ref('424/考勤转换输出.xlsx')
  const templateRelpath = ref('424/考勤-2026-3月份考勤统计表.xlsx')
  const month = ref('')
  const headerRow = ref(0)
  const usePersonnelRoster = ref(true)
  const useLlm = ref(false)
  const loading = ref(false)
  const loadingDl = ref(false)
  const err = ref('')
  const okMsg = ref('')
  const lastOutputRelpath = ref('')

  // 规则加载
  const rulesLoading = ref(true)
  const rulesErr = ref('')
  const rulesPayload = ref<AttendanceRulesData | null>(null)

  // 原有规则相关
  const rulesLines = computed(() => {
    const d = rulesPayload.value
    if (!d || !Array.isArray(d.lines)) return []
    return d.lines.filter((x: unknown): x is string => typeof x === 'string' && x.trim() !== '')
  })

  const rulesWindow = computed(() => {
    const w = rulesPayload.value?.saturday_window_label
    return typeof w === 'string' && w.trim() ? w.trim() : ''
  })

  const rulesConfig = computed(() => {
    const c = rulesPayload.value?.config
    return c && typeof c === 'object' ? (c as Record<string, unknown>) : {}
  })

  const rulesConfigKeys = computed(() => Object.keys(rulesConfig.value).sort())

  const scheduleGroups = computed(() => {
    const raw = rulesPayload.value?.schedule_groups
    return Array.isArray(raw) ? (raw as TaiyangniaoScheduleGroup[]) : []
  })

  function formatConfigValue(v: unknown) {
    if (typeof v === 'boolean') return v ? '是' : '否'
    return String(v)
  }

  async function loadRules() {
    rulesLoading.value = true
    rulesErr.value = ''
    try {
      const res = await apiFetch('/api/mod/taiyangniao-pro/attendance/rules')
      const j = await res.json().catch(() => ({}))
      if (!res.ok) {
        rulesErr.value = j.error || j.message || `HTTP ${res.status}`
        rulesPayload.value = null
        return
      }
      if (!j.success) {
        rulesErr.value = j.error || '无法加载规则'
        rulesPayload.value = null
        return
      }
      rulesPayload.value = j.data && typeof j.data === 'object' ? j.data : null
    } catch (e) {
      rulesErr.value = e instanceof Error ? e.message : String(e)
      rulesPayload.value = null
    } finally {
      rulesLoading.value = false
    }
  }

  onMounted(() => {
    void loadRules()
  })

  function onFile(ev: Event) {
    const target = ev.target as HTMLInputElement | null
    const f = target?.files?.[0]
    file.value = f || null
    err.value = ''
    okMsg.value = ''
  }

  function _basename(rel: unknown) {
    const s = String(rel || '').replace(/\\/g, '/')
    const i = s.lastIndexOf('/')
    return i >= 0 ? s.slice(i + 1) : s || '考勤转换输出.xlsx'
  }

  async function downloadOutput(relpath: string) {
    const rel = String(relpath || '').trim()
    if (!rel) return
    loadingDl.value = true
    err.value = ''
    try {
      const q = new URLSearchParams()
      q.set('relpath', rel)
      const res = await apiFetch(`/api/mod/taiyangniao-pro/attendance/download?${q.toString()}`)
      if (!res.ok) {
        const t = await res.text().catch(() => '')
        err.value = t || `下载失败 HTTP ${res.status}`
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = _basename(rel)
      a.rel = 'noopener'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      err.value = e instanceof Error ? e.message : String(e)
    } finally {
      loadingDl.value = false
    }
  }

  async function doUploadConvert() {
    err.value = ''
    okMsg.value = ''
    if (!file.value) {
      err.value = '请先选择钉钉导出的 Excel 文件。'
      return
    }

    // 检查填写方式是否正确
    const outPath = outputRelpath.value || '424/考勤转换输出.xlsx'
    const tplPath = templateRelpath.value || ''

    // 如果输出路径看起来像一个现有模板文件（包含考勤统计表），但没有单独指定模板
    if (outPath.includes('考勤统计表') && !tplPath) {
      const confirmed = confirm(
        `你填写的输出路径 "${outPath}" 看起来像是一个现有模板文件。\\n\\n` +
        `建议填写方式：\\n` +
        `• 输出相对路径：填一个新文件名，如 "424/考勤转换结果.xlsx"\\n` +
        `• 模板相对路径（可选）：填现有模板文件，如 "${outPath}"\\n\\n` +
        `是否继续当前填写方式？`
      )
      if (!confirmed) {
        return
      }
    }

    loading.value = true
    try {
      const fd = new FormData()
      fd.append('file', file.value)
      fd.append('output_relpath', outputRelpath.value || '424/考勤转换输出.xlsx')
      if (templateRelpath.value) fd.append('template_relpath', templateRelpath.value)
      if (month.value) fd.append('month', month.value)
      fd.append('header_row', String(Number.isFinite(headerRow.value) ? headerRow.value : 0))
      if (useLlm.value) fd.append('use_llm', '1')
      fd.append('use_personnel_roster', usePersonnelRoster.value ? '1' : '0')

      const res = await apiFetch('/api/mod/taiyangniao-pro/attendance/convert-upload', {
        method: 'POST',
        body: fd,
      })
      const j = await res.json().catch(() => ({}))
      if (!res.ok || !j.success) {
        err.value = j.error || j.message || `HTTP ${res.status}`
        return
      }
      const d = j.data || {}
      const rowsIn = Number(d.rows_in ?? 0)
      const rowsStats = Number(d.rows_stats ?? 0)
      // 旧版后端仍可能在「成功」里返回 0 行；新版应返回 422。此处兜底避免误导性绿字。
      if (rowsIn === 0 && rowsStats === 0) {
        err.value =
          '未解析到任何考勤数据行（源表 0 行）。请确认：① 已重新部署/重启并加载当前仓库里的太阳鸟 pro（含智能表头识别）；' +
          '② 或填写「表头所在行」、勾选「LLM 识别表头」后重试。若成功提示里应出现 [表头识别:…] 片段。'
        okMsg.value = ''
        return
      }
      const outRel = d.output_relpath || outputRelpath.value
      lastOutputRelpath.value = outRel
      const hi = d.header_info || {}
      const tag = hi.source ? `[表头识别:${hi.source}@行${hi.header_row}]` : ''
      const llmTag = d.used_llm ? '（LLM 参与）' : ''
      const ru = d.rows_used_for_template
      const ruTxt =
        ru != null && ru !== '' && Number(ru) !== Number(d.rows_in)
          ? `；与名单姓名匹配 ${ru} 条日记录用于回填`
          : ''
      const prc = Number(d.personnel_roster_count ?? 0)
      const prTxt = prc > 0 ? `；人员管理 ${prc} 人` : ''
      okMsg.value = `完成：输出 ${outRel}；钉钉源表 ${d.rows_in ?? '?'} 行，统计 ${d.rows_stats ?? '?'} 行${prTxt}${ruTxt}${tag}${llmTag}。`
      await downloadOutput(outRel)
      if (!err.value) {
        okMsg.value += ' 已自动下载。'
      }
    } catch (e) {
      err.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  return {
    file,
    outputRelpath,
    templateRelpath,
    month,
    headerRow,
    usePersonnelRoster,
    useLlm,
    loading,
    loadingDl,
    err,
    okMsg,
    lastOutputRelpath,
    rulesLoading,
    rulesErr,
    rulesLines,
    rulesWindow,
    rulesConfig,
    rulesConfigKeys,
    scheduleGroups,
    formatConfigValue,
    onFile,
    downloadOutput,
    doUploadConvert,
  }
}
