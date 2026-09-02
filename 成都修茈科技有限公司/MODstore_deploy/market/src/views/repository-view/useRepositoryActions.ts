// 拆分自 RepositoryView.vue：动作类逻辑（新建/导入/脚手架/删除/一键清理/一键登记/导航/浮层菜单）（逻辑逐字迁移，行为不变）。
import { ref, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api'
import type { IndustryPreset } from '../../constants/industryPresets'
import type { ModRow } from './repositoryTypes'
import {
  LS_AUTHORING_INDUSTRY,
  PREFILL_KEY,
  isCreateModConflictError,
  libraryFolderForDeleteApi,
  modIdForDeleteApi,
  modIdFromDisplayName,
  registerKey,
} from './repositoryTypes'

export interface RepositoryActionsDeps {
  flash: (msg: string, ok?: boolean) => void
  load: (opts?: { cacheBust?: boolean }) => Promise<void>
  mods: Ref<ModRow[]>
  industryPresets: IndustryPreset[]
  message: Ref<string>
}

export function useRepositoryActions(deps: RepositoryActionsDeps) {
  const { flash, load, mods, industryPresets, message } = deps
  const router = useRouter()

  const authoringIndustryId = ref((typeof localStorage !== 'undefined' && localStorage.getItem(LS_AUTHORING_INDUSTRY)) || '通用')
  const createIndustryId = ref(authoringIndustryId.value)
  const showCreate = ref(false)
  const createName = ref('')
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

  function persistAuthoringIndustry() {
    try {
      localStorage.setItem(LS_AUTHORING_INDUSTRY, authoringIndustryId.value)
    } catch {
      /* ignore */
    }
    createIndustryId.value = authoringIndustryId.value
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
      const res = (await api.adminPurgeAllMods()) as {
        removed_dir_count?: number
        removed_user_mod_rows?: number
      }
      const removed = Number(res?.removed_dir_count || 0)
      const removedRows = Number(res?.removed_user_mod_rows || 0)
      flash(`已清空能力货架：删除 ${removed} 个目录，截断 user_mods ${removedRows} 行`, true)
    } catch (e: unknown) {
      flash(`一键清空失败：${e instanceof Error ? e.message : String(e)}`, false)
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
    const prim = m.primary ? '\n\n注意：该包在 manifest 中标记为主扩展（primary），删除后请确认 XCAGI / 宿主侧不再依赖该 id。' : ''
    const idNote = displayId && folderSeg && displayId !== folderSeg ? `（manifest id：${displayId}；目录名：${folderSeg}）` : `（${folder}）`
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
      flash(pid && ver ? `已登记到本地仓库：${pid} @ ${ver}（员工制作页「已登记员工包」可见）` : '已登记到本地仓库（/v1/packages）', true)
    } catch (err) {
      flash((err as Error)?.message || String(err), false)
    } finally {
      registerBusy.value = ''
    }
  }

  function goEmployeePrefill(modId: string, emp: Record<string, unknown>, workflowIndex = 0) {
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
      const res = await api.modAiScaffold(brief, scaffoldIdHint.value.trim(), scaffoldReplace.value, industryId)
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

  return {
    authoringIndustryId,
    createIndustryId,
    showCreate,
    createName,
    showScaffold,
    scaffoldBrief,
    scaffoldIndustryId,
    scaffoldIdHint,
    scaffoldReplace,
    scaffoldBusy,
    registerBusy,
    deleteModBusy,
    purgeLibraryBusy,
    headerMoreOpen,
    openCardMenuId,
    persistAuthoringIndustry,
    closeFloatingMenus,
    toggleCardMenu,
    onDocumentPointerDown,
    onPurgeFromMenu,
    onDeleteFromCardMenu,
    clearRepoPageLocalOnly,
    purgeRepoLibraryAndLocalState,
    deleteModFromLibrary,
    viewMod,
    testModInSandbox,
    registerWorkflowToCatalog,
    goEmployeePrefill,
    openScaffoldModal,
    submitScaffold,
    submitCreate,
    onImport,
  }
}
