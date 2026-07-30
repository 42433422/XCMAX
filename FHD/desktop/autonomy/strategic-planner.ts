/**
 * 桌面端战略规划客户端——调用后端 LLM 季度目标分解。
 * 本地也可走启发式回退（无网络/无 token 时）。
 */

export interface FeatureBet {
  title: string
  why: string
  success_metric: string
  horizon_weeks: number
  dependencies: string[]
  risk: 'low' | 'medium' | 'high' | string
}

export interface QuarterlyPlan {
  quarter: string
  goal: string
  features: FeatureBet[]
  rationale: string
  revisions: Array<Record<string, unknown>>
  source: string
  generated_at?: string
}

function currentQuarter(d = new Date()): string {
  const q = Math.floor(d.getUTCMonth() / 3) + 1
  return `${d.getUTCFullYear()}-Q${q}`
}

/** 无后端时的本地启发式：至少给出 3 个功能赌注 */
export function heuristicQuarterlyPlan(goal: string, quarter?: string): QuarterlyPlan {
  return {
    quarter: quarter || currentQuarter(),
    goal: goal.trim() || '本季度推进 LLM 战略规划与自治软约束化',
    features: [
      {
        title: 'LLM 季度规划闭环上生产',
        why: '把战略从阈值机升级为可拆解目标',
        success_metric: '每季度自动产出 3 个功能赌注并经反思修订',
        horizon_weeks: 4,
        dependencies: [],
        risk: 'medium',
      },
      {
        title: '运维自治软约束化',
        why: 'CRASH_THRESHOLD 等硬阈值改为带 floor 的自适应',
        success_metric: '崩溃回滚阈值可影子学习且不低于安全下限',
        horizon_weeks: 3,
        dependencies: [],
        risk: 'high',
      },
      {
        title: 'ImpactPredictor 规则+LLM 双轨',
        why: 'switch-case 只做安全轨，复杂副作用走 LLM 顾问',
        success_metric: '高风险动作有 advisory 记录且误拦可审计',
        horizon_weeks: 5,
        dependencies: [],
        risk: 'medium',
      },
    ],
    rationale: 'desktop_heuristic_fallback',
    revisions: [],
    source: 'heuristic_fallback',
    generated_at: new Date().toISOString(),
  }
}

export async function planQuarterViaApi(opts: {
  baseUrl: string
  token?: string
  goal?: string
  critique?: string
  quarter?: string
}): Promise<QuarterlyPlan> {
  const url = `${opts.baseUrl.replace(/\/$/, '')}/api/xcmax/ops/strategic-plan`
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(opts.token ? { Authorization: `Bearer ${opts.token}` } : {}),
      },
      body: JSON.stringify({
        goal: opts.goal,
        critique: opts.critique,
        quarter: opts.quarter,
        use_llm: true,
        persist: true,
      }),
    })
    if (!res.ok) {
      return heuristicQuarterlyPlan(opts.goal || '', opts.quarter)
    }
    const body = (await res.json()) as { success?: boolean; data?: QuarterlyPlan }
    if (body?.data?.features?.length) return body.data
  } catch {
    // fall through
  }
  return heuristicQuarterlyPlan(opts.goal || '', opts.quarter)
}
