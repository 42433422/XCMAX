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
  currentLabel: 'AI 自愈脚本系统（三步半闭环 → 监督下闭环）',
  updatedNote:
    '2026-07-21 verify-l4：7 个 gap 修复协同验证通过。P0-1 staging env 模板就绪；P0-2 autonomy_callback.py + 4 处集成点落地（p1-callback → ok）；P0-3 fhd-deploy.yml 3 处 production-only 改 (production||staging)；P1-1 approval_resume.py mobile push hook + merge_github_pr/close_github_issue executor；P1-2 bus.py 7 开关默认全开；P1-3 ai_review.py fail-open path-level 兜底。待 staging CVM SSH 引导 secrets 后实战验证。',
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
      impact:
        '守护机制会跑，但常只建 Issue、不产可合并修复；监听面未覆盖 Employee Smoke / MODstore tests 等。P1-3 已在 ai_review.py fail-open 路径加 path-level 规则兜底（7 path rules + 2 deletion + 7 binary exts），减少误判',
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
      title: 'staging 自动部署默认开启',
      status: 'partial',
      impact:
        '主开关未设时默认开；ENVS 空则仅 staging；production 须显式列入 ENVS。P0-1 已补 staging-autonomy.env.example 模板 + 文档引导（docs/autonomy/），实际生效需 SSH 到 staging CVM 引导 secrets',
      nextStep: 'SSH 到 staging CVM 引导 staging-autonomy.env；观察 staging 自动部署 7 日；确认 production 未误入 ENVS',
      ownerSurface: 'modstore',
    },
    {
      id: 'p0-staging-watcher',
      severity: 'P0',
      title: 'CVM watcher 曾硬编码生产路径',
      status: 'partial',
      impact:
        '矩阵已含 staging；独立健康检查见 scripts/deploy/check-staging-health.sh。P0-3 已将 fhd-deploy.yml 中 3 处 production-only 条件改为 (production||staging)，staging 通道代码就绪',
      nextStep: 'SSH 到 staging CVM 引导 secrets；定期跑 check-staging-health.sh；确认 watcher staging tick 非 skipped',
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
      status: 'ok',
      impact:
        'SSOT：FHD/scripts/autonomy/autonomy_callback.py（ingest + github-approval 终态）；ci/ 为兼容 shim。已接 cvm_autonomy_watcher / escalate_to_human；CVM 已配 FHD_API_BASE_URL + AUTONOMY_WEBHOOK_TOKEN。',
      nextStep: '管理端面板补 pending autonomy actions 趋势图即可',
      ownerSurface: 'admin',
    },
    {
      id: 'p1-runtime-sync',
      severity: 'P1',
      title: 'runtime 副本双向同步缺失',
      status: 'ok',
      impact: '已落地 sync-runtime-to-source.sh + install-sync-runtime-to-source-cron.sh，与 install-local-autonomy-runtime 形成双向同步',
      nextStep: '开发机执行一次 install-sync-runtime-to-source-cron.sh 后保持每小时回写',
      ownerSurface: 'modstore',
    },
    {
      id: 'p1-implement-pack',
      severity: 'P1',
      title: '连接点 4 implement-pack 曾仅靠标签隐式触发',
      status: 'ok',
      impact: 'evolution_decision_ledger.cmd_implement_pack 经 gh workflow run 显式触发 fhd-ai-issue-implement.yml；标签路径仅作手工兜底',
      nextStep: '观察一周 evolution-orchestrator → implement 链路成功率',
      ownerSurface: 'ci',
    },
    {
      id: 'p1-im',
      severity: 'P1',
      title: 'CI/CVM 主动通知已接管理端 IM',
      status: 'ok',
      impact:
        'escalate_to_human / cvm watcher 旁路推老板 IM（fail-open）；需配内部 URL + API key + boss uid。P1-1 已在 approval_resume.py 加 mobile push hook（_notify_autonomy_actor，复用 notify_mobile_user）+ 注册 merge_github_pr / close_github_issue 两个 executor，管理端审批通过后可自动合并 PR / 关闭 issue',
      nextStep:
        '在 CI/CVM 配置 XCAGI_FHD_INTERNAL_URL + XCAGI_MARKET_INTERNAL_API_KEY + XCAGI_AUTONOMY_IM_BOSS_USER_ID；管理端配置 XCAGI_ADMIN_NOTIFY_USER_ID 后 mobile push 即生效；实战验证一条 escalate',
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
      title: '变异测试 PR gate（阈值 80%）',
      status: 'partial',
      impact:
        'gate 作用域收紧为 app/di + app/contexts；kill rate 达标后阻断 PR。P2-1 已补 Top 3 模块测试（di/contexts/flags），未达 80% 目标，当前为监控指标非 PR 阻断',
      nextStep: '继续补测试提升 kill rate 至 ≥80%；确认 mutation-smoke 在 PR 上绿；逐步扩大 source_paths',
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

export function overlayDeployGap(gaps: AutonomyMaturityGap[], autoDispatchEnabled: boolean | null): AutonomyMaturityGap[] {
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
