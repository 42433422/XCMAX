/**
 * 通往 L4（监督下闭环）的管理端可读清单 — 与运维诊断对齐。
 * 状态由面板结合 runtime policy / 静态诊断刷新；非演示文案。
 */
export type AutonomyGapSeverity = 'P0' | 'P1' | 'P2'
export type AutonomyGapStatus = 'blocked' | 'partial' | 'ok' | 'unknown'

export interface AutonomyMaturityGap {
  id: string
  severity: AutonomyGapSeverity
  title: string
  status: AutonomyGapStatus
  impact: string
  nextStep: string
  ownerSurface: 'ci' | 'modstore' | 'cvm' | 'admin'
  /** Optional deep-link hints for operators */
  actions?: Array<{ label: string; href?: string }>
}

export interface AutonomyL4Readiness {
  targetLevel: 'L4'
  currentLabel: string
  updatedNote: string
  steps: Array<{ id: string; title: string; unlocks: string[] }>
  gaps: AutonomyMaturityGap[]
  l5StructuralGaps: Array<{ id: string; title: string; detail: string }>
}

/** Static baseline; runtime overlay fills deploy/callback fields when API available. */
export const AUTONOMY_L4_READINESS: AutonomyL4Readiness = {
  targetLevel: 'L4',
  currentLabel: 'AI 自愈脚本系统（三步半闭环）',
  updatedNote:
    'P0-1 诊断：XCAGI_LLM_* secrets 已配置；AI Self-Heal 会对「CI/CD Pipeline」失败触发，但常因无法提取错误而 exit 2；大量失败 workflow 名未列入监听列表。',
  steps: [
    {
      id: 'step1',
      title: '解锁 P0-1：让 self-heal 真正修好或可对齐失败面',
      unlocks: ['p0-self-heal'],
    },
    {
      id: 'step2',
      title: '解锁 P0-2/3：staging 打开 AUTO_DISPATCH + watcher 双路径',
      unlocks: ['p0-auto-deploy', 'p0-staging-watcher'],
    },
    {
      id: 'step3',
      title: '解锁 P1：callback 收口 + CI/CVM IM 通知',
      unlocks: ['p1-callback', 'p1-im'],
    },
  ],
  gaps: [
    {
      id: 'p0-self-heal',
      severity: 'P0',
      title: 'CI ai-self-heal 有效治愈率不足',
      status: 'partial',
      impact: '守护机制会跑，但常只建 Issue、不产可合并修复；监听面未覆盖 Employee Smoke / MODstore tests 等',
      nextStep: '扩大 workflows 监听名；修好日志抽取；workflow_dispatch 对真实失败 run 做一次实战',
      ownerSurface: 'ci',
      actions: [
        {
          label: 'AI Self-Heal workflow',
          href: 'https://github.com/42433422/XCMAX/actions/workflows/fhd-ai-self-heal.yml',
        },
      ],
    },
    {
      id: 'p0-auto-deploy',
      severity: 'P0',
      title: '自治部署默认关闭',
      status: 'blocked',
      impact: '闭环只到「合」就停，需人工 dispatch 部署（三步半）',
      nextStep: '仅在 staging 开 MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY=1，跑满 7 天再谈 prod',
      ownerSurface: 'modstore',
    },
    {
      id: 'p0-staging-watcher',
      severity: 'P0',
      title: 'CVM watcher 曾硬编码生产路径',
      status: 'partial',
      impact: '自治动作无法先在 staging 验证',
      nextStep: 'cvm-autonomy-watcher 矩阵：/opt/fhd-staging + /opt/fhd-full',
      ownerSurface: 'cvm',
      actions: [
        {
          label: 'cvm-autonomy-watcher',
          href: 'https://github.com/42433422/XCMAX/actions/workflows/fhd-cvm-autonomy-watcher.yml',
        },
      ],
    },
    {
      id: 'p1-callback',
      severity: 'P1',
      title: 'Callback / approval records 缺失',
      status: 'blocked',
      impact: '状态机停在「已触发未确认」，管理端无法判定是否真正成功',
      nextStep: '修 ingest→approval ledger 链路；面板显示 pending autonomy actions',
      ownerSurface: 'admin',
    },
    {
      id: 'p1-im',
      severity: 'P1',
      title: 'CI/CVM 主动通知缺失',
      status: 'blocked',
      impact: 'needs-human 只能靠 GitHub Issue/PR，人无法及时介入',
      nextStep: '复用 MODstore notification_service 给 CI escalate / watcher 推 IM',
      ownerSurface: 'ci',
    },
    {
      id: 'p1-e2e-loop',
      severity: 'P1',
      title: '连续 N 轮 loop 验证缺失',
      status: 'partial',
      impact: '仅有一次性手动验证，不知长期稳定性',
      nextStep: 'staging 连续 7 日 self-maintenance + 管理端打开件清零趋势',
      ownerSurface: 'admin',
    },
    {
      id: 'p2-mutation',
      severity: 'P2',
      title: '变异测试 kill rate ~43%（目标 80%）',
      status: 'partial',
      impact: '自治 PR 修复正确性无量化门禁',
      nextStep: '先 weekly 监控，再升为 PR gate',
      ownerSurface: 'ci',
    },
  ],
  l5StructuralGaps: [
    {
      id: 'self-evolve-policy',
      title: '无自我演化机制',
      detail: 'policy 自身 frozen，系统不能改自己的策略',
    },
    {
      id: 'multi-objective',
      title: '无多目标优化',
      detail: '只解决失败→修复，未权衡性能/成本/体验',
    },
    {
      id: 'formal-verify',
      title: '无形式化验证',
      detail: '正确性靠 LLM + 测试，无数学证明',
    },
  ],
}

export function overlayDeployGap(
  gaps: AutonomyMaturityGap[],
  autoDispatchEnabled: boolean | null,
): AutonomyMaturityGap[] {
  return gaps.map((gap) => {
    if (gap.id !== 'p0-auto-deploy' || autoDispatchEnabled == null) return gap
    if (autoDispatchEnabled) {
      return {
        ...gap,
        status: 'partial',
        impact: 'AUTO_DISPATCH_DEPLOY 已打开；请确认仅限 staging envs 且观察 7 日',
      }
    }
    return { ...gap, status: 'blocked' }
  })
}
