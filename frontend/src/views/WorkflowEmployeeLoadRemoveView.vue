<template>
  <div class="page-view" id="view-workflow-employee-load-remove">
    <div class="page-content">
      <div class="page-header" style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
        <router-link :to="{ name: 'other-tools' }" class="btn btn-ghost" title="返回员工工作流管理">
          ← 员工工作流管理
        </router-link>
        <h2 style="margin: 0">加载和去除员工</h2>
      </div>

      <p v-if="!hasToken && !hasLocalApi" class="wel-alert wel-alert--warn" style="margin: 8px 0 0">
        未检测到修茈市场访问令牌且未配置远程 API 基址，已展示本地员工列表。如需拉取远程员工列表，请先在
        <router-link :to="{ name: 'model-payment' }">模型服务</router-link>
        完成修茈登录或设置 VITE_MODSTORE_API_ORIGIN。
      </p>
      <p v-else-if="!hasToken && hasLocalApi" class="wel-alert wel-alert--info" style="margin: 8px 0 0">
        当前通过本地后端 API 拉取员工列表。如需直连修茈远程 API，请在
        <router-link :to="{ name: 'model-payment' }">模型服务</router-link>
        登录或设置 VITE_MODSTORE_API_ORIGIN。
      </p>
      <p v-if="corsHint" class="wel-alert wel-alert--warn" style="margin: 8px 0 0">{{ corsHint }}</p>
      <p v-if="err" class="wel-alert wel-alert--error" style="margin: 8px 0 0">{{ err }}</p>
      <p v-if="successMsg" class="wel-alert wel-alert--ok" style="margin: 8px 0 0">{{ successMsg }}</p>

      <div class="card" style="margin-bottom: 12px">
        <h3 style="margin: 0 0 8px">任务一 · 非在岗员工管理</h3>
        <p style="margin: 0 0 8px; color: #6b7280">
          列表与 MODstore 工作台侧栏相反：<strong>不显示</strong>「编制内且已入库 catalog」的管理端在岗包；其余
          <code>listEmployees</code> 行（含 <code>v1_catalog</code>、非编制 <code>catalog</code> 等）在此维护。
        </p>
        <p style="margin: 0 0 8px; color: #6b7280">
          <strong>客户端下岗/上岗</strong>仅写入本机 localStorage（<code>{{ CLIENT_EMPLOYEE_OFFDUTY_KEY }}</code>），不修改修茈服务器数据。
          <strong>删除</strong>调用修茈 <code>DELETE /api/admin/employee-packs</code>（需管理员 JWT；编制包服务端 403）。
        </p>
        <p v-if="ctx.clientModsUiOff" style="margin: 0 0 8px; color: #6b7280">当前为原版模式：扩展相关说明仍以副窗为准。</p>

        <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px">
          <button type="button" class="btn btn-primary" :disabled="loading" @click="reload">刷新</button>
          <label style="display: inline-flex; align-items: center; gap: 6px; color: #374151">
            <input v-model="hideClientOffduty" type="checkbox" />
            隐藏「客户端已下岗」的行
          </label>
          <span v-if="apiOrigin" style="font-size: 12px; color: #9ca3af">API：{{ apiOrigin }}</span>
        </div>

        <div v-if="loading" style="padding: 16px; color: #6b7280">加载中…</div>
        <div v-else-if="!visibleRows.length" style="padding: 16px; color: #6b7280">暂无符合条件的员工包（或全部被过滤）。</div>
        <div v-else style="overflow-x: auto">
          <table class="wel-table">
            <thead>
              <tr>
                <th>名称</th>
                <th>pkg_id</th>
                <th>source</th>
                <th>编制</th>
                <th>客户端</th>
                <th style="min-width: 220px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visibleRows" :key="row.id">
                <td>{{ row.name || '—' }}</td>
                <td><code>{{ row.id }}</code></td>
                <td>{{ row.source || '—' }}</td>
                <td>{{ isPlannedDutyRosterPkgId(row.id) ? '编制内' : '非编制' }}</td>
                <td>
                  <span v-if="offdutySet.has(row.id)" class="wel-badge wel-badge--muted">已下岗（本地）</span>
                  <span v-else class="wel-badge wel-badge--ok">正常</span>
                </td>
                <td>
                  <button
                    v-if="offdutySet.has(row.id)"
                    type="button"
                    class="btn btn-sm btn-ghost"
                    @click="onClientOn(row.id)"
                  >
                    客户端上岗
                  </button>
                  <button v-else type="button" class="btn btn-sm btn-ghost" @click="onClientOff(row.id)">客户端下岗</button>
                  <button
                    type="button"
                    class="btn btn-sm btn-danger"
                    :disabled="deleteBusyId === row.id || !canServerDelete(row)"
                    :title="!canServerDelete(row) ? '编制内员工包不可从本页删除（服务端拒绝）' : ''"
                    @click="onServerDelete(row)"
                  >
                    {{ deleteBusyId === row.id ? '删除中…' : '删除' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="margin-bottom: 12px">
        <h3 style="margin: 0 0 8px">任务二 · 从平台包添加（.xcemp）</h3>
        <p style="margin: 0 0 8px; color: #6b7280">
          与工作台「↓ 下载平台包 (.xcemp)」同一产物。此处走修茈管理员入库接口
          <code>POST /api/admin/catalog</code>（需<strong>管理员</strong>市场 Token），将文件写入目录并登记
          <code>catalog_items</code>。
        </p>
        <p v-if="uploadErr" style="margin: 0 0 8px; color: #b91c1c">{{ uploadErr }}</p>
        <div style="display: grid; gap: 10px; max-width: 520px">
          <label> pkg_id（须与 manifest 内 id 一致）<input v-model="uploadPkgId" class="wel-input" type="text" placeholder="如 my-employee-pack" /> </label>
          <label> version <input v-model="uploadVersion" class="wel-input" type="text" placeholder="如 1.0.0" /> </label>
          <label> 显示名称 <input v-model="uploadName" class="wel-input" type="text" placeholder="如 我的员工包" /> </label>
          <label>
            .xcemp 文件
            <input type="file" accept=".xcemp,.zip,.xcmod" @change="onFile" />
          </label>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="uploadBusy || !hasToken || !uploadFile"
            @click="submitUpload"
          >
            {{ uploadBusy ? '上传中…' : '上传并登记' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowModsRuntimeContext } from '@/composables/useWorkflowModsRuntimeContext'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { isMgmtOnDutyRow, isPlannedDutyRosterPkgId } from '@/constants/modstoreDutyRosterIds'
import { buildModWorkflowPanelMeta, type ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'
import {
  hasModstoreMarketToken,
  modstoreAdminUploadCatalog,
  modstoreDeleteEmployeePack,
  modstoreListEmployees,
  resolveModstoreApiOrigin,
  type ModstoreEmployeeRow,
} from '@/api/modstoreBridge'
import {
  CLIENT_EMPLOYEE_OFFDUTY_KEY,
  loadClientOffdutyIds,
  setClientOffduty,
} from '@/utils/clientEmployeeOffduty'

const { ctx } = useWorkflowModsRuntimeContext()
const modsStore = useModsStore()
const wfEmpStore = useWorkflowAiEmployeesStore()
const { enabled: wfEmpEnabled } = storeToRefs(wfEmpStore)

const loading = ref(false)
const err = ref('')
const corsHint = ref('')
const successMsg = ref('')
const rows = ref<ModstoreEmployeeRow[]>([])
const hideClientOffduty = ref(false)
const offdutySet = ref<Set<string>>(new Set())
const deleteBusyId = ref('')
const uploadBusy = ref(false)
const uploadErr = ref('')
const uploadPkgId = ref('')
const uploadVersion = ref('1.0.0')
const uploadName = ref('')
const uploadFile = ref<File | null>(null)

const hasToken = computed(() => hasModstoreMarketToken())
const hasLocalApi = computed(() => !resolveModstoreApiOrigin())
const apiOrigin = computed(() => resolveModstoreApiOrigin())

function buildLocalRows(): ModstoreEmployeeRow[] {
  const out: ModstoreEmployeeRow[] = []
  const seen = new Set<string>()
  const modMeta = buildModWorkflowPanelMeta(modsStore.modsForUi as ModWithWorkflowEmployees[])

  for (const empId of Object.keys(wfEmpEnabled.value)) {
    if (seen.has(empId)) continue
    seen.add(empId)
    const meta = modMeta[empId]
    const label = meta?.title
      ? meta.title.replace(/^工作流 ·\s*/, '').trim()
      : empId
    out.push({ id: empId, name: label, source: 'local' })
  }

  for (const [id, meta] of Object.entries(modMeta)) {
    if (seen.has(id)) continue
    seen.add(id)
    const label = meta.title?.replace(/^工作流 ·\s*/, '').trim() || id
    out.push({ id, name: label, source: 'mod_manifest' })
  }

  return out
}

function mergeRows(local: ModstoreEmployeeRow[], remote: ModstoreEmployeeRow[]): ModstoreEmployeeRow[] {
  const seen = new Set(local.map((r) => r.id))
  const out = [...local]
  for (const r of remote) {
    if (seen.has(r.id)) continue
    seen.add(r.id)
    out.push(r)
  }
  return out
}

const filteredByDuty = computed(() => rows.value.filter((r) => !isMgmtOnDutyRow(r)))

const visibleRows = computed(() => {
  const base = filteredByDuty.value
  if (!hideClientOffduty.value) return base
  return base.filter((r) => !offdutySet.value.has(r.id))
})

function syncOffduty() {
  offdutySet.value = loadClientOffdutyIds()
}

function canServerDelete(row: ModstoreEmployeeRow): boolean {
  if (isPlannedDutyRosterPkgId(row.id)) return false
  if (!hasToken.value) return false
  return true
}

async function reload() {
  err.value = ''
  corsHint.value = ''
  successMsg.value = ''
  const local = buildLocalRows()

  if (!hasToken.value) {
    rows.value = local
    return
  }
  loading.value = true
  try {
    const remote = await modstoreListEmployees()
    rows.value = mergeRows(local, remote)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    err.value = msg
    rows.value = local
    if (/fetch|Failed to fetch|NetworkError|load failed/i.test(msg)) {
      corsHint.value =
        '若控制台为 CORS 错误：请让运维对修茈域配置允许当前 XCmax 源，或设置 VITE_MODSTORE_API_ORIGIN 指向经 Nginx 同源反代后的 API。'
    }
  } finally {
    loading.value = false
  }
}

function onClientOff(id: string) {
  setClientOffduty(id, true)
  syncOffduty()
  successMsg.value = '已标记客户端下岗（仅本机）。'
}

function onClientOn(id: string) {
  setClientOffduty(id, false)
  syncOffduty()
  successMsg.value = '已恢复客户端上岗（仅本机）。'
}

async function onServerDelete(row: ModstoreEmployeeRow) {
  if (!canServerDelete(row)) return
  if (!window.confirm(`确定从修茈服务器删除员工包「${row.name || row.id}」？此操作不可撤销（编制包将被服务端拒绝）。`)) return
  deleteBusyId.value = row.id
  err.value = ''
  successMsg.value = ''
  try {
    await modstoreDeleteEmployeePack(row.id)
    successMsg.value = `已删除 ${row.id}`
    await reload()
  } catch (e: unknown) {
    err.value = e instanceof Error ? e.message : String(e)
  } finally {
    deleteBusyId.value = ''
  }
}

function onFile(ev: Event) {
  uploadErr.value = ''
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  uploadFile.value = f || null
  if (!f) return
  if (!uploadName.value.trim()) {
    uploadName.value = f.name.replace(/\.(xcemp|zip|xcmod)$/i, '') || f.name
  }
}

async function submitUpload() {
  uploadErr.value = ''
  successMsg.value = ''
  if (!uploadFile.value) {
    uploadErr.value = '请选择文件'
    return
  }
  if (!uploadPkgId.value.trim() || !uploadVersion.value.trim() || !uploadName.value.trim()) {
    uploadErr.value = '请填写 pkg_id、version 与显示名称（可与 manifest 核对）。'
    return
  }
  uploadBusy.value = true
  try {
    await modstoreAdminUploadCatalog({
      pkgId: uploadPkgId.value.trim(),
      version: uploadVersion.value.trim(),
      name: uploadName.value.trim(),
      artifact: 'employee_pack',
      file: uploadFile.value,
    })
    successMsg.value = '上传并登记成功。'
    uploadFile.value = null
    await reload()
  } catch (e: unknown) {
    uploadErr.value = e instanceof Error ? e.message : String(e)
  } finally {
    uploadBusy.value = false
  }
}

onMounted(() => {
  syncOffduty()
  void reload()
})
</script>

<style scoped>
.wel-alert {
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 14px;
}
.wel-alert--warn {
  background: #fffbeb;
  border: 1px solid #fcd34d;
  color: #92400e;
}
.wel-alert--error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}
.wel-alert--ok {
  background: #ecfdf5;
  border: 1px solid #6ee7b7;
  color: #065f46;
}
.wel-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
.wel-table th,
.wel-table td {
  border: 1px solid #e5e7eb;
  padding: 8px 10px;
  text-align: left;
  vertical-align: middle;
}
.wel-table th {
  background: #f9fafb;
  font-weight: 600;
}
.wel-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
}
.wel-badge--muted {
  background: #f3f4f6;
  color: #6b7280;
}
.wel-badge--ok {
  background: #dcfce7;
  color: #166534;
}
.wel-input {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  box-sizing: border-box;
}
.btn-sm {
  font-size: 13px;
  padding: 4px 10px;
  margin-right: 6px;
}
.btn-danger {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
