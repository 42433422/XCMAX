import { useRoute, useRouter } from 'vue-router'
import { useAgentStore } from '../../stores/agent'
import { api } from '../../api'
import type { OrchestrationSession } from '../../types/agent'

const POLL_INTERVAL_MS = 1200

export type OrchestrationTarget = {
  type: 'mod' | 'workflow' | 'employee'
  id: string
}

export function useButlerOrchestrator() {
  const route = useRoute()
  const router = useRouter()
  const agentStore = useAgentStore()

  /** 根据当前路由推断可编辑的目标（Mod / 工作流 / 员工）。*/
  function detectTarget(): OrchestrationTarget | null {
    if (route.name === 'mod-authoring') {
      const modId = route.params.modId
      if (typeof modId === 'string' && modId) {
        return { type: 'mod', id: modId }
      }
    }
    if (route.name === 'workbench-shell') {
      const target = route.params.target
      const id = route.params.id
      if (target === 'workflow' && typeof id === 'string' && id) {
        return { type: 'workflow', id }
      }
      if (target === 'employee' && typeof id === 'string' && id) {
        return { type: 'employee', id }
      }
    }
    return null
  }

  /**
   * 启动编排管线：POST /api/agent/butler/orchestrate → 轮询 /api/workbench/sessions/{id}
   * 调用前确保已拿到用户确认（requestAction high-risk）。
   */
  async function start(
    brief: string,
    scope?: string,
  ): Promise<{ ok: boolean; error?: string }> {
    const tgt = detectTarget()
    if (!tgt) {
      return {
        ok: false,
        error: '当前页面无法直接改写，请先打开具体的 Mod / 工作流 / 员工页',
      }
    }

    agentStore.setMode('orchestrating')

    let sessionId: string
    try {
      const resp = await (api as any).butlerOrchestrateStart({
        target_type: tgt.type,
        target_id: tgt.id,
        brief,
        scope: scope || 'auto',
      }) as { session_id: string; status: string }
      sessionId = resp.session_id
    } catch (e: unknown) {
      agentStore.setMode('error')
      return { ok: false, error: e instanceof Error ? e.message : String(e) }
    }

    // Seed the store so the overlay appears immediately
    agentStore.orchestrationSession = {
      sessionId,
      steps: [],
      status: 'running',
    }

    // Fire-and-forget poll loop; overlay reacts to store changes
    void _pollLoop(sessionId)
    return { ok: true }
  }

  async function _pollLoop(sid: string): Promise<void> {
    while (true) {
      try {
        const s = await (api as any).workbenchGetSession(sid) as {
          status: string
          steps: OrchestrationSession['steps']
          error?: string | null
          artifact?: Record<string, unknown> | null
        }
        const prev = agentStore.orchestrationSession
        const mergedSteps = _mergeStepsMonotonic(prev?.steps, s.steps ?? [])
        agentStore.orchestrationSession = {
          sessionId: sid,
          steps: mergedSteps,
          status: (s.status === 'done' || s.status === 'error' ? s.status : 'running') as OrchestrationSession['status'],
          error: s.error ?? null,
          artifact: s.artifact ?? null,
        }
        if (s.status === 'done' || s.status === 'error') {
          if (s.status === 'done') {
            agentStore.setMode('idle')
          } else {
            agentStore.setMode('error')
          }
          return
        }
      } catch {
        // Network hiccup — keep retrying
      }
      await _delay(POLL_INTERVAL_MS)
    }
  }

  /** 完成后全页刷新（最简单：重新加载当前路由数据）。*/
  function refreshAfterDone(): void {
    router.go(0)
  }

  /** 回滚到快照（仅 mod 场景）。*/
  async function rollbackToSnapshot(modId: string, snapId: string): Promise<void> {
    try {
      await (api as any).restoreModSnapshot(modId, snapId)
      router.go(0)
    } catch (e: unknown) {
      console.error('rollback failed', e)
    }
  }

  return { detectTarget, start, refreshAfterDone, rollbackToSnapshot }
}

function _delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

const _STATUS_RANK: Record<string, number> = { pending: 0, running: 1, done: 2, error: 2 }
function _mergeStepsMonotonic(
  prev: OrchestrationSession['steps'] | undefined,
  incoming: OrchestrationSession['steps'],
): OrchestrationSession['steps'] {
  if (!prev || !prev.length) return incoming
  const prevMap = new Map<string, { status: string; started_at?: string }>()
  for (const st of prev) prevMap.set(String(st.id), st)
  return incoming.map((st) => {
    const prevSt = prevMap.get(String(st.id))
    if (!prevSt) return st
    const prevRank = _STATUS_RANK[String(prevSt.status)] ?? 0
    const inRank = _STATUS_RANK[String(st.status)] ?? 0
    if (inRank >= prevRank) return st
    return { ...st, status: prevSt.status as any, started_at: prevSt.started_at }
  })
}
