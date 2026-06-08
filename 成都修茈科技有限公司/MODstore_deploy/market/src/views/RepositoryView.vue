<template>
  <div class="repo-page">
    <div class="page-header">
      <h1 class="page-title">Mod 能力货架</h1>
      <div class="industry-toolbar">
        <label class="label industry-toolbar-label">默认行业</label>
        <select v-model="authoringIndustryId" class="input industry-select" @change="persistAuthoringIndustry">
          <option v-for="p in industryPresets" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary" @click="showCreate = true">新建 Mod</button>
        <label class="btn">
          导入包（.zip / .xcmod）
          <input type="file" accept=".zip,.xcmod,.xcemp" class="hidden-input" @change="onImport" />
        </label>
        <button
          type="button"
          class="btn btn-secondary"
          title="使用已配置的默认大模型生成 manifest + 脚手架并导入（见 LLM 设置）"
          @click="openScaffoldModal"
        >
          AI 生成脚手架
        </button>
        <div class="header-more-wrap">
          <button
            type="button"
            class="btn btn-sm"
            aria-haspopup="menu"
            :aria-expanded="headerMoreOpen"
            @click.stop="headerMoreOpen = !headerMoreOpen"
          >
            更多
          </button>
          <div v-if="headerMoreOpen" class="header-more-menu" role="menu" @click.stop>
            <button
              type="button"
              class="header-more-item header-more-item--danger"
              role="menuitem"
              :disabled="purgeLibraryBusy"
              title="删除当前账号 Mod 能力货架中的全部包（需登录），并清除本页提示与「带入员工制作」预填缓存；不可恢复"
              @click="onPurgeFromMenu"
            >
              {{ purgeLibraryBusy ? '清空中…' : '一键清理' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="message" :class="['flash', messageOk ? 'flash-ok' : 'flash-err']">{{ message }}</div>

    <section class="repo-shelf-filters" aria-label="能力货架筛选">
      <input
        v-model.trim="shelfQ"
        class="input shelf-search"
        type="search"
        placeholder="搜索名称、ID、描述…"
      />
      <select v-model="shelfIndustry" class="input shelf-select">
        <option value="">全部行业</option>
        <option v-for="p in industryPresets" :key="'shelf-' + p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <select v-model="shelfStatus" class="input shelf-select">
        <option value="">全部状态</option>
        <option value="primary">主扩展</option>
        <option value="bundle">组合包</option>
        <option value="mod">普通 Mod</option>
      </select>
      <select v-model="shelfVersion" class="input shelf-select">
        <option value="">全部版本</option>
        <option v-for="v in versionOptions" :key="v" :value="v">v{{ v }}</option>
      </select>
      <select v-model="shelfTest" class="input shelf-select">
        <option value="">全部测试结果</option>
        <option value="pass">通过</option>
        <option value="fix">待修正</option>
      </select>
      <select v-model="shelfScope" class="input shelf-select">
        <option value="">全部企业授权</option>
        <option value="assigned">已分配企业</option>
        <option value="unassigned">未配置企业授权</option>
      </select>
      <button
        v-if="hasActiveShelfFilters"
        type="button"
        class="btn btn-sm shelf-clear-btn"
        @click="clearShelfFilters"
      >
        清空筛选
      </button>
    </section>
    <p class="repo-shelf-meta">
      展示 {{ filteredMods.length }} / {{ mods.length }} 个能力
      <template v-if="usageLoadError"> · 启用范围未读取：{{ usageLoadError }}</template>
    </p>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="filteredMods.length" class="mods-grid">
      <div v-for="m in filteredMods" :key="m.id" class="mod-card">
        <div class="mod-card-top">
          <div class="mod-card-badges">
            <span class="badge badge-artifact" :class="'badge-artifact--' + (m.artifact || 'mod')">{{ artifactLabel(m.artifact) }}</span>
            <span class="badge" :class="m.ok ? 'badge-ok' : 'badge-warn'">{{ m.ok ? '通过' : '待修正' }}</span>
            <span v-if="m.primary" class="badge badge-primary">主扩展</span>
            <span class="badge badge-scope">{{ modIndustryLabel(m) }}</span>
          </div>
          <div class="mod-card-more-wrap">
            <button
              type="button"
              class="mod-card-more-btn"
              aria-haspopup="menu"
              :aria-expanded="openCardMenuId === m.id"
              aria-label="更多操作"
              @click.stop="toggleCardMenu(m.id)"
            >
              ⋯
            </button>
            <div v-if="openCardMenuId === m.id" class="mod-card-menu" role="menu" @click.stop>
              <button
                type="button"
                class="mod-card-menu-item mod-card-menu-item--danger"
                role="menuitem"
                :disabled="deleteModBusy === modIdForDeleteApi(m)"
                @click="onDeleteFromCardMenu(m)"
              >
                {{ deleteModBusy === modIdForDeleteApi(m) ? '删除中…' : '删除 Mod' }}
              </button>
            </div>
          </div>
        </div>
        <p v-if="isBundle(m)" class="bundle-hint">组合包：子项见 manifest.bundle</p>
        <h3 class="mod-card-name">{{ m.name || m.id }}</h3>
        <p v-if="getBlurb(m)" class="mod-card-blurb">{{ getBlurb(m) }}</p>
        <p v-else class="mod-card-blurb mod-card-blurb--muted">暂无简介，可在制作页补充 description 或 library_blurb</p>
        <div class="mod-card-id">{{ m.id }} · v{{ m.version || '?' }}</div>
        <div class="mod-card-meta">
          <span v-if="formatUpdatedAt(m.updated_at)" class="mod-card-meta-item">更新 {{ formatUpdatedAt(m.updated_at) }}</span>
          <span v-if="getUsageScene(m)" class="mod-card-meta-item mod-card-meta-item--scene" :title="getUsageScene(m)">
            场景：{{ getUsageScene(m) }}
          </span>
        </div>
        <div class="mod-card-scope" :class="{ 'mod-card-scope--muted': !usageNames(m.id).length && !usageLoadError }">
          {{ usageText(m.id) }}
        </div>
        <div v-if="m.warnings?.length" class="mod-card-warn">{{ m.warnings[0] }}{{ m.warnings.length > 1 ? ' …' : '' }}</div>
        <div v-if="m.error" class="mod-card-warn">{{ m.error }}</div>
        <div v-if="m.workflow_employees?.length" class="wf-emp-block">
          <div class="wf-emp-title">manifest 中的工作流声明（workflow_employees）</div>
          <div class="wf-emp-actions">
            <div
              v-for="(e, idx) in m.workflow_employees"
              :key="(e.id || '') + '-' + idx"
              class="wf-emp-line"
            >
              <button
                type="button"
                class="btn btn-sm btn-ghost"
                title="打开员工制作页并预填该条声明（不会自动写入本地包目录）。也可点右侧「一键登记」直接写入 /v1/packages；或完成向导后手动上传登记。"
                @click="goEmployeePrefill(m.id, e, Number(idx))"
              >
                带入员工制作：{{ e.label || e.id || '未命名' }}
              </button>
              <button
                type="button"
                class="btn btn-sm btn-primary"
                :disabled="registerBusy === registerKey(m.id, idx)"
                title="从该条声明生成最小 employee_pack 并通过沙盒审核后写入本地 /v1/packages（需已登录）。与「带入员工制作」二选一或组合使用；同包 id+version 再次登记会覆盖。"
                @click="registerWorkflowToCatalog(m.id, idx)"
              >
                {{ registerBusy === registerKey(m.id, idx) ? '登记中…' : '一键登记' }}
              </button>
            </div>
          </div>
        </div>
        <div class="mod-card-actions">
          <button class="btn btn-sm" @click="viewMod(m.id)">制作 / 编辑</button>
          <button
            type="button"
            class="btn btn-sm btn-secondary"
            title="把该 Mod ID 自动带入沙箱页，并指向线上 FHD 沙盒宿主"
            @click="testModInSandbox(m.id)"
          >
            沙箱测试
          </button>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">
      <p>{{ mods.length ? '没有符合筛选的能力' : '库中暂无扩展包' }}</p>
      <p v-if="mods.length && hasActiveShelfFilters" class="empty-hint">
        试试
        <button type="button" class="empty-link" @click="clearShelfFilters">清空筛选</button>
        或修改搜索关键词
      </p>
      <p v-else class="empty-hint">{{ mods.length ? '调整搜索或筛选条件' : '新建或导入 Mod 开始' }}</p>
    </div>

    <!-- AI 脚手架 -->
    <div v-if="showScaffold" class="modal-overlay" @click.self="showScaffold = false">
      <div class="modal modal-wide">
        <h2 class="modal-title">AI 生成 Mod 脚手架</h2>
        <div class="form-group">
          <label class="label">目标行业</label>
          <select v-model="scaffoldIndustryId" class="input industry-select">
            <option v-for="p in industryPresets" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label class="label">描述</label>
          <textarea
            v-model="scaffoldBrief"
            class="input textarea"
            rows="4"
            placeholder="简要描述 Mod 用途"
          />
        </div>
        <div class="form-group">
          <label class="label">ID（可选）</label>
          <input v-model="scaffoldIdHint" class="input" placeholder="my-mod-id" />
        </div>
        <label class="checkbox-line">
          <input v-model="scaffoldReplace" type="checkbox" />
          若 id 已存在则覆盖导入
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" :disabled="scaffoldBusy" @click="showScaffold = false">取消</button>
          <button class="btn btn-primary" type="button" :disabled="scaffoldBusy" @click="submitScaffold">
            {{ scaffoldBusy ? '生成中…' : '生成并导入' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新建 Mod 弹窗 -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <h2 class="modal-title">新建 Mod</h2>
        <div class="form-group">
          <label class="label">名称</label>
          <input v-model="createName" class="input" placeholder="显示名称" />
        </div>
        <div class="form-group">
          <label class="label">目标行业</label>
          <select v-model="createIndustryId" class="input">
            <option v-for="p in industryPresets" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="showCreate = false">取消</button>
          <button class="btn btn-primary" @click="submitCreate">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { listIndustryPresets } from '../constants/industryPresets'

const LS_AUTHORING_INDUSTRY = 'modstore_authoring_industry_id'

const router = useRouter()
interface ModRow {
  id: string
  name?: string
  version?: string
  artifact?: string
  ok?: boolean
  primary?: boolean
  warnings?: string[]
  error?: string
  workflow_employees?: Array<Record<string, any>>
  path?: string
  description?: string
  library_blurb?: string
  updated_at?: string
  usage_scene?: string
  [key: string]: any
}

const mods = ref<ModRow[]>([])
const loading = ref(true)
const message = ref('')
const messageOk = ref(true)
const industryPresets = listIndustryPresets()
const authoringIndustryId = ref(
  (typeof localStorage !== 'undefined' && localStorage.getItem(LS_AUTHORING_INDUSTRY)) || '通用',
)
const createIndustryId = ref(authoringIndustryId.value)
const showCreate = ref(false)
const createName = ref('')

function persistAuthoringIndustry() {
  try {
    localStorage.setItem(LS_AUTHORING_INDUSTRY, authoringIndustryId.value)
  } catch {
    /* ignore */
  }
  createIndustryId.value = authoringIndustryId.value
}
const showScaffold = ref(false)
const scaffoldBrief = ref('')
const scaffoldIndustryId = ref(authoringIndustryId.value)
const scaffoldIdHint = ref('')
const scaffoldReplace = ref(true)
const scaffoldBusy = ref(false)
/** `${modId}:${workflowIndex}` 登记中 */
const registerBusy = ref('')
/** 正在删除的 manifest.id */
const deleteModBusy = ref('')
/** 一键清理：批量删库进行中 */
const purgeLibraryBusy = ref(false)
const headerMoreOpen = ref(false)
const openCardMenuId = ref('')
const shelfQ = ref('')
const shelfIndustry = ref('')
const shelfStatus = ref('')
const shelfVersion = ref('')
const shelfTest = ref('')
const shelfScope = ref('')
const usageByModId = ref<Record<string, string[]>>({})
const usageLoadError = ref('')

const PREFILL_KEY = 'modstore_employee_prefill'

interface EnterpriseUserRow {
  id?: string | number
  username?: string
  email?: string
  mod_ids?: string[]
}

const versionOptions = computed(() => {
  const set = new Set<string>()
  for (const m of mods.value) {
    const v = String(m.version || '').trim()
    if (v) set.add(v)
  }
  return Array.from(set).sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
})

const hasActiveShelfFilters = computed(
  () =>
    !!(
      shelfQ.value.trim() ||
      shelfIndustry.value ||
      shelfStatus.value ||
      shelfVersion.value ||
      shelfTest.value ||
      shelfScope.value
    ),
)

const filteredMods = computed(() => {
  const q = shelfQ.value.trim().toLowerCase()
  return mods.value.filter((m) => {
    if (q) {
      const hay = [m.id, m.name, m.description, m.library_blurb]
        .map((x) => String(x || '').toLowerCase())
        .join('\n')
      if (!hay.includes(q)) return false
    }
    if (shelfIndustry.value && modIndustryId(m) !== shelfIndustry.value) return false
    if (shelfStatus.value && modShelfStatus(m) !== shelfStatus.value) return false
    if (shelfVersion.value && String(m.version || '').trim() !== shelfVersion.value) return false
    if (shelfTest.value === 'pass' && !m.ok) return false
    if (shelfTest.value === 'fix' && m.ok) return false
    if (shelfScope.value === 'assigned' && usageNames(m.id).length === 0) return false
    if (shelfScope.value === 'unassigned' && usageNames(m.id).length > 0) return false
    return true
  })
})

function modIndustryId(m: ModRow): string {
  const industry = m?.industry
  if (industry && typeof industry === 'object') {
    const id = String((industry as Record<string, any>).id || '').trim()
    if (id) return id
    const name = String((industry as Record<string, any>).name || '').trim()
    if (name) return name
  }
  if (typeof industry === 'string' && industry.trim()) return industry.trim()
  return String(m?.industry_id || '通用').trim() || '通用'
}

function modIndustryLabel(m: ModRow): string {
  const id = modIndustryId(m)
  return industryPresets.find((p) => p.id === id)?.name || id
}

function modShelfStatus(m: ModRow): string {
  if (m.primary) return 'primary'
  if (isBundle(m)) return 'bundle'
  return 'mod'
}

function usageNames(modId: string): string[] {
  return usageByModId.value[String(modId || '').trim()] || []
}

function usageText(modId: string): string {
  const names = usageNames(modId)
  if (!names.length) {
    return usageLoadError.value ? '企业授权：未读取' : '企业授权：未配置（当前账号可编辑，未分配给企业）'
  }
  const preview = names.slice(0, 3).join('、')
  const detail = names.length > 3 ? `${names.length} 家企业（${preview}…）` : `${names.length} 家企业（${preview}）`
  return `企业授权：${detail}`
}

function clearShelfFilters() {
  shelfQ.value = ''
  shelfIndustry.value = ''
  shelfStatus.value = ''
  shelfVersion.value = ''
  shelfTest.value = ''
  shelfScope.value = ''
}

function closeFloatingMenus() {
  headerMoreOpen.value = false
  openCardMenuId.value = ''
}

function toggleCardMenu(modId: string) {
  const id = String(modId || '').trim()
  openCardMenuId.value = openCardMenuId.value === id ? '' : id
  headerMoreOpen.value = false
}

function onDocumentPointerDown(ev: PointerEvent) {
  const t = ev.target
  if (t instanceof Element && t.closest('.header-more-wrap, .mod-card-more-wrap')) return
  closeFloatingMenus()
}

async function onPurgeFromMenu() {
  headerMoreOpen.value = false
  await purgeRepoLibraryAndLocalState()
}

async function onDeleteFromCardMenu(m: ModRow) {
  openCardMenuId.value = ''
  await deleteModFromLibrary(m)
}

function formatUpdatedAt(raw: string | undefined): string {
  const s = String(raw || '').trim()
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 14 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' })
}

function getUsageScene(m: ModRow): string {
  if (!m || typeof m !== 'object') return ''
  const scene = typeof m.usage_scene === 'string' ? m.usage_scene.trim() : ''
  if (scene) return scene
  const wf = m.workflow_employees
  if (Array.isArray(wf) && wf.length) {
    const e0 = wf[0]
    const label = e0 && typeof e0 === 'object' ? String(e0.label || e0.id || '').trim() : ''
    if (label) return `工作流员工：${label}`
  }
  if (m.primary) return '主扩展 / 宿主壳层'
  if (isBundle(m)) return '组合包 manifest.bundle'
  return '沙箱 / 制作页'
}

/** 由显示名生成 manifest / 目录 id（与后端 create_mod 约定一致） */
function modIdFromDisplayName(name: string): string {
  const raw = String(name || '')
    .trim()
    .toLowerCase()
  let x = raw.replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '')
  if (!x) {
    x = `mod-${Date.now().toString(36)}`
  }
  if (!/^[a-z]/.test(x)) {
    x = `m-${x.replace(/[^a-z0-9-]/g, '')}`.replace(/-+/g, '-').replace(/^-|-$/g, '')
  }
  if (!x || !/^[a-z]/.test(x)) {
    x = `mod-${Date.now().toString(36)}`
  }
  return x.slice(0, 128)
}

function isCreateModConflictError(e: unknown): boolean {
  const msg = (e as { message?: string })?.message || String(e)
  return msg.includes('已存在') || msg.includes('409') || /FileExistsError/i.test(msg)
}

function flash(msg: string, ok = true) {
  message.value = msg
  messageOk.value = ok
  setTimeout(() => { message.value = '' }, 5000)
}

/** 磁盘目录末段名（仅用于提示文案；删除 API 须用 manifest id） */
function libraryFolderForDeleteApi(m: ModRow | null | undefined): string {
  if (!m || typeof m !== 'object') return ''
  const rawPath = typeof m.path === 'string' ? m.path.trim() : ''
  if (rawPath) {
    const norm = rawPath.replace(/\\/g, '/').replace(/\/+$/, '')
    const seg = norm.split('/').filter(Boolean).pop()
    if (seg) return seg
  }
  return String(m.id || '').trim()
}

/** DELETE /api/mods/:id 须传 manifest.id（与账号 user_mod 一致）；服务端再解析真实目录 */
function modIdForDeleteApi(m: ModRow | null | undefined): string {
  if (!m || typeof m !== 'object') return ''
  const mid = String(m.id || '').trim()
  if (mid) return mid
  return libraryFolderForDeleteApi(m)
}

function clearRepoPageLocalOnly() {
  message.value = ''
  try {
    sessionStorage.removeItem(PREFILL_KEY)
  } catch {
    /* ignore */
  }
  showCreate.value = false
  createName.value = ''
  showScaffold.value = false
  scaffoldBrief.value = ''
  scaffoldIdHint.value = ''
}

/** 清空源码库：管理员一键调用后端原子接口，避免前端循环单条 DELETE 因 list 缓存 /
 *  user_mods 关联残留导致「老是删不完」。 */
async function purgeRepoLibraryAndLocalState() {
  if (purgeLibraryBusy.value) return
  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录后再使用一键清理（将删除账号下全部 Mod）', false)
    return
  }

  const list = Array.isArray(mods.value) ? mods.value : []
  const visibleCount = list.length
  const primaryCount = list.filter((m) => m && m.primary).length
  const primaryHint =
    primaryCount > 0
      ? `\n\n其中有 ${primaryCount} 个包在 manifest 中标记为主扩展（primary），删除后请确认 XCAGI / 宿主侧不再依赖对应 id。`
      : ''

  if (
    !window.confirm(
      `确定一键重置 Mod 能力货架？\n` +
        `将原子地：删除 library/ 下全部 mod 目录（不只你账号下的）+ 截断 user_mods 关联表。当前可见 ${visibleCount} 个；若有「鬼仓」目录或历史用户残留也会一并清掉。${primaryHint}\n\n` +
        `同时清除本页提示与员工制作预填缓存。不可恢复。`,
    )
  ) {
    return
  }

  purgeLibraryBusy.value = true
  clearRepoPageLocalOnly()
  try {
    const res: any = await api.adminPurgeAllMods()
    const removed = Number(res?.removed_dir_count || 0)
    const removedRows = Number(res?.removed_user_mod_rows || 0)
    flash(`已清空能力货架：删除 ${removed} 个目录，截断 user_mods ${removedRows} 行`, true)
  } catch (e: any) {
    flash(`一键清空失败：${e?.message || String(e)}`, false)
  } finally {
    purgeLibraryBusy.value = false
    await load({ cacheBust: true })
  }
}

async function deleteModFromLibrary(m: ModRow) {
  const folder = m && typeof m === 'object' ? modIdForDeleteApi(m) : ''
  const folderSeg = m && typeof m === 'object' ? libraryFolderForDeleteApi(m) : ''
  const displayId = m && typeof m === 'object' ? String(m.id || '').trim() : ''
  if (!folder) return
  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录后再删除 Mod', false)
    return
  }
  const label = (m.name && String(m.name).trim()) || displayId || folder
  const prim = m.primary
    ? '\n\n注意：该包在 manifest 中标记为主扩展（primary），删除后请确认 XCAGI / 宿主侧不再依赖该 id。'
    : ''
  const idNote =
    displayId && folderSeg && displayId !== folderSeg
      ? `（manifest id：${displayId}；目录名：${folderSeg}）`
      : `（${folder}）`
  if (
    !window.confirm(
      `确定从 Mod 能力货架删除「${label}」${idNote}？\n本地库目录将整包删除，且会从你的账号关联中移除。此操作不可恢复。${prim}`,
    )
  ) {
    return
  }
  deleteModBusy.value = folder
  try {
    await api.deleteMod(folder)
    flash(`已删除 Mod 目录：${folder}`, true)
    await load({ cacheBust: true })
    if (Array.isArray(mods.value) && mods.value.some((row) => modIdForDeleteApi(row) === folder)) {
      flash(`删除已返回成功，但列表仍包含「${folder}」；请强制刷新或检查 GET /api/mods 是否被缓存。`, false)
    }
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    deleteModBusy.value = ''
  }
}

function getBlurb(m: ModRow): string {
  if (!m || typeof m !== 'object') return ''
  const b = typeof m.library_blurb === 'string' ? m.library_blurb.trim() : ''
  if (b) return b
  const d = typeof m.description === 'string' ? m.description.trim() : ''
  if (!d) return ''
  const one = d.replace(/\s+/g, ' ')
  return one.length > 120 ? `${one.slice(0, 117)}…` : one
}

function artifactLabel(a: string | undefined): string {
  const x = (a || 'mod').toLowerCase()
  if (x === 'employee_pack') return '员工包'
  if (x === 'bundle') return '组合包'
  return 'Mod'
}

function isBundle(m: ModRow): boolean {
  return (m?.artifact || 'mod').toLowerCase() === 'bundle'
}

function viewMod(id: string) {
  router.push({ name: 'mod-authoring', params: { modId: id } })
}

function testModInSandbox(id: string) {
  const modId = String(id || '').trim()
  if (!modId) {
    flash('该 Mod 缺少 id，无法带入沙箱测试', false)
    return
  }
  router.push({ name: 'sandbox', query: { modId, host: '/sandbox', autoPush: '1' } })
}

function registerKey(modId: string, workflowIndex: number): string {
  return `${modId}:${workflowIndex}`
}

async function registerWorkflowToCatalog(modId: string, workflowIndex: number) {
  if (!localStorage.getItem('modstore_token')) {
    flash('请先登录工作台后再一键登记到本地仓库', false)
    return
  }
  const k = registerKey(modId, workflowIndex)
  registerBusy.value = k
  try {
    const res = await api.registerWorkflowEmployeeCatalog(modId, workflowIndex)
    const pkg = res?.package
    const pid = pkg?.id || ''
    const ver = pkg?.version || ''
    flash(
      pid && ver
        ? `已登记到本地仓库：${pid} @ ${ver}（员工制作页「已登记员工包」可见）`
        : '已登记到本地仓库（/v1/packages）',
      true,
    )
  } catch (err) {
    flash((err as Error)?.message || String(err), false)
  } finally {
    registerBusy.value = ''
  }
}

function goEmployeePrefill(modId: string, emp: Record<string, any>, workflowIndex = 0) {
  const label = (emp && (emp.label || emp.id)) || '员工'
  const sum = typeof emp?.panel_summary === 'string' ? emp.panel_summary.trim() : ''
  const desc = sum
    ? `声明摘要：${sum}\n来源 Mod：${modId}（manifest.workflow_employees[${workflowIndex}]）。已带入员工制作页预填；也可在 Mod 能力货架对该条点「一键登记」直接写入 /v1/packages，或完成向导后手动登记。`
    : `来自 Mod「${modId}」的 workflow_employees[${workflowIndex}] 声明。已带入员工制作页预填；也可在能力货架「一键登记」或完成向导后登记到 /v1/packages。`
  try {
    sessionStorage.setItem(
      PREFILL_KEY,
      JSON.stringify({
        modId,
        workflowIndex,
        workflowEmployee: emp && typeof emp === 'object' ? emp : {},
        name: String(label).slice(0, 200),
        description: desc.slice(0, 4000),
      }),
    )
  } catch {
    /* ignore */
  }
  router.push({ name: 'workbench-unified', query: { focus: 'employee' } })
}

function openScaffoldModal() {
  scaffoldIndustryId.value = authoringIndustryId.value
  showScaffold.value = true
}

async function submitScaffold() {
  let brief = scaffoldBrief.value.trim()
  if (brief.length < 3) {
    flash('请至少写几句描述', false)
    return
  }
  const industryId = String(scaffoldIndustryId.value || '通用').trim() || '通用'
  if (industryId === '通用') {
    flash('请先选择目标行业（勿用「通用」）', false)
    return
  }
  const preset = industryPresets.find((p) => p.id === industryId) || industryPresets[0]
  if (preset && !brief.includes('目标行业')) {
    brief = `【目标行业：${preset.name}（${preset.id}）】${preset.scenario}\n\n${brief}`
  }
  persistAuthoringIndustry()
  authoringIndustryId.value = industryId
  scaffoldBusy.value = true
  try {
    const res = await api.modAiScaffold(
      brief,
      scaffoldIdHint.value.trim(),
      scaffoldReplace.value,
      industryId,
    )
    flash(`已生成并导入 ${res.id}`)
    showScaffold.value = false
    scaffoldBrief.value = ''
    scaffoldIdHint.value = ''
    await load()
    router.push({ name: 'mod-authoring', params: { modId: res.id } })
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  } finally {
    scaffoldBusy.value = false
  }
}

async function load(opts?: { cacheBust?: boolean }) {
  loading.value = true
  try {
    const res = await api.listMods(!!opts?.cacheBust)
    mods.value = Array.isArray(res?.data) ? res.data : []
  } catch (e) {
    flash('加载 Mod 库失败: ' + ((e as Error)?.message || String(e)), false)
    mods.value = []
  } finally {
    loading.value = false
  }
}

async function loadEnterpriseUsage() {
  usageLoadError.value = ''
  try {
    const res: any = await api.adminListUsers(200, 0, true)
    const rows: EnterpriseUserRow[] = Array.isArray(res?.users)
      ? res.users
      : Array.isArray(res?.data?.users)
        ? res.data.users
        : []
    const next: Record<string, string[]> = {}
    for (const user of rows) {
      const label = String(user.username || user.email || user.id || '').trim()
      for (const mid of user.mod_ids || []) {
        const id = String(mid || '').trim()
        if (!id) continue
        if (!next[id]) next[id] = []
        if (label) next[id].push(label)
      }
    }
    usageByModId.value = next
  } catch (e) {
    usageByModId.value = {}
    usageLoadError.value = (e as Error)?.message || String(e)
  }
}

async function submitCreate() {
  const displayName = createName.value.trim()
  if (!displayName) {
    flash('请填写名称', false)
    return
  }
  const baseId = modIdFromDisplayName(displayName)
  for (let i = 0; i < 30; i++) {
    const candidate = i === 0 ? baseId : `${baseId}-${i + 1}`.slice(0, 128)
    try {
      const industryId = String(createIndustryId.value || authoringIndustryId.value || '通用').trim()
      const res = await api.createMod(candidate, displayName, industryId)
      const newId = res.id
      showCreate.value = false
      createName.value = ''
      flash(`已创建 ${newId}`)
      await load()
      router.push({ name: 'mod-authoring', params: { modId: newId } })
      return
    } catch (e: unknown) {
      if (isCreateModConflictError(e)) continue
      flash((e as Error)?.message || String(e), false)
      return
    }
  }
  flash('无法生成可用目录名（重试次数过多）', false)
}

async function onImport(ev: Event) {
  const input = ev.target as HTMLInputElement | null
  const f = input?.files?.[0]
  if (input) input.value = ''
  if (!f) return
  try {
    const res = await api.importZIP(f, true)
    flash(`已导入 ${res.id}`)
    await load()
  } catch (e) {
    flash((e as Error)?.message || String(e), false)
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  void load()
  void loadEnterpriseUsage()
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})
</script>

<style scoped>
.repo-page {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: var(--page-pad-y) var(--layout-pad-x);
  box-sizing: border-box;
}

.industry-toolbar {
  margin-bottom: 1.25rem;
  padding: 1rem 1.1rem;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(18, 22, 32, 0.72);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.industry-toolbar-label {
  display: block;
  margin-bottom: 0.35rem;
}

.industry-select {
  max-width: 520px;
  width: 100%;
  cursor: pointer;
  color-scheme: dark;
  appearance: none;
  -webkit-appearance: none;
  padding-right: 2.35rem;
  background-color: rgba(10, 12, 18, 0.92);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23cbd5e1' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.7rem center;
  background-size: 1rem;
}

.industry-select option {
  background-color: #141820;
  color: #f1f5f9;
  padding: 0.45rem 0.65rem;
}

.industry-select option:checked {
  background-color: #2563eb;
  color: #ffffff;
}

.industry-select:focus {
  border-color: rgba(96, 165, 250, 0.55);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.22);
}

.repo-shelf-filters {
  display: grid;
  grid-template-columns: minmax(220px, 1.5fr) repeat(5, minmax(126px, 1fr)) auto;
  gap: 0.65rem;
  margin: 0 0 0.65rem;
  align-items: center;
}

.shelf-clear-btn {
  align-self: stretch;
  white-space: nowrap;
}

.header-more-wrap {
  position: relative;
}

.header-more-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 40;
  min-width: 10.5rem;
  padding: 0.35rem;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: #1a1a1e;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}

.header-more-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.65rem;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  font-size: 0.875rem;
  cursor: pointer;
}

.header-more-item:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.header-more-item--danger {
  color: #ff6b6b;
}

.header-more-item--danger:hover:not(:disabled) {
  background: rgba(255, 80, 80, 0.12);
}

.shelf-search,
.shelf-select {
  min-height: 38px;
}

.shelf-select {
  cursor: pointer;
  color-scheme: dark;
}

.repo-shelf-meta {
  margin: 0 0 1rem;
  color: rgba(255, 255, 255, 0.42);
  font-size: 0.82rem;
}

.industry-toolbar-hint {
  margin: 0.5rem 0 0;
}

.page-header {
  margin-bottom: 2rem;
}

.page-title {
  font-size: 1.75rem;
  margin: 0 0 0.5rem;
  color: #ffffff;
}

.page-desc {
  font-size: 0.9rem;
  color: rgba(255,255,255,0.4);
  margin: 0 0 1.25rem;
  line-height: 1.55;
}

.page-desc .mono {
  font-size: 0.8125rem;
  background: rgba(255,255,255,0.06);
  padding: 0.1em 0.35em;
  border-radius: 4px;
  color: rgba(255,255,255,0.75);
}

.bundle-hint {
  font-size: 0.75rem;
  color: rgba(251, 191, 36, 0.9);
  margin: 0 0 0.5rem;
}

.badge-artifact {
  font-weight: 600;
}

.badge-artifact--mod {
  background: rgba(96, 165, 250, 0.12);
  color: #93c5fd;
}

.badge-artifact--employee_pack {
  background: rgba(129, 140, 248, 0.15);
  color: #a5b4fc;
}

.badge-artifact--bundle {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.hidden-input {
  display: none;
}

.flash {
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.flash-ok {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.flash-err {
  background: rgba(255,80,80,0.1);
  color: #ff6b6b;
}

.loading {
  text-align: center;
  padding: 3rem;
  color: rgba(255,255,255,0.3);
}

.mods-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 17rem), 1fr));
  gap: 1rem;
}

.mod-card {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.25rem;
  transition: all 0.2s;
  position: relative;
}

.mod-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.mod-card-top .mod-card-badges {
  margin-bottom: 0;
  flex: 1 1 auto;
  min-width: 0;
}

.mod-card-more-wrap {
  position: relative;
  flex-shrink: 0;
}

.mod-card-more-btn {
  width: 2rem;
  height: 2rem;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.45);
  font-size: 1.1rem;
  line-height: 1;
  cursor: pointer;
}

.mod-card-more-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}

.mod-card-menu {
  position: absolute;
  top: calc(100% + 2px);
  right: 0;
  z-index: 30;
  min-width: 9rem;
  padding: 0.3rem;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: #1a1a1e;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
}

.mod-card-menu-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.45rem 0.6rem;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 0.8125rem;
  cursor: pointer;
}

.mod-card-menu-item--danger {
  color: #ff6b6b;
}

.mod-card-menu-item--danger:hover:not(:disabled) {
  background: rgba(255, 80, 80, 0.12);
}

.mod-card:hover {
  border-color: rgba(255,255,255,0.2);
  transform: translateY(-2px);
}

.mod-card-badges {
  display: flex;
  gap: 0.375rem;
  margin-bottom: 0.75rem;
}

.mod-card-name {
  font-size: 1rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 0.375rem;
}

.mod-card-blurb {
  font-size: 0.8125rem;
  color: rgba(255,255,255,0.5);
  line-height: 1.5;
  margin: 0 0 0.625rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mod-card-blurb--muted {
  color: rgba(255, 255, 255, 0.28);
  font-style: italic;
}

.mod-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
  margin-bottom: 0.45rem;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.38);
}

.mod-card-meta-item--scene {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mod-card-id {
  font-size: 0.75rem;
  color: rgba(255,255,255,0.3);
  font-family: monospace;
  margin-bottom: 0.5rem;
}

.mod-card-scope {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.52);
  margin-bottom: 0.5rem;
  line-height: 1.45;
}

.mod-card-scope--muted {
  color: rgba(255, 255, 255, 0.38);
}

.mod-card-warn {
  font-size: 0.75rem;
  color: #fbbf24;
}

.mod-card-actions {
  margin-top: 1rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.empty-state {
  text-align: center;
  padding: 4rem 1rem;
  color: rgba(255,255,255,0.3);
}

.empty-state p {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
}

.empty-hint {
  font-size: 0.85rem;
  color: rgba(255,255,255,0.2);
}

.empty-link {
  border: none;
  background: none;
  padding: 0;
  color: #93c5fd;
  font-size: inherit;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.empty-link:hover {
  color: #bfdbfe;
}

.btn {
  padding: 0.5rem 1rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: transparent;
  color: rgba(255,255,255,0.7);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:hover {
  background: rgba(255,255,255,0.06);
  color: #ffffff;
}

.btn-primary {
  background: #ffffff;
  color: #0a0a0a;
  border: none;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-sm {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.1875rem 0.5rem;
  border-radius: 4px;
  font-size: 0.6875rem;
  font-weight: 500;
}

.badge-ok {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.badge-warn {
  background: rgba(251,191,36,0.1);
  color: #fbbf24;
}

.badge-primary {
  background: rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.5);
}

.badge-scope {
  background: rgba(20, 184, 166, 0.12);
  color: #5eead4;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.modal {
  width: 100%;
  max-width: 420px;
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 16px;
  padding: 1.5rem;
}

.modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  margin: 0 0 1.25rem;
  color: #ffffff;
}

.form-group {
  margin-bottom: 1rem;
}

.label {
  display: block;
  font-size: 0.8rem;
  color: rgba(255,255,255,0.5);
  margin-bottom: 0.4rem;
}

.input {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: rgba(255,255,255,0.03);
  color: #ffffff;
  font-size: 0.9rem;
  outline: none;
}

.input:focus {
  border-color: rgba(255,255,255,0.3);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.5rem;
}

.modal-wide {
  max-width: 520px;
}

.modal-hint {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.45;
  margin: -0.5rem 0 1rem;
}

.textarea {
  resize: vertical;
  min-height: 6rem;
  font-family: inherit;
}

.checkbox-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
  margin-top: 0.5rem;
}

.btn-secondary {
  border-color: rgba(147, 197, 253, 0.35);
  color: #93c5fd;
}

.btn-secondary:hover {
  background: rgba(96, 165, 250, 0.12);
  color: #bfdbfe;
}

.btn-ghost {
  border-style: dashed;
  border-color: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.55);
}

.btn-ghost:hover {
  border-color: rgba(165, 180, 252, 0.4);
  color: #c7d2fe;
}

.wf-emp-block {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.wf-emp-title {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: rgba(255, 255, 255, 0.35);
  margin-bottom: 0.35rem;
}

.wf-emp-actions {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.wf-emp-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.5rem;
}

@media (max-width: 960px) {
  .repo-shelf-filters {
    grid-template-columns: 1fr 1fr;
  }

  .shelf-clear-btn {
    grid-column: 1 / -1;
    justify-self: start;
  }
}

@media (max-width: 560px) {
  .repo-shelf-filters {
    grid-template-columns: 1fr;
  }
}

html[data-workbench-theme='light'] .repo-page {
  background: #f5f5f7;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .page-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .page-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .page-desc .mono {
  background: rgba(0, 0, 0, 0.05);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .bundle-hint {
  color: #b45309;
}

html[data-workbench-theme='light'] .badge-artifact--mod {
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
}

html[data-workbench-theme='light'] .badge-artifact--employee_pack {
  background: rgba(99, 102, 241, 0.08);
  color: #4f46e5;
}

html[data-workbench-theme='light'] .badge-artifact--bundle {
  background: rgba(217, 119, 6, 0.08);
  color: #b45309;
}

html[data-workbench-theme='light'] .flash-ok {
  background: rgba(22, 163, 74, 0.08);
  color: #16a34a;
}

html[data-workbench-theme='light'] .flash-err {
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
}

html[data-workbench-theme='light'] .loading {
  color: #86868b;
}

html[data-workbench-theme='light'] .mod-card {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .mod-card:hover {
  border-color: rgba(0, 0, 0, 0.12);
}

html[data-workbench-theme='light'] .mod-card-name {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .mod-card-blurb {
  color: #86868b;
}

html[data-workbench-theme='light'] .mod-card-id {
  color: #86868b;
}

html[data-workbench-theme='light'] .mod-card-scope,
html[data-workbench-theme='light'] .repo-shelf-meta {
  color: #6e6e73;
}

html[data-workbench-theme='light'] .mod-card-warn {
  color: #b45309;
}

html[data-workbench-theme='light'] .empty-state {
  color: #86868b;
}

html[data-workbench-theme='light'] .empty-hint {
  color: #aeaeb2;
}

html[data-workbench-theme='light'] .btn {
  border-color: rgba(0, 0, 0, 0.1);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn-primary {
  background: #0071e3;
  color: #ffffff;
}

html[data-workbench-theme='light'] .btn-primary:hover {
  opacity: 0.85;
}

html[data-workbench-theme='light'] .btn-secondary {
  border-color: rgba(0, 113, 227, 0.25);
  color: #0071e3;
}

html[data-workbench-theme='light'] .btn-secondary:hover {
  background: rgba(0, 113, 227, 0.06);
  color: #0060c7;
}

html[data-workbench-theme='light'] .btn-ghost {
  border-color: rgba(0, 0, 0, 0.1);
  color: #86868b;
}

html[data-workbench-theme='light'] .btn-ghost:hover {
  border-color: rgba(0, 113, 227, 0.3);
  color: #0071e3;
}

html[data-workbench-theme='light'] .badge-ok {
  background: rgba(22, 163, 74, 0.08);
  color: #16a34a;
}

html[data-workbench-theme='light'] .badge-warn {
  background: rgba(217, 119, 6, 0.08);
  color: #b45309;
}

html[data-workbench-theme='light'] .badge-primary {
  background: rgba(0, 0, 0, 0.04);
  color: #86868b;
}

html[data-workbench-theme='light'] .modal-overlay {
  background: rgba(0, 0, 0, 0.3);
}

html[data-workbench-theme='light'] .modal {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .modal-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .label {
  color: #86868b;
}

html[data-workbench-theme='light'] .input {
  border-color: rgba(0, 0, 0, 0.1);
  /* 勿用 background 简写，否则会冲掉 .industry-select 的自定义下拉箭头 */
  background-color: rgba(0, 0, 0, 0.02);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .input:focus {
  border-color: #0071e3;
}

html[data-workbench-theme='light'] .industry-toolbar {
  background: rgba(255, 255, 255, 0.92);
  border-color: rgba(0, 0, 0, 0.08);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

html[data-workbench-theme='light'] .industry-select {
  color-scheme: light;
  background-color: #ffffff;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23475569' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.7rem center;
  background-size: 1rem;
}

html[data-workbench-theme='light'] .industry-select option {
  background-color: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .industry-select option:checked {
  background-color: #e8f2ff;
  color: #0a4d9c;
}

html[data-workbench-theme='light'] .modal-hint {
  color: #86868b;
}

html[data-workbench-theme='light'] .checkbox-line {
  color: #86868b;
}

html[data-workbench-theme='light'] .wf-emp-block {
  border-top-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .wf-emp-title {
  color: #86868b;
}
</style>
