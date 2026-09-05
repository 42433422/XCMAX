<template>
  <div class="attendance-management">
    <header class="management-header">
      <div>
        <h2>{{ pageTitle }}</h2>
        <p class="subtitle">{{ pageDescription }}</p>
      </div>
      <div class="header-actions">
        <button v-if="isEditable" type="button" class="btn btn-primary" @click="startCreate">
          {{ section === 'personnel' ? '新增人员' : '新增部门' }}
        </button>
        <router-link
          v-if="section === 'records' && conversionEnabled"
          class="btn btn-primary"
          to="/mod/sunbird-attendance-custom/convert"
        >
          上传考勤表
        </router-link>
        <router-link
          v-if="section === 'schedules' && conversionEnabled"
          class="btn btn-primary"
          to="/mod/sunbird-attendance-custom/convert"
        >
          转换规则（定制）
        </router-link>
        <button type="button" class="btn" :disabled="loading" @click="loadData()">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <dialog v-if="isEditable" ref="editorDialog" class="editor-card" aria-labelledby="attendance-editor-title" @cancel.prevent="cancelEdit">
      <div class="editor-heading">
        <h3 id="attendance-editor-title">
          {{
            editingId
              ? `编辑${section === 'personnel' ? '人员' : '部门'}`
              : `新增${section === 'personnel' ? '人员' : '部门'}`
          }}
        </h3>
        <button type="button" class="close-btn" aria-label="关闭编辑" :disabled="saving" @click="cancelEdit">×</button>
      </div>

      <div v-if="section === 'personnel'" class="form-grid">
        <label>
          <span>姓名 *</span>
          <input v-model.trim="employeeForm.employee_name" autocomplete="off" autofocus />
        </label>
        <label>
          <span>工号</span>
          <input v-model.trim="employeeForm.employee_no" autocomplete="off" />
        </label>
        <label>
          <span>部门</span>
          <input
            v-model.trim="employeeForm.department"
            list="attendance-departments"
            autocomplete="off"
          />
          <datalist id="attendance-departments">
            <option v-for="name in departmentNames" :key="name" :value="name" />
          </datalist>
        </label>
        <label>
          <span>上级部门</span>
          <input v-model.trim="employeeForm.main_department" autocomplete="off" />
        </label>
        <label>
          <span>考勤组</span>
          <input v-model.trim="employeeForm.attendance_group" autocomplete="off" />
        </label>
        <label>
          <span>岗位 / 性质</span>
          <input v-model.trim="employeeForm.position" autocomplete="off" />
        </label>
        <label>
          <span>钉钉用户 ID</span>
          <input v-model.trim="employeeForm.user_id" autocomplete="off" />
        </label>
      </div>

      <div v-else class="form-grid">
        <label>
          <span>部门名称 *</span>
          <input v-model.trim="departmentForm.department" autocomplete="off" autofocus />
        </label>
        <label>
          <span>上级部门</span>
          <input v-model.trim="departmentForm.main_department" autocomplete="off" />
        </label>
        <label>
          <span>考勤组</span>
          <input v-model.trim="departmentForm.attendance_group" autocomplete="off" />
        </label>
      </div>

      <p v-if="editorError" class="inline-error" role="alert">{{ editorError }}</p>
      <div class="editor-actions">
        <button type="button" class="btn btn-primary" :disabled="saving" @click="saveEditor">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button type="button" class="btn" :disabled="saving" @click="cancelEdit">取消</button>
      </div>
    </dialog>

    <section v-if="section !== 'schedules'" class="toolbar-card">
      <div class="search-box">
        <span aria-hidden="true">⌕</span>
        <input
          v-model.trim="search"
          :placeholder="searchPlaceholder"
          autocomplete="off"
          @keyup.enter="applyFilters"
        />
      </div>
      <select
        v-if="section === 'records'"
        v-model="month"
        aria-label="统计月份"
        @change="applyFilters"
      >
        <option value="">全部月份</option>
        <option v-for="item in months" :key="item" :value="item">{{ item }}</option>
      </select>
      <button type="button" class="btn" @click="applyFilters">查询</button>
      <span class="total-text">共 {{ total }} 条</span>
    </section>

    <div v-if="error" class="state-card state-card-error" role="alert">
      <strong>数据加载失败</strong>
      <span>{{ error }}</span>
      <button type="button" class="btn" @click="loadData()">重试</button>
    </div>
    <div v-else-if="loading" class="state-card" aria-live="polite">正在读取{{ pageTitle }}…</div>

    <section v-else-if="section === 'schedules'" class="schedule-grid">
      <article v-for="group in scheduleGroups" :key="group.name" class="schedule-card">
        <div class="schedule-card-heading">
          <div>
            <span class="card-kicker">{{ group.shift_type || '固定班制' }}</span>
            <h3>{{ group.name }}</h3>
          </div>
          <span class="count-pill">{{ group.headcount || '按导入数据统计' }}</span>
        </div>
        <ul>
          <li v-for="line in group.lines || []" :key="line">{{ line }}</li>
        </ul>
      </article>
      <article v-if="!scheduleGroups.length" class="state-card">尚未配置排班资源。</article>
      <article v-if="ruleLines.length" class="schedule-card schedule-card-wide">
        <span class="card-kicker">转换规则</span>
        <h3>考勤计算说明</h3>
        <ul>
          <li v-for="line in ruleLines" :key="line">{{ line }}</li>
        </ul>
      </article>
    </section>

    <section v-else class="table-card">
      <div class="table-scroll">
        <table v-if="section === 'personnel'">
          <thead>
            <tr>
              <th>姓名</th>
              <th>工号</th>
              <th>部门</th>
              <th>上级部门</th>
              <th>考勤组</th>
              <th>岗位 / 性质</th>
              <th class="actions-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td class="primary-cell">{{ row.employee_name || '—' }}</td>
              <td>{{ row.employee_no || '—' }}</td>
              <td>{{ row.department || '未分配' }}</td>
              <td>{{ row.main_department || '—' }}</td>
              <td>
                <span class="soft-pill">{{ row.attendance_group || '未设置' }}</span>
              </td>
              <td>{{ row.position || '—' }}</td>
              <td class="row-actions">
                <button type="button" @click="startEdit(row)">编辑</button>
                <button type="button" class="danger-link" @click="removeRow(row)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>

        <table v-else-if="section === 'departments'">
          <thead>
            <tr>
              <th>部门名称</th>
              <th>上级部门</th>
              <th>考勤组</th>
              <th>人员数</th>
              <th class="actions-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td class="primary-cell">{{ row.department || '—' }}</td>
              <td>{{ row.main_department || '—' }}</td>
              <td>
                <span class="soft-pill">{{ row.attendance_group || '未设置' }}</span>
              </td>
              <td>{{ row.employee_count ?? 0 }}</td>
              <td class="row-actions">
                <button type="button" @click="startEdit(row)">编辑</button>
                <button type="button" class="danger-link" @click="removeRow(row)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>

        <table v-else>
          <thead>
            <tr>
              <th>日期</th>
              <th>姓名</th>
              <th>部门</th>
              <th>班次</th>
              <th>请假小时</th>
              <th>缺勤天数</th>
              <th>迟到 / 早退 / 缺卡</th>
              <th>月份</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td class="primary-cell">{{ row.work_date || '—' }}</td>
              <td>{{ row.employee_name || '—' }}</td>
              <td>{{ row.department || '—' }}</td>
              <td>{{ row.shift_name || '—' }}</td>
              <td>{{ row.leave_hours || 0 }}</td>
              <td>{{ row.absent_days || 0 }}</td>
              <td>
                <span :class="['soft-pill', { 'warning-pill': hasAnomaly(row) }]">{{
                  anomalyText(row)
                }}</span>
              </td>
              <td>{{ row.month_label || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!rows.length" class="empty-state">
        <strong>{{ emptyTitle }}</strong>
        <span>{{ emptyDescription }}</span>
        <button v-if="isEditable" type="button" class="btn btn-primary" @click="startCreate">
          {{ section === 'personnel' ? '新增第一位人员' : '新增第一个部门' }}
        </button>
        <router-link v-else-if="conversionEnabled" class="btn btn-primary" to="/mod/sunbird-attendance-custom/convert"
          >上传考勤表</router-link
        >
      </div>

      <footer v-if="total > pageSize" class="pagination">
        <button type="button" class="btn" :disabled="page <= 1" @click="goPage(page - 1)">
          上一页
        </button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button type="button" class="btn" :disabled="page >= totalPages" @click="goPage(page + 1)">
          下一页
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
  import { computed, nextTick, reactive, ref, watch } from 'vue';
  import { apiFetch } from '@/utils/apiBase';
  import { appConfirm } from '@/utils/appDialog';

  type Section = 'personnel' | 'departments' | 'schedules' | 'records';
  type DataRow = Record<string, string | number | null | undefined>;

  const props = defineProps<{ section: Section; conversionEnabled?: boolean }>();

  let loadGeneration = 0;
  const loading = ref(false);
  const saving = ref(false);
  const error = ref('');
  const editorError = ref('');
  const rows = ref<DataRow[]>([]);
  const total = ref(0);
  const page = ref(1);
  const pageSize = 25;
  const search = ref('');
  const month = ref('');
  const months = ref<string[]>([]);
  const scheduleGroups = ref<
    Array<{ name: string; headcount?: string; shift_type?: string; lines?: string[] }>
  >([]);
  const ruleLines = ref<string[]>([]);
  const departmentNames = ref<string[]>([]);
  const editorOpen = ref(false);
  const editorDialog = ref<HTMLDialogElement | null>(null);
  watch(editorOpen, async (open) => {
    await nextTick();
    if (open && editorOpen.value) editorDialog.value?.showModal();
    else editorDialog.value?.close();
  });
  const editingId = ref<number | null>(null);

  const emptyEmployee = () => ({
    employee_name: '',
    employee_no: '',
    department: '',
    main_department: '',
    attendance_group: '',
    position: '',
    user_id: '',
  });
  const emptyDepartment = () => ({ department: '', main_department: '', attendance_group: '' });
  const employeeForm = reactive(emptyEmployee());
  const departmentForm = reactive(emptyDepartment());

  const isEditable = computed(
    () => props.section === 'personnel' || props.section === 'departments'
  );
  const pageTitle = computed(
    () =>
      ({
        personnel: '人员管理',
        departments: '部门管理',
        schedules: '排班资源',
        records: '考勤记录',
      })[props.section]
  );
  const pageDescription = computed(
    () =>
      ({
        personnel: '维护考勤名单、工号、所属部门与考勤组。',
        departments: '维护组织部门、上级部门和对应考勤组。',
        schedules: '查看人员名单中的考勤组与人数；客户模板规则在定制转换功能内维护。',
        records: '按人员、部门和月份查询导入后的逐日考勤明细。',
      })[props.section]
  );
  const searchPlaceholder = computed(
    () =>
      ({
        personnel: '搜索姓名、工号、部门或岗位',
        departments: '搜索部门、上级部门或考勤组',
        records: '搜索姓名、工号、部门或班次',
        schedules: '',
      })[props.section]
  );
  const emptyTitle = computed(() =>
    props.section === 'personnel'
      ? '暂无人员'
      : props.section === 'departments'
        ? '暂无部门'
        : '暂无考勤记录'
  );
  const emptyDescription = computed(() =>
    props.section === 'records'
      ? '当前没有符合条件的入库明细。'
      : `当前${pageTitle.value}还没有符合条件的数据。`
  );
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

  async function requestJson(url: string, init?: RequestInit) {
    const response = await apiFetch(url, init);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.success) {
      throw new Error(payload.message || payload.error || `HTTP ${response.status}`);
    }
    return payload.data;
  }

  async function loadDepartmentNames() {
    try {
      const data = await requestJson(
        '/api/mod/attendance-industry/departments?page=1&page_size=500'
      );
      departmentNames.value = (data?.items || [])
        .map((row: DataRow) => String(row.department || ''))
        .filter(Boolean);
    } catch {
      departmentNames.value = [];
    }
  }

  async function loadData(quiet = false) {
    const generation = ++loadGeneration;
    if (!quiet) loading.value = true;
    error.value = '';
    try {
      if (props.section === 'schedules') {
        const data = await requestJson('/api/mod/attendance-industry/schedules');
        if (generation !== loadGeneration) return;
        scheduleGroups.value = Array.isArray(data?.schedule_groups) ? data.schedule_groups : [];
        ruleLines.value = Array.isArray(data?.lines) ? data.lines : [];
        return;
      }
      const endpoint =
        props.section === 'personnel'
          ? 'employees'
          : props.section === 'departments'
            ? 'departments'
            : 'records';
      const query = new URLSearchParams({
        page: String(page.value),
        page_size: String(pageSize),
        search: search.value,
      });
      if (props.section === 'records' && month.value) query.set('month', month.value);
      const data = await requestJson(
        `/api/mod/attendance-industry/${endpoint}?${query.toString()}`
      );
      if (generation !== loadGeneration) return;
      rows.value = Array.isArray(data?.items) ? data.items : [];
      total.value = Number(data?.total) || 0;
      if (props.section === 'records')
        months.value = Array.isArray(data?.months) ? data.months : [];
      if (props.section === 'personnel') void loadDepartmentNames();
    } catch (cause) {
      if (generation !== loadGeneration) return;
      error.value = cause instanceof Error ? cause.message : String(cause);
      rows.value = [];
      total.value = 0;
    } finally {
      if (generation === loadGeneration) loading.value = false;
    }
  }

  function applyFilters() {
    page.value = 1;
    void loadData();
  }

  function goPage(next: number) {
    page.value = Math.min(totalPages.value, Math.max(1, next));
    void loadData();
  }

  function startCreate() {
    editingId.value = null;
    editorError.value = '';
    Object.assign(employeeForm, emptyEmployee());
    Object.assign(departmentForm, emptyDepartment());
    editorOpen.value = true;
  }

  function startEdit(row: DataRow) {
    editingId.value = Number(row.id);
    editorError.value = '';
    if (props.section === 'personnel') {
      Object.assign(employeeForm, emptyEmployee(), row);
    } else {
      Object.assign(departmentForm, emptyDepartment(), row);
    }
    editorOpen.value = true;
  }

  function cancelEdit() {
    if (saving.value) return;
    closeEditor();
  }

  function closeEditor() {
    editorOpen.value = false;
    editingId.value = null;
    editorError.value = '';
  }

  async function saveEditor() {
    if (saving.value) return;
    const entity = props.section === 'personnel' ? 'employees' : 'departments';
    const payload = props.section === 'personnel' ? { ...employeeForm } : { ...departmentForm };
    const id = editingId.value;
    saving.value = true;
    editorError.value = '';
    try {
      await requestJson(`/api/mod/attendance-industry/${entity}${id ? `/${id}` : ''}`, {
        method: id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      closeEditor();
      // 保留表格 DOM 与分页，避免刷新时列表折叠导致滚动位置归零。
      await loadData(true);
    } catch (cause) {
      editorError.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      saving.value = false;
    }
  }

  async function removeRow(row: DataRow) {
    const label =
      props.section === 'personnel'
        ? String(row.employee_name || '该人员')
        : String(row.department || '该部门');
    if (!(await appConfirm(`确定删除“${label}”吗？`, { danger: true }))) return;
    const entity = props.section === 'personnel' ? 'employees' : 'departments';
    try {
      await requestJson(`/api/mod/attendance-industry/${entity}/${row.id}`, { method: 'DELETE' });
      if (rows.value.length === 1 && page.value > 1) page.value -= 1;
      await loadData();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    }
  }

  function hasAnomaly(row: DataRow): boolean {
    return [
      'leave_hours',
      'absent_days',
      'late_count_hint',
      'early_count_hint',
      'missing_card_count',
    ].some((key) => Number(row[key]) > 0);
  }

  function anomalyText(row: DataRow): string {
    const parts: string[] = [];
    if (Number(row.late_count_hint) > 0) parts.push(`迟到 ${row.late_count_hint}`);
    if (Number(row.early_count_hint) > 0) parts.push(`早退 ${row.early_count_hint}`);
    if (Number(row.missing_card_count) > 0) parts.push(`缺卡 ${row.missing_card_count}`);
    return parts.join(' / ') || '正常';
  }

  watch(
    () => props.section,
    () => {
      page.value = 1;
      search.value = '';
      month.value = '';
      rows.value = [];
      total.value = 0;
      cancelEdit();
      void loadData();
    },
    { immediate: true }
  );
</script>

<style scoped src="./AttendanceManagementView.css"></style>
