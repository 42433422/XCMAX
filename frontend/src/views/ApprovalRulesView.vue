<template>
  <div class="approval-rules-view">
    <div class="view-header">
      <h2>审批流程规则</h2>
      <p class="subtitle">配置工作流中需要审批的操作节点</p>
    </div>

    <div class="rules-container">
      <div class="rules-header">
        <div class="enable-toggle">
          <label class="toggle-label">
            <span>启用审批功能</span>
            <div class="toggle-switch" :class="{ active: enabled }" @click="toggleEnabled">
              <div class="toggle-slider"></div>
            </div>
          </label>
        </div>
      </div>

      <div class="rules-list" v-if="enabled">
        <div class="rule-item" v-for="(rule, index) in rules" :key="index">
          <div class="rule-info">
            <div class="rule-main">
              <span class="rule-action">{{ getActionLabel(rule.tool_id, rule.action) }}</span>
              <span class="rule-trigger" :class="rule.trigger">{{ getTriggerLabel(rule.trigger) }}</span>
            </div>
            <div class="rule-description">{{ rule.description || '无描述' }}</div>
            <div class="rule-path">{{ rule.tool_id }} / {{ rule.action }}</div>
          </div>
          <div class="rule-actions">
            <button class="btn-edit" @click="editRule(index)" title="编辑">
              <i class="fa fa-pencil"></i>
            </button>
            <button class="btn-delete" @click="deleteRule(index)" title="删除">
              <i class="fa fa-trash"></i>
            </button>
          </div>
        </div>

        <div class="add-rule-section">
          <h3>添加新规则</h3>
          <div class="add-form">
            <div class="form-group">
              <label>工具 ID</label>
              <select v-model="newRule.tool_id">
                <option value="">选择工具</option>
                <option value="shipment_generate">发货单生成</option>
                <option value="print">打印</option>
                <option value="products">产品管理</option>
                <option value="customers">客户管理</option>
              </select>
            </div>
            <div class="form-group">
              <label>操作</label>
              <select v-model="newRule.action">
                <option value="">选择操作</option>
                <option value="execute">执行</option>
                <option value="create">创建</option>
                <option value="update">更新</option>
                <option value="delete">删除</option>
              </select>
            </div>
            <div class="form-group">
              <label>触发方式</label>
              <select v-model="newRule.trigger">
                <option value="always">始终审批</option>
                <option value="conditional">条件审批</option>
                <option value="never">从不审批</option>
              </select>
            </div>
            <div class="form-group full-width">
              <label>描述</label>
              <input type="text" v-model="newRule.description" placeholder="规则描述" />
            </div>
            <button class="btn-add" @click="addRule" :disabled="!canAddRule">
              <i class="fa fa-plus"></i> 添加规则
            </button>
          </div>
        </div>
      </div>

      <div class="no-rules" v-else>
        <i class="fa fa-check-circle-o"></i>
        <p>审批功能已禁用，所有操作将直接执行，无需审批。</p>
      </div>
    </div>

    <div class="attendance-section" v-if="enabled">
      <h3>考勤转换规则（钉钉 → 明细）</h3>
      <p class="subtitle hint">
        与上方审批规则保存在同一配置（<code>resources/config/approval_config.yaml</code>）。每人 B 列「18:30记加班」「09:00上班」等仍在 Excel
        里单独写。
      </p>
      <div class="attendance-grid">
        <div class="form-group full-width">
          <label>公司/工厂考勤组关键字（每行一条，匹配考勤组或班次名）</label>
          <textarea v-model="kwText" rows="4" class="mono"></textarea>
        </div>
        <div class="form-group">
          <label>工作日正班时段 1</label>
          <input v-model="attendancePolicy.weekday_segments[0]" type="text" class="mono" placeholder="08:00-12:00" />
        </div>
        <div class="form-group">
          <label>工作日正班时段 2</label>
          <input v-model="attendancePolicy.weekday_segments[1]" type="text" class="mono" placeholder="13:30-17:30" />
        </div>
        <div class="form-group full-width">
          <label>公司/工厂周六无班次时段时的默认半天窗（工厂等，不含下方「公司大小周」）</label>
          <input v-model="attendancePolicy.saturday_company_alt_segment" type="text" class="mono" placeholder="13:30-16:00" />
        </div>

        <h4 class="attendance-subhead">公司大小周六（仅下方匹配到的「公司员工」；班次名里已写时段时仍优先）</h4>
        <p class="subtitle hint tiny">
          全局锚点：偶数周=大周六（仅第一段），奇数周=小周六（两段）。每人可在明细 B 列写「大小周锚2026-01-10」覆盖为自己的大周六对齐；未写者用此处锚点。工厂员工仍走上面「半天窗」。
        </p>
        <div class="form-group checkbox-row">
          <label class="inline-check">
            <input type="checkbox" v-model="attendancePolicy.company_alternate_saturday.enabled" />
            启用公司大小周周六
          </label>
        </div>
        <div class="form-group">
          <label>锚点周六（YYYY-MM-DD，对齐到当周周六）</label>
          <input v-model="attendancePolicy.company_alternate_saturday.anchor_saturday" type="text" class="mono" placeholder="2026-01-03" />
        </div>
        <div class="form-group full-width">
          <label>公司员工匹配子串（每行一条，考勤组或班次名包含即算）</label>
          <textarea v-model="casGroupText" rows="3" class="mono"></textarea>
        </div>
        <div class="form-group full-width">
          <label>大周六正班时段（每行 HH:MM-HH:MM）</label>
          <textarea v-model="casBigText" rows="2" class="mono"></textarea>
        </div>
        <div class="form-group full-width">
          <label>小周六正班时段（每行一段）</label>
          <textarea v-model="casSmallText" rows="3" class="mono"></textarea>
        </div>

        <div class="form-group checkbox-row">
          <label class="inline-check">
            <input type="checkbox" v-model="attendancePolicy.sunday_empty_schedule" />
            周日不设正班裁窗（与「周日仅加班」策略配合）
          </label>
        </div>
        <div class="form-group checkbox-row">
          <label class="inline-check">
            <input type="checkbox" v-model="attendancePolicy.sunday_map_sqrt_to_star" />
            周日将原正班 √ / 交叉 ☆ 统一记为星期天加班 ★
          </label>
        </div>
        <button type="button" class="btn-save-att" @click="saveAttendanceOnly">
          保存考勤规则
        </button>
      </div>
    </div>

    <div class="pending-approvals" v-if="enabled && pendingApprovals.length > 0">
      <h3>待审批请求 ({{ pendingApprovals.length }})</h3>
      <div class="pending-list">
        <div class="pending-item" v-for="item in pendingApprovals" :key="item.request_id">
          <div class="pending-info">
            <span class="pending-action">{{ getActionLabel(item.tool_id, item.action) }}</span>
            <span class="pending-time">{{ formatTime(item.created_at) }}</span>
          </div>
          <div class="pending-actions">
            <button class="btn-approve" @click="approveItem(item)">
              <i class="fa fa-check"></i> 通过
            </button>
            <button class="btn-reject" @click="rejectItem(item)">
              <i class="fa fa-times"></i> 拒绝
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="edit-modal" v-if="editingIndex !== null" @click.self="closeEdit">
      <div class="modal-content">
        <h3>编辑规则</h3>
        <div class="form-group">
          <label>描述</label>
          <input type="text" v-model="editForm.description" />
        </div>
        <div class="form-group">
          <label>触发方式</label>
          <select v-model="editForm.trigger">
            <option value="always">始终审批</option>
            <option value="conditional">条件审批</option>
            <option value="never">从不审批</option>
          </select>
        </div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="closeEdit">取消</button>
          <button class="btn-save" @click="saveEdit">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { appAlert } from '@/utils/appDialog'

const enabled = ref(true)
const rules = ref([])
const pendingApprovals = ref([])
const editingIndex = ref(null)
const editForm = ref({ description: '', trigger: 'always' })

const newRule = ref({
  tool_id: '',
  action: '',
  trigger: 'always',
  description: ''
})

const defaultCompanyAlternateSaturday = () => ({
  enabled: true,
  anchor_saturday: '2026-01-03',
  group_match_substrings: ['公司-考勤', '公司正班'],
  big_week_segments: ['09:00-12:00'],
  small_week_segments: ['09:00-12:00', '13:30-16:00']
})

const defaultAttendancePolicy = () => ({
  company_factory_group_keywords: ['公司-考勤', '公司正班', '惠州工厂-正班', '工厂正班'],
  weekday_segments: ['08:00-12:00', '13:30-17:30'],
  saturday_company_alt_segment: '13:30-16:00',
  sunday_empty_schedule: true,
  sunday_map_sqrt_to_star: true,
  company_alternate_saturday: defaultCompanyAlternateSaturday()
})

const attendancePolicy = ref(defaultAttendancePolicy())

const kwText = computed({
  get: () => (attendancePolicy.value.company_factory_group_keywords || []).join('\n'),
  set: (v) => {
    const lines = String(v || '')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    attendancePolicy.value.company_factory_group_keywords = lines.length
      ? lines
      : [...defaultAttendancePolicy().company_factory_group_keywords]
  }
})

const _cas = () =>
  attendancePolicy.value.company_alternate_saturday || defaultCompanyAlternateSaturday()

const casGroupText = computed({
  get: () => (_cas().group_match_substrings || []).join('\n'),
  set: (v) => {
    if (!attendancePolicy.value.company_alternate_saturday) {
      attendancePolicy.value.company_alternate_saturday = defaultCompanyAlternateSaturday()
    }
    const lines = String(v || '')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    attendancePolicy.value.company_alternate_saturday.group_match_substrings = lines.length
      ? lines
      : [...defaultCompanyAlternateSaturday().group_match_substrings]
  }
})

const casBigText = computed({
  get: () => (_cas().big_week_segments || []).join('\n'),
  set: (v) => {
    if (!attendancePolicy.value.company_alternate_saturday) {
      attendancePolicy.value.company_alternate_saturday = defaultCompanyAlternateSaturday()
    }
    const lines = String(v || '')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    attendancePolicy.value.company_alternate_saturday.big_week_segments = lines.length
      ? lines
      : [...defaultCompanyAlternateSaturday().big_week_segments]
  }
})

const casSmallText = computed({
  get: () => (_cas().small_week_segments || []).join('\n'),
  set: (v) => {
    if (!attendancePolicy.value.company_alternate_saturday) {
      attendancePolicy.value.company_alternate_saturday = defaultCompanyAlternateSaturday()
    }
    const lines = String(v || '')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    attendancePolicy.value.company_alternate_saturday.small_week_segments = lines.length
      ? lines
      : [...defaultCompanyAlternateSaturday().small_week_segments]
  }
})

function mergeAttendanceFromApi(raw) {
  const d = defaultAttendancePolicy()
  const r = raw && typeof raw === 'object' ? raw : {}
  const merged = { ...d, ...r }
  if (!Array.isArray(merged.company_factory_group_keywords)) {
    merged.company_factory_group_keywords = [...d.company_factory_group_keywords]
  }
  if (!Array.isArray(merged.weekday_segments) || merged.weekday_segments.length < 2) {
    merged.weekday_segments = [...d.weekday_segments]
  } else {
    merged.weekday_segments = [String(merged.weekday_segments[0]), String(merged.weekday_segments[1])]
  }
  merged.saturday_company_alt_segment = String(merged.saturday_company_alt_segment || d.saturday_company_alt_segment)
  merged.sunday_empty_schedule =
    r.sunday_empty_schedule !== undefined ? !!r.sunday_empty_schedule : d.sunday_empty_schedule
  merged.sunday_map_sqrt_to_star =
    r.sunday_map_sqrt_to_star !== undefined ? !!r.sunday_map_sqrt_to_star : d.sunday_map_sqrt_to_star
  const dcas = defaultCompanyAlternateSaturday()
  const rcas = r.company_alternate_saturday && typeof r.company_alternate_saturday === 'object' ? r.company_alternate_saturday : {}
  merged.company_alternate_saturday = {
    ...dcas,
    ...rcas,
    group_match_substrings: Array.isArray(rcas.group_match_substrings)
      ? rcas.group_match_substrings.map(String)
      : dcas.group_match_substrings,
    big_week_segments: Array.isArray(rcas.big_week_segments) ? rcas.big_week_segments.map(String) : dcas.big_week_segments,
    small_week_segments: Array.isArray(rcas.small_week_segments)
      ? rcas.small_week_segments.map(String)
      : dcas.small_week_segments
  }
  merged.company_alternate_saturday.enabled =
    rcas.enabled !== undefined ? !!rcas.enabled : dcas.enabled
  attendancePolicy.value = merged
}

const canAddRule = computed(() => {
  return newRule.value.tool_id && newRule.value.action
})

const toolLabels = {
  shipment_generate: '发货单生成',
  print: '打印操作',
  products: '产品管理',
  customers: '客户管理'
}

const actionLabels = {
  execute: '执行',
  create: '创建',
  update: '更新',
  delete: '删除'
}

const getActionLabel = (tool_id, action) => {
  return `${toolLabels[tool_id] || tool_id} - ${actionLabels[action] || action}`
}

const getTriggerLabel = (trigger) => {
  const labels = { always: '始终', conditional: '条件', never: '从不' }
  return labels[trigger] || trigger
}

const formatTime = (isoString) => {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN')
}

const toggleEnabled = async () => {
  enabled.value = !enabled.value
  await saveConfig()
}

const loadConfig = async () => {
  try {
    const response = await fetch('/api/ai/approval/pending')
    const data = await response.json()
    if (data.success) {
      pendingApprovals.value = data.data?.pending_approvals || []
    }
  } catch (e) {
    console.error('加载待审批列表失败', e)
  }

  try {
    const response = await fetch('/api/ai/config/approval')
    const data = await response.json()
    if (data.enabled !== undefined) {
      enabled.value = data.enabled
    }
    if (data.rules) {
      rules.value = data.rules
    }
    mergeAttendanceFromApi(data.attendance_policy)
  } catch (e) {
    console.error('加载审批配置失败', e)
  }
}

const saveConfig = async () => {
  try {
    await fetch('/api/ai/config/approval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: enabled.value,
        rules: rules.value,
        attendance_policy: attendancePolicy.value
      })
    })
  } catch (e) {
    console.error('保存审批配置失败', e)
  }
}

const addRule = async () => {
  if (!canAddRule.value) return

  rules.value.push({
    tool_id: newRule.value.tool_id,
    action: newRule.value.action,
    trigger: newRule.value.trigger,
    description: newRule.value.description,
    conditions: {}
  })

  newRule.value = { tool_id: '', action: '', trigger: 'always', description: '' }
  await saveConfig()
}

const editRule = (index) => {
  editingIndex.value = index
  editForm.value = {
    description: rules.value[index].description || '',
    trigger: rules.value[index].trigger || 'always'
  }
}

const saveEdit = async () => {
  if (editingIndex.value !== null) {
    rules.value[editingIndex.value].description = editForm.value.description
    rules.value[editingIndex.value].trigger = editForm.value.trigger
    await saveConfig()
    closeEdit()
  }
}

const closeEdit = () => {
  editingIndex.value = null
}

const deleteRule = async (index) => {
  rules.value.splice(index, 1)
  await saveConfig()
}

const approveItem = async (item) => {
  try {
    const response = await fetch('/api/ai/approval/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: item.plan_id })
    })
    const data = await response.json()
    if (data.success) {
      await appAlert(data.message || '审批已通过')
      if (data.data?.workflow_executed && data.data?.workflow_result) {
        const wr = data.data.workflow_result
        console.log('工作流执行结果:', wr)
        await appAlert(
          `工作流已执行完成！\n` +
          `执行节点: ${wr.nodes_executed}/${wr.nodes_total}\n` +
          `状态: ${wr.has_errors ? '有错误' : '成功'}`
        )
      }
      await loadConfig()
    } else {
      await appAlert(data.message || '审批失败')
    }
  } catch (e) {
    console.error('审批失败', e)
    await appAlert('审批请求失败: ' + e.message)
  }
}

const rejectItem = async (item) => {
  try {
    const response = await fetch('/api/ai/approval/reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_id: item.plan_id })
    })
    const data = await response.json()
    if (data.success) {
      await loadConfig()
    }
  } catch (e) {
    console.error('拒绝失败', e)
  }
}

const saveAttendanceOnly = async () => {
  await saveConfig()
  await appAlert('考勤规则已保存')
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.approval-rules-view {
  padding: 20px;
  max-width: 900px;
  margin: 0 auto;
}

.view-header h2 {
  margin: 0 0 5px 0;
  color: #333;
}

.subtitle {
  margin: 0 0 20px 0;
  color: #666;
  font-size: 14px;
}

.subtitle.hint {
  font-size: 13px;
  line-height: 1.5;
}

.subtitle.hint code {
  font-size: 12px;
  background: #f5f5f5;
  padding: 1px 4px;
  border-radius: 3px;
}

.attendance-section {
  margin-top: 24px;
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.attendance-section h3 {
  margin: 0 0 8px 0;
  font-size: 16px;
  color: #333;
}

.attendance-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 12px;
}

.attendance-grid .full-width {
  grid-column: 1 / -1;
}

.attendance-grid .checkbox-row {
  grid-column: 1 / -1;
}

.inline-check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #444;
  cursor: pointer;
}

.mono {
  font-family: ui-monospace, Consolas, monospace;
}

.btn-save-att {
  grid-column: 1 / -1;
  padding: 10px 16px;
  background: #1976d2;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  justify-self: start;
}

.btn-save-att:hover {
  background: #1565c0;
}

.attendance-subhead {
  margin: 18px 0 0 0;
  grid-column: 1 / -1;
  font-size: 14px;
  color: #444;
  font-weight: 600;
}

.subtitle.hint.tiny {
  margin: 4px 0 8px 0;
  font-size: 12px;
  grid-column: 1 / -1;
}

.rules-container {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.rules-header {
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid #eee;
}

.toggle-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}

.toggle-switch {
  width: 50px;
  height: 26px;
  background: #ccc;
  border-radius: 13px;
  position: relative;
  transition: background 0.3s;
}

.toggle-switch.active {
  background: #4CAF50;
}

.toggle-slider {
  width: 22px;
  height: 22px;
  background: #fff;
  border-radius: 50%;
  position: absolute;
  top: 2px;
  left: 2px;
  transition: transform 0.3s;
}

.toggle-switch.active .toggle-slider {
  transform: translateX(24px);
}

.rule-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px;
  background: #f9f9f9;
  border-radius: 6px;
  margin-bottom: 10px;
}

.rule-info {
  flex: 1;
}

.rule-main {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 5px;
}

.rule-action {
  font-weight: 600;
  color: #333;
}

.rule-trigger {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.rule-trigger.always {
  background: #ffebee;
  color: #c62828;
}

.rule-trigger.conditional {
  background: #fff3e0;
  color: #ef6c00;
}

.rule-trigger.never {
  background: #e8f5e9;
  color: #2e7d32;
}

.rule-description {
  color: #666;
  font-size: 14px;
  margin-bottom: 3px;
}

.rule-path {
  color: #999;
  font-size: 12px;
  font-family: monospace;
}

.rule-actions {
  display: flex;
  gap: 8px;
}

.rule-actions button {
  padding: 6px 10px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.btn-edit {
  background: #e3f2fd;
  color: #1565c0;
}

.btn-delete {
  background: #ffebee;
  color: #c62828;
}

.add-rule-section {
  margin-top: 25px;
  padding-top: 20px;
  border-top: 1px dashed #ddd;
}

.add-rule-section h3 {
  margin: 0 0 15px 0;
  font-size: 16px;
}

.add-form {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 15px;
}

.form-group {
  display: flex;
  flex-direction: column;
}

.form-group.full-width {
  grid-column: 1 / -1;
}

.form-group label {
  font-size: 13px;
  color: #666;
  margin-bottom: 5px;
}

.form-group select,
.form-group input {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.btn-add {
  grid-column: 1 / -1;
  padding: 10px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.btn-add:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.no-rules {
  text-align: center;
  padding: 40px;
  color: #666;
}

.no-rules i {
  font-size: 48px;
  color: #4CAF50;
  margin-bottom: 15px;
}

.pending-approvals {
  margin-top: 25px;
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.pending-approvals h3 {
  margin: 0 0 15px 0;
  color: #333;
}

.pending-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 15px;
  background: #fff3e0;
  border-radius: 6px;
  margin-bottom: 10px;
}

.pending-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.pending-action {
  font-weight: 600;
  color: #e65100;
}

.pending-time {
  font-size: 12px;
  color: #999;
}

.pending-actions {
  display: flex;
  gap: 8px;
}

.pending-actions button {
  padding: 6px 12px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}

.btn-approve {
  background: #4CAF50;
  color: white;
}

.btn-reject {
  background: #f44336;
  color: white;
}

.edit-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  padding: 25px;
  border-radius: 8px;
  width: 400px;
  max-width: 90%;
}

.modal-content h3 {
  margin: 0 0 20px 0;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.btn-cancel {
  padding: 8px 16px;
  background: #eee;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.btn-save {
  padding: 8px 16px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
</style>
