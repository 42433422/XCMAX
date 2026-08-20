import { computed, type Ref } from 'vue'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { formatWorkDurationShort, totalWorkMs, type WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'

export type WorkspaceDeskDisplayDeps = {
  nowMs: Ref<number>
  selectedDesk: Ref<WorkflowEmployeeDeskRow | null>
  loopRuntime: Ref<Record<string, unknown> | null>
  loopParticipantIds: Ref<string[]>
  loopParticipantRoleLabels: Ref<Record<string, string>>
}

export function useWorkspaceDeskDisplay(deps: WorkspaceDeskDisplayDeps) {
  const { nowMs, selectedDesk, loopRuntime, loopParticipantIds, loopParticipantRoleLabels } = deps
  const wfEmp = useWorkflowAiEmployeesStore()

  function progressPct(row: WorkflowEmployeeDeskRow): number {
    if (!row.enabled) return 0
    const p = row.snapshot?.progressPct
    if (typeof p !== 'number' || !Number.isFinite(p)) return 0
    return Math.max(0, Math.min(100, p))
  }

  function progressWidth(row: WorkflowEmployeeDeskRow): string {
    return `${progressPct(row)}%`
  }

  function toggleDesk(empId: string, ev: Event) {
    ev.stopPropagation()
    wfEmp.toggle(empId)
  }

  function processedShort(row: WorkflowEmployeeDeskRow): string {
    const n = row.session?.processedCount ?? 0
    if (n <= 999) return String(n)
    if (n <= 9_999) return `${(n / 1000).toFixed(1)}k`
    return `${Math.floor(n / 1000)}k`
  }

  function workShort(row: WorkflowEmployeeDeskRow): string {
    if (!row.enabled) return '—'
    return formatWorkDurationShort(totalWorkMs(row.session, nowMs.value))
  }

  function isLoopParticipant(empId: string): boolean {
    return loopParticipantIds.value.includes(empId)
  }

  function deskLoopState(row: WorkflowEmployeeDeskRow) {
    if (isLoopParticipant(row.empId)) {
      return {
        tone: 'run',
        label: '参与 Loop',
        detail: loopParticipantRoleLabels.value[row.empId] || '已被 self-maintenance runtime 标记为本轮参与员工',
      }
    }
    if (!row.enabled) {
      return {
        tone: 'off',
        label: '未托管',
        detail: '工位没有开启副窗托管；不会作为当前工作现场展示忙态。',
      }
    }
    if (!loopRuntime.value) {
      return {
        tone: 'warn',
        label: 'Loop 未连接',
        detail: '员工空间未拿到 self-maintenance runtime，暂时无法判断是否参与本轮自维护。',
      }
    }
    if (!loopParticipantIds.value.length) {
      return {
        tone: 'idle',
        label: '待派发',
        detail: '当前 runtime 未暴露编制参与者，可能还没达到缺证阈值或 ledger 未回写 employee_id。',
      }
    }
    return {
      tone: 'idle',
      label: '未参与本轮',
      detail: '本轮 self-maintenance runtime 有其他编制员工参与，当前工位未被调度。',
    }
  }

  const selectedDeskLoopState = computed(() => (selectedDesk.value ? deskLoopState(selectedDesk.value) : null))

  return {
    progressPct,
    progressWidth,
    toggleDesk,
    processedShort,
    workShort,
    isLoopParticipant,
    deskLoopState,
    selectedDeskLoopState,
  }
}
