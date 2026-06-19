/**
 * 日更全链路辐射视图 — dagre LR + 中心「日更闭环」辐射（与编制图一致）
 *
 * 对接契约（v2 · SOT_VERSION = 2026-06-08）：
 *  1. 节点容器 `data-emp-wf-node="<id>"`（所有节点必带；中心=CENTER_ID），
 *     `data-emp-wf-phase="<phase>"` 仅在节点有 phase 时挂载。
 *  2. 单击节点派发 `CustomEvent('emp-wf:node-click', { detail: { id, label,
 *     phase, desc, source: 'radial' }, bubbles: true })`；
 *     兼容旧名 `emp-wf-node-click`。
 *  3. 外层容器尺寸变化（iframe/嵌入/缩放）由内部 ResizeObserver 监听，
 *     自动调 `__empWfPanZoom.reset()` 重置视图。
 *  4. 标签文本优先走 `setLabelResolver(fn)` 注入的解析器（fn 同步返回
 *     string 或 Promise<string>），未注入则用 NODES 里写死的 label。
 *  5. 暴露 `EmpWfRadialGraph.SOT_VERSION` 给宿主做缓存/版本校验。
 */
const EmpWfRadialGraph = (() => {
  /* 优先从 xcagi-dashboard-sot.js 单点 SOT 取；未加载时回落到本地常量。 */
  const SOT_VERSION =
    (typeof window !== 'undefined' && window.XCAGI_DASHBOARD_SOT && window.XCAGI_DASHBOARD_SOT.version) ||
    '2026-06-08';
  const CENTER_ID = 'daily-hub';
  const NODE_W = 200;
  const NODE_H = 76;
  const CENTER_W = 128;
  const CENTER_H = 48;
  /** 枢纽胶囊占位：须计入 stage 高度，且不能被 minY 归一化抵消 */
  const HUB_TOP = 16;
  const HUB_GAP = 44;
  const TOP_RESERVE = HUB_TOP + CENTER_H + HUB_GAP;
  const COMPACT_IDS = new Set([
    'P3', 'P4', 'P5', 'P6', 'P6G', 'P6POP', 'P6PW', 'P7', 'P8', 'P9', 'P9G', 'P9I', 'P5I', 'P6I',
    'BK', 'BKOND', 'DRPROBE', 'ART', 'WB_D', 'WB_M', 'GAPS', 'ROAD',
  ]);
  const TAB_LINK_NODES = { GAPS: 'gaps', ROAD: 'roadmap' };

  /** 节点尺寸计算常量 */
  const DECISION_NODE_MIN_W = 132;
  const DECISION_NODE_MAX_W = 196;
  const DECISION_CHAR_WIDTH = 6.8;
  const DECISION_HEIGHT_RATIO = 0.78;
  const PHASE_NODE_W = 272;
  const PHASE_NODE_H = 92;
  const COMPACT_NODE_W = 112;
  const COMPACT_NODE_H = 54;
  const STEP_NODE_CHAR_WIDTH = 6.4;
  const STEP_NODE_MIN_W = 172;
  const STEP_NODE_MAX_W = 248;
  const STEP_NODE_LONG_LABEL_LEN = 26;
  const STEP_NODE_LONG_H = 86;
  const STEP_NODE_DEFAULT_H = 72;

  const PHASE_COLORS = {
    t0: '#79c0ff',
    t1: '#58e2c2',
    t2: '#d2a8ff',
    t2b: '#a371f7',
    t3: '#56d364',
    t4: '#ffa657',
    evt: '#f778ba',
  };

  const AUTO_MAINTENANCE_POLICY = {
    enabled: true,
    missingEvidenceThreshold: 3,
    syncLimit: 32,
    cooldownMs: 10 * 60 * 1000,
    minQueueGap: 1,
  };

  function _toPositiveInt(raw, fallback, min = 1) {
    const n = Number.parseInt(String(raw), 10);
    if (Number.isNaN(n)) return fallback;
    return Math.max(min, n);
  }

  function _readBoolean(raw, fallback = true) {
    if (raw === undefined || raw === null || raw === '') return fallback;
    const normalized = String(raw).trim().toLowerCase();
    if (['1', 'true', 'yes', 'on', 'enabled'].includes(normalized)) return true;
    if (['0', 'false', 'no', 'off', 'disabled'].includes(normalized)) return false;
    return fallback;
  }

  function getAutoMaintenancePolicy(root) {
    const p = { ...AUTO_MAINTENANCE_POLICY };
    const rootDataset = (root && root.dataset) ? root.dataset : null;
    if (rootDataset) {
      const flag = rootDataset.empWfAutoMaintenance;
      if (flag != null && flag !== '') {
        p.enabled = _readBoolean(flag, p.enabled);
      }
      p.missingEvidenceThreshold = _toPositiveInt(rootDataset.empWfAutoMaintenanceThreshold, p.missingEvidenceThreshold, 1);
      p.syncLimit = _toPositiveInt(rootDataset.empWfAutoMaintenanceLimit, p.syncLimit);
      p.cooldownMs = Math.max(
        30 * 1000,
        _toPositiveInt(rootDataset.empWfAutoMaintenanceCooldownMs, Math.floor(p.cooldownMs / 1000), 30) * 1000,
      );
      p.minQueueGap = _toPositiveInt(rootDataset.empWfAutoMaintenanceMinQueueGap, p.minQueueGap, 1);
    }
    try {
      const query = new URLSearchParams((typeof location !== 'undefined' && location.search) || '');
      const urlEnabled = query.get('auto_maintenance_enabled');
      if (urlEnabled !== null) {
        p.enabled = _readBoolean(urlEnabled, p.enabled);
      }
      p.missingEvidenceThreshold = _toPositiveInt(
        query.get('auto_maintenance_threshold'),
        p.missingEvidenceThreshold,
        1,
      );
      p.syncLimit = _toPositiveInt(query.get('auto_maintenance_limit'), p.syncLimit);
      p.cooldownMs = Math.max(
        30 * 1000,
        _toPositiveInt(query.get('auto_maintenance_cooldown_ms'), Math.floor(p.cooldownMs / 1000), 30) * 1000,
      );
      p.minQueueGap = _toPositiveInt(query.get('auto_maintenance_min_queue_gap'), p.minQueueGap, 1);
    } catch (_err) {
      /* ignore */
    }
    return p;
  }

  function shouldAutoMaintenanceSync(root, coverage) {
    if (!root || !coverage) return null;
    const policy = getAutoMaintenancePolicy(root);
    if (!policy.enabled) return null;
    const missing = Number(coverage.missing_evidence_nodes || 0);
    const queued = Number(coverage.maintenance_queued_nodes || 0);
    if (!Number.isFinite(missing) || missing < policy.missingEvidenceThreshold) return null;
    const remaining = missing - queued;
    if (remaining < policy.minQueueGap) return null;

    const now = Date.now();
    const lastAt = Number(root.__empWfAutoMaintenanceLastRunAt || 0);
    const lastMissing = Number(root.__empWfAutoMaintenanceLastMissing || -1);

    if (missing > lastMissing) {
      return { policy, missing, queued, remaining };
    }
    if (lastAt > 0 && now - lastAt < policy.cooldownMs) {
      return null;
    }
    return { policy, missing, queued, remaining };
  }

  async function autoTriggerMaintenanceSync(root, coverage) {
    if (!root) return;
    if (root.__empWfAutoMaintenanceInFlight) return;
    const rootControls = getMaintenanceSyncControls();
    const suggestion = shouldAutoMaintenanceSync(root, coverage);
    if (!suggestion) return;

    const limit = Math.min(suggestion.policy.syncLimit, Math.max(1, suggestion.missing));
    root.__empWfAutoMaintenanceInFlight = true;
    root.__empWfAutoMaintenanceLastRunAt = Date.now();
    root.__empWfAutoMaintenanceLastMissing = suggestion.missing;
    if (rootControls.syncBtn) rootControls.syncBtn.disabled = true;
    setMaintenanceSyncStatus(
      `缺证 ${suggestion.missing} >= 阈值 ${suggestion.policy.missingEvidenceThreshold}，自动补齐中（limit=${limit}）`,
      'running',
    );
    try {
      const result = await syncMissingEvidenceBacklog(limit);
      const added = Number(result && result.added ? result.added : 0);
      const skipped = Number(result && result.skipped ? result.skipped : 0);
      const total = Number(result && result.total_missing ? result.total_missing : suggestion.missing);
      const msgChunks = [];
      if (!Number.isNaN(added)) msgChunks.push(`已入队 ${added}`);
      if (!Number.isNaN(skipped)) msgChunks.push(`已存在 ${skipped}`);
      if (!Number.isNaN(total)) msgChunks.push(`缺证 ${total}`);
      setMaintenanceSyncStatus(`自维护已自动触发：${msgChunks.length ? msgChunks.join('，') : '任务已提交'}`, 'ok');
    } catch (err) {
      setMaintenanceSyncStatus(`自维护自动触发失败：${err && err.message ? err.message : String(err || 'unknown')}`, 'error');
    } finally {
      root.__empWfAutoMaintenanceInFlight = false;
      if (rootControls.syncBtn) {
        const stillAvailable = !root.classList.contains('is-runtime-status-error');
        rootControls.syncBtn.disabled = !stillAvailable;
      }
    }
  }

  const NODES = [
    { id: CENTER_ID, label: '日更闭环', kind: 'center' },
    { id: 'BK', label: '03:05 容灾备份', kind: 'step', phase: 't0', desc: 'SQLite 全量备份（VACUUM INTO + wal_checkpoint TRUNCATE）+ release_train 快照 → backups/ · v2.2: 真实 WAL 增量（拷贝 .db-wal/.db-shm）+ 全量轮转' },
    {
      id: 'BKOND',
      label: '按需快照\n交叉升级/回滚触发',
      kind: 'step',
      phase: 't0',
      desc: '交叉升级/回滚前主动触发按需快照，独立目录 backups/ondemand/ + 独立保留策略（默认7份），同时写 release_train 历史快照确保回滚粒度精确 · v2.2: 快照失败联动 DR 守卫',
    },
    {
      id: 'DRFAIL',
      label: '灾备失败 → 降级\n告警 + 跳过当日 bump',
      kind: 'step',
      phase: 't0',
      desc: '容灾备份失败时熔断：发告警、保留上一份快照、当日不递增 release_train（last_bump_day 守卫兜底）· v2.2: 自动恢复探针每30分钟重试，超8次升级告警；clear_backup_guard 双轨发布 dispatch 事件',
    },
    {
      id: 'DRPROBE',
      label: '自动恢复探针\n30min 重试 × 8',
      kind: 'step',
      phase: 't0',
      desc: 'DRFAIL 守卫生效后，每30分钟自动重试备份；成功则解除守卫恢复日更（双轨 dispatch backup.dr_guard.cleared 事件），超8次升级告警。retry_count 结构化字段写入 SSOT',
    },
    { id: 'R', label: '03:15 retention-officer 归档', kind: 'step', phase: 't0', desc: '日志与过期数据归档清理，释放存储空间，确保备份后数据链路清洁' },
    {
      id: 'K',
      label: '运维 KPI · 待审 · TLS · IMAP',
      kind: 'step',
      phase: 't1',
      desc: 'SLO 7 天 staging 验收【进行中 · 已更正】：服务器 119.27.178.147 k3s xcagi-staging 集群健康运行（docker 26.1.3 + 全 pod Running/0 重启）。Prometheus 抓 xcagi-backend(xcagi-service:80)=UP、8d 保留；k6-7day 168h 压测进行中（~11% · 已 18h+ · 0 中断 · 22.5w 迭代），api_requests_total 持续增长（11.9w，近 1h +1.8w）。窗口约 6 天后达 168h → 填 reading_7d + SRE 签字解 T36–T37。注：本地 k3d/KinD 试装失败仅影响开发机、不影响服务器集群；k6 自身 /metrics target 因非 scrape 设计显示 down，不影响 SLO 采集。acceptance-*.yaml 已据实声明 observation_mode。',
    },
    { id: 'SW', label: 'P-W 网站截图+分析', kind: 'step', phase: 't1' },
    { id: 'SS', label: 'P-S 软件截图+分析', kind: 'step', phase: 't1' },
    { id: 'SA', label: 'P-App 移动/WebView 截图', kind: 'step', phase: 't1' },
    { id: 'M', label: '员工大会 → 会议摘要', kind: 'step', phase: 't1' },
    { id: 'PPTX', label: '三端截图 → PPT 附件', kind: 'step', phase: 't1' },
    { id: 'ASM', label: '拼装 digest HTML', kind: 'step', phase: 't1' },
    { id: 'P', label: '落库 DailyDigestRecord', kind: 'step', phase: 't1' },
    { id: 'RT', label: 'release_train +0.0.0.1\n同日幂等', kind: 'step', phase: 't1', desc: 'last_bump_day 守卫 · 历史快照 jsonl' },
    { id: 'CENT', label: 'day_index % 100 = 0?', kind: 'decision', phase: 't1' },
    { id: 'MAJ', label: 'major 大推送 1.N.0.0', kind: 'step', phase: 't1' },
    { id: 'V', label: 'Vibe 预备 更新+补丁 MD', kind: 'step', phase: 't1' },
    {
      id: 'ACT',
      label: '双清单 → daily_action_items',
      kind: 'step',
      phase: 't1',
      desc: 'parse_and_store_action_items · 同日 dedupe_key 幂等',
    },
    {
      id: 'GAPS',
      label: '断点清单 · AI 补丁看板',
      kind: 'step',
      phase: 't1',
      desc: '#s-gaps · kind=patch · 固定卡片模板 · 单一数据源',
    },
    {
      id: 'ROAD',
      label: '路线图 · AI 更新看板',
      kind: 'step',
      phase: 't1',
      desc: '#s-roadmap · kind=update · 状态随执行自动刷新',
    },
    {
      id: 'ART',
      label: '阶段结果文件面板',
      kind: 'step',
      phase: 't1',
      desc: 'PNG/PPT/Vibe MD/RT 历史/DR 备份 · artifacts API',
    },
    { id: 'L', label: '四产线拆分 P-W/P-S/P-App/S-R', kind: 'phase', phase: 't1', desc: '【跨轨桥接 经营→研发】事件轨 O7 变更反馈 / CS_CHG 变更工单 / Vibe08 08:00 补丁清单 汇入日更四产线 backlog，与双清单 action_items 合流派发' },
    { id: 'PARSE', label: '08:15 解析 WorkUnit', kind: 'step', phase: 't2' },
    { id: 'PSA', label: 'P-S Runner 补丁派发', kind: 'step', phase: 't2' },
    { id: 'APPA', label: 'P-App Runner 补丁派发', kind: 'step', phase: 't2' },
    {
      id: 'GITCR',
      label: 'CR → 员工分支\ngit commit + gh PR',
      kind: 'step',
      phase: 't2',
      desc: 'cr_git_pipeline：apply CR 暂存到 employees/<id> 分支 → git commit「apply CR-<id>」→（MODSTORE_CR_GIT_AUTO_PR=1）gh PR；默认全开，git 不可用则降级跳过',
    },
    { id: 'ORCH', label: '08:25 release_train orchestrator', kind: 'phase', phase: 't2b' },
    { id: 'PW', label: 'P-W Runner 更新派发', kind: 'step', phase: 't2b' },
    { id: 'APPB', label: 'P-App Runner 更新派发', kind: 'step', phase: 't2b' },
    { id: 'SR', label: 'S-R Runner 派发', kind: 'step', phase: 't2b' },
    { id: 'KIND', label: 'release_kind?', kind: 'decision', phase: 't2b' },
    { id: 'P9I', label: 'deploy-release-officer P9', kind: 'step', phase: 't2b' },
    { id: 'P5I', label: 'deploy-release-officer P5 全量', kind: 'step', phase: 't2b' },
    { id: 'P6I', label: 'push-update-context P6 OTA/COS', kind: 'step', phase: 't2b' },
    {
      id: 'FASTGATE',
      label: '即时推送门禁\nstaging+健康检查通过?',
      kind: 'decision',
      phase: 't2b',
      desc: '快路径全量推送 COS/OTA 前置门禁：staging 验收 + /healthz + 关键 smoke 通过才放行 DLSSOT；不过则转 ROLLBACK 自动回滚。堵住「即时路径绕过灰度/审批直推全量」的风险',
    },
    {
      id: 'DLSSOT',
      label: '安装包推 COS\n回写下载版本 SSOT',
      kind: 'step',
      phase: 't2b',
      desc: 'release/xcagi-v10.0.0/{personal,enterprise} → dl.xiu-ci.com · 回写 FHD/config/download_release.json.last_push + 官网 /download-release.json（下载页 fetch，无需重建即生效）· v10 锁恒 10.0.0 · 【跨轨桥接 研发→经营】产出供事件轨 O6 企业使用 / O5 交付编排 消费 OTA',
    },
    { id: 'BR', label: '切日更分支 primary 模式', kind: 'step', phase: 't2b' },
    { id: 'P2W', label: 'P2 网站编码', kind: 'step', phase: 't3' },
    { id: 'P2S', label: 'P2 软件编码', kind: 'step', phase: 't3' },
    { id: 'P2APP', label: 'P2 App 打包/渠道', kind: 'step', phase: 't3' },
    { id: 'P2R', label: 'P2 归档/文档', kind: 'step', phase: 't3' },
    { id: 'GATE', label: '第4段=0 且非首日?', kind: 'decision', phase: 't3' },
    { id: 'P9G', label: 'P9 十日线代际 Gn→Gn+1', kind: 'step', phase: 't3' },
    { id: 'P3', label: 'P3 测试', kind: 'step', phase: 't3' },
    { id: 'P4', label: 'P4 CI 构建', kind: 'step', phase: 't3' },
    { id: 'P5', label: 'P5 发布', kind: 'step', phase: 't3' },
    {
      id: 'CANARY',
      label: '灰度发布\nstaging→canary 10%→prod',
      kind: 'step',
      phase: 't3',
      desc: 'XCAGI_DEPLOY_STRATEGY=canary（默认）：先 staging 验证 → 金丝雀 10% 流量 + HPA 自动扩缩 → 校验通过再推进 production（rolling/canary/blue-green 可选）',
    },
    { id: 'P6', label: 'P6 推送更新', kind: 'step', phase: 't3' },
    { id: 'P6G', label: '每30日 · 0.0.3.0?', kind: 'decision', phase: 't3' },
    { id: 'P6POP', label: 'Desktop+App 更新弹窗', kind: 'step', phase: 't3' },
    { id: 'P6PW', label: 'P-W 网站静默自更', kind: 'step', phase: 't3' },
    {
      id: 'ROLLBACK',
      label: '校验不过 → 自动回滚\n回上一稳定版 + 告警',
      kind: 'step',
      phase: 't3',
      desc: '灰度/即时门禁失败统一回滚：deploy-release-officer 回退到上一稳定 release_train，COS/OTA 撤包，发告警并落 OpsStagedChange 复盘待审',
    },
    {
      id: 'HEAL',
      label: 'P7 异常 → 自愈\n重启/扩缩/熔断',
      kind: 'step',
      phase: 't3',
      desc: '监控触发自愈闭环：HPA 扩缩 + pod 重启 + 失败熔断；自愈无效则升级为 OpsStagedChange 人工介入',
    },
    { id: 'P7', label: 'P7 监控', kind: 'step', phase: 't3' },
    { id: 'P8', label: 'P8 净化', kind: 'step', phase: 't3' },
    { id: 'P9', label: 'P9 版本演进 · SSOT', kind: 'step', phase: 't3' },
    { id: 'STG', label: 'OpsStagedChange pending', kind: 'step', phase: 't4' },
    { id: 'APPR', label: '邮件/工作台审批', kind: 'step', phase: 't4' },
    {
      id: 'V10SYNC',
      label: '版本统一管理\nWeb·App·软件',
      desc: '除各端独立 OTA 外，统一收口网站/App/软件营销锚点与 Mod 宿主版本',
      kind: 'step',
      phase: 't4',
    },
    { id: 'MERGE', label: '合并 + 部署', kind: 'step', phase: 't4' },
    {
      id: 'WB_D',
      label: '派发回写 dispatched',
      kind: 'step',
      phase: 't2',
      desc: 'line-execute 成功 → sync_dispatched_for_work_units',
    },
    {
      id: 'WB_M',
      label: '部署回写 merged ✅',
      kind: 'step',
      phase: 't4',
      desc: 'OpsStagedChange 部署 → sync_merged_on_deploy · 卡片淡化',
    },
    /* 跨轨桥接：研发时间轨 ↔ 经营事件轨（节点 ID 复用 daily_digest_node_employees.json 现有编制） */
    {
      id: 'O5',
      label: '事件轨 · O5 交付编排',
      kind: 'step',
      phase: 'evt',
      desc: '【跨轨 研发→经营】DLSSOT 今日 OTA/COS 产物供事件轨 O5 交付编排消费（deploy-release-officer + shipment_mgmt）',
    },
    {
      id: 'O6',
      label: '事件轨 · O6 企业使用',
      kind: 'step',
      phase: 'evt',
      desc: '【跨轨 研发→经营】交付后企业实际使用，沉淀使用信号供 O7 反馈与经营治理',
    },
    {
      id: 'O7',
      label: '事件轨 · O7 变更反馈',
      kind: 'step',
      phase: 'evt',
      desc: '【跨轨 经营→研发】企业使用反馈 → six_line_event_router → backlog/change_request，次日汇入日更',
    },
    {
      id: 'CS_CHG',
      label: '变更工单 · ops-dispatch',
      kind: 'step',
      phase: 'evt',
      desc: '【跨轨 经营→研发】客服变更工单归一化进 six_line_digest_backlog.jsonl',
    },
    {
      id: 'Vibe08',
      label: '08:00 补丁清单 P-S',
      kind: 'step',
      phase: 'evt',
      desc: '【跨轨 经营→研发】M2 已接线：08:00 Vibe 将事件轨 backlog 合并进次日补丁清单 → 汇入双清单',
    },
  ];

  const FLOW_EDGES = [
    ['SW', 'M'], ['SS', 'M'], ['SA', 'M'],
    ['SW', 'PPTX'], ['SS', 'PPTX'], ['SA', 'PPTX'],
    ['K', 'ASM'], ['M', 'ASM'], ['PPTX', 'ASM', true],
    ['ASM', 'P'], ['P', 'RT'], ['P', 'ART', true], ['RT', 'CENT'],
    ['CENT', 'MAJ'], ['RT', 'V'], ['V', 'ACT'], ['ACT', 'L'],
    ['ACT', 'GAPS', true], ['ACT', 'ROAD', true],
    ['L', 'PARSE'], ['PARSE', 'PSA'], ['PARSE', 'APPA'],
    ['PSA', 'GITCR'], ['APPA', 'GITCR'], ['GITCR', 'WB_D'],
    ['PSA', 'WB_D'], ['APPA', 'WB_D'], ['WB_D', 'GAPS', true], ['WB_D', 'ROAD', true],
    ['PSA', 'ORCH'], ['APPA', 'ORCH'],
    ['ORCH', 'PW'], ['ORCH', 'APPB'], ['ORCH', 'SR'], ['ORCH', 'KIND'],
    ['PW', 'WB_D'], ['APPB', 'WB_D'], ['SR', 'WB_D'],
    ['KIND', 'P9I'], ['P9I', 'P5I'], ['P5I', 'P6I'], ['P6I', 'FASTGATE'],
    ['FASTGATE', 'DLSSOT'], ['FASTGATE', 'ROLLBACK', true], ['ORCH', 'BR'],
    ['PW', 'P2W'], ['PSA', 'P2S'], ['APPA', 'P2APP'], ['APPB', 'P2APP', true],
    ['SR', 'P2R'],
    ['P2W', 'GATE'], ['P2S', 'GATE'], ['P2APP', 'GATE'], ['P2R', 'GATE'],
    ['GATE', 'P9G'], ['GATE', 'P3'], ['P9G', 'P5I'],
    ['P3', 'P4'], ['P4', 'P5'], ['P5', 'CANARY'], ['CANARY', 'P6'],
    ['CANARY', 'ROLLBACK', true], ['ROLLBACK', 'STG', true],
    ['P6', 'P6PW', true], ['P6', 'P6G'],
    ['P6G', 'P6POP'], ['P6G', 'P7'], ['P6POP', 'P7'], ['P6PW', 'P7', true],
    ['P7', 'P8'], ['P8', 'P9'], ['P7', 'HEAL', true], ['HEAL', 'STG', true], ['HEAL', 'P8', true],
    ['MAJ', 'P5I', true], ['P9', 'STG'], ['STG', 'APPR'], ['APPR', 'V10SYNC'], ['V10SYNC', 'MERGE'],
    ['MERGE', 'WB_M'], ['WB_M', 'GAPS', true], ['WB_M', 'ROAD', true],
    ['BK', 'R'], ['BK', 'DRFAIL', true], ['DRFAIL', 'R', true], ['DRFAIL', 'DRPROBE', true],
    ['DRPROBE', 'BK', true], ['BKOND', 'R', true],
    ['R', 'K', true], ['R', 'SW', true], ['R', 'SS', true], ['R', 'SA', true],
    ['BR', 'P2W'], ['BR', 'P2S'], ['BR', 'P2APP'], ['BR', 'P2R'],
    ['DLSSOT', 'P7'],
    /* 跨轨闭环：研发产出 → 经营使用 → 反馈 → 次日研发（XRAIL_EDGE_KEYS 渲染为跨轨虚线） */
    ['DLSSOT', 'O5'], ['O5', 'O6'], ['O6', 'O7'],
    ['O7', 'CS_CHG'], ['CS_CHG', 'Vibe08'], ['Vibe08', 'V'],
  ];

  /** 跨轨桥接边：研发时间轨 ↔ 经营事件轨，独立粉色虚线样式 */
  const XRAIL_EDGE_KEYS = new Set([
    'DLSSOT->O5', 'O5->O6', 'O6->O7', 'O7->CS_CHG', 'CS_CHG->Vibe08', 'Vibe08->V',
  ]);

  let dagrePromise = null;
  let currentView = 'radial';
  let labelResolver = null;
  let resizeObserver = null;

  /**
   * 注入标签解析器：fn(node) -> string | Promise<string>
   * 用于多模型协作：接入方可在 fn 里把 `03:15 retention-officer 归档`
   * 拆成 `03:15 ${zhLabel} ${动作}`，避免每个模型各自拼接漂移。
   */
  function setLabelResolver(fn) {
    labelResolver = typeof fn === 'function' ? fn : null;
  }

  /**
   * 启动期 schema 校验：发现 NODES 缺 id / 重复 id / phase 不在色板
   * 立刻抛错，避免下游接进去后才发现节点没渲染。
   */
  function validateSchema() {
    const seen = new Set();
    for (const n of NODES) {
      if (!n || typeof n !== 'object' || !n.id) {
        throw new Error('emp-wf-radial: NODES 存在缺 id 的条目');
      }
      if (seen.has(n.id)) {
        throw new Error('emp-wf-radial: NODES 存在重复 id = ' + n.id);
      }
      seen.add(n.id);
      if (n.id !== CENTER_ID && !n.kind) {
        throw new Error('emp-wf-radial: 节点 ' + n.id + ' 缺 kind');
      }
      if (n.phase && !PHASE_COLORS[n.phase]) {
        throw new Error('emp-wf-radial: 节点 ' + n.id + ' 的 phase=' + n.phase + ' 不在 PHASE_COLORS');
      }
    }
  }

  /**
   * 把节点点击派发为标准 CustomEvent，集成方只需
   * `host.addEventListener('emp-wf:node-click', e => ...)` 即可。
   * 旧名 `emp-wf-node-click` 同时派发，避免老集成方漏接。
   */
  function dispatchNodeClick(domEl, originalEvent, nodeDef) {
    if (!domEl) return;
    const detail = {
      id: (domEl.dataset && domEl.dataset.empWfNode) || (nodeDef && nodeDef.id) || '',
      label: (nodeDef && nodeDef.label) || (domEl.textContent && domEl.textContent.trim()) || '',
      phase: (nodeDef && nodeDef.phase) || (domEl.dataset && domEl.dataset.empWfPhase) || '',
      desc: (nodeDef && nodeDef.desc) || '',
      kind: (nodeDef && nodeDef.kind) || '',
      source: 'radial',
    };
    const ev = new CustomEvent('emp-wf:node-click', { detail, bubbles: true, cancelable: true });
    const legacy = new CustomEvent('emp-wf-node-click', { detail, bubbles: true, cancelable: true });
    if (originalEvent && typeof originalEvent.stopPropagation === 'function') {
      originalEvent.stopPropagation();
    }
    domEl.dispatchEvent(ev);
    domEl.dispatchEvent(legacy);
  }

  const DAGRE_URLS = [
    'docs/xcagi-dashboard/vendor/dagre.min.js',
    'https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1.1.4/dist/dagre.min.js',
  ];

  function loadDagre() {
    if (window.dagre && window.dagre.graphlib) return Promise.resolve(window.dagre);
    if (dagrePromise) return dagrePromise;
    dagrePromise = new Promise((resolve, reject) => {
      let idx = 0;
      const tryNext = () => {
        if (idx >= DAGRE_URLS.length) {
          reject(new Error('dagre 布局库加载失败'));
          return;
        }
        const s = document.createElement('script');
        s.src = DAGRE_URLS[idx++];
        s.async = true;
        s.onload = () => {
          if (window.dagre && window.dagre.graphlib) resolve(window.dagre);
          else tryNext();
        };
        s.onerror = tryNext;
        document.head.appendChild(s);
      };
      tryNext();
    });
    return dagrePromise;
  }

  function nodeSize(n) {
    if (n.id === CENTER_ID) return { w: CENTER_W, h: CENTER_H };
    if (n.kind === 'decision') {
      const w = Math.min(DECISION_NODE_MAX_W, Math.max(DECISION_NODE_MIN_W, Math.ceil(n.label.length * DECISION_CHAR_WIDTH)));
      return { w, h: Math.round(w * DECISION_HEIGHT_RATIO) };
    }
    if (n.kind === 'phase') return { w: PHASE_NODE_W, h: PHASE_NODE_H };
    if (COMPACT_IDS.has(n.id)) return { w: COMPACT_NODE_W, h: COMPACT_NODE_H };
    const long = n.label.length > STEP_NODE_LONG_LABEL_LEN;
    const w = Math.min(STEP_NODE_MAX_W, Math.max(STEP_NODE_MIN_W, Math.ceil(n.label.length * STEP_NODE_CHAR_WIDTH)));
    return { w, h: long ? STEP_NODE_LONG_H : STEP_NODE_DEFAULT_H };
  }

  function layoutGraphOpts() {
    const embed = document.body.classList.contains('embed-workflow');
    return {
      rankdir: 'TB',
      ranksep: embed ? 48 : 64,
      nodesep: embed ? 24 : 32,
      marginx: embed ? 16 : 24,
      marginy: embed ? 16 : 24,
    };
  }

  function computeLayout(dagreLib) {
    const g = new dagreLib.graphlib.Graph({ multigraph: true });
    g.setDefaultEdgeLabel(() => ({}));
    /* 仅主流程边 TB 布局，与 Mermaid 纵向架构图一致（勿从中心辐射 hub 边） */
    g.setGraph(layoutGraphOpts());

    for (const n of NODES) {
      if (n.id === CENTER_ID) continue;
      const sz = nodeSize(n);
      g.setNode(n.id, { width: sz.w, height: sz.h });
    }

    for (const row of FLOW_EDGES) {
      if (row[0] === CENTER_ID || row[1] === CENTER_ID) continue;
      g.setEdge(row[0], row[1], {}, 'flow-' + row[0] + '-' + row[1]);
    }

    dagreLib.layout(g);

    const positions = new Map();
    for (const n of NODES) {
      const pos = g.node(n.id);
      const sz = nodeSize(n);
      if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
        positions.set(n.id, { x: pos.x - sz.w / 2, y: pos.y - sz.h / 2, w: sz.w, h: sz.h });
      }
    }
    if (positions.size < 2) throw new Error('dagre 布局结果为空');
    return { positions };
  }

  const PIPELINE_EDGE_KEYS = new Set([
    'ASM->P', 'P->RT', 'RT->CENT', 'CENT->MAJ', 'RT->V', 'V->ACT', 'ACT->L',
    'BK->R', 'BKOND->R', 'L->PARSE', 'PARSE->PSA', 'PARSE->APPA', 'PSA->ORCH', 'APPA->ORCH',
    'PSA->WB_D', 'APPA->WB_D', 'PW->WB_D', 'APPB->WB_D', 'SR->WB_D',
    'ORCH->PW', 'ORCH->APPB', 'ORCH->SR', 'ORCH->KIND', 'ORCH->BR',
    'KIND->P9I', 'P9I->P5I', 'P5I->P6I',
    'PW->P2W', 'PSA->P2S', 'APPA->P2APP', 'SR->P2R',
    'P2W->GATE', 'P2S->GATE', 'P2APP->GATE', 'P2R->GATE',
    'GATE->P9G', 'GATE->P3', 'P3->P4', 'P4->P5', 'P5->P6', 'P6->P6G',
    'P6G->P6POP', 'P6G->P7', 'P6POP->P7', 'P7->P8', 'P8->P9',
    'P9->STG', 'STG->APPR', 'APPR->V10SYNC', 'V10SYNC->MERGE', 'MERGE->WB_M',
  ]);

  function displayBox(p, minX, minY, pad, topReserve) {
    return {
      x: p.x - minX + pad,
      y: p.y - minY + pad + (topReserve || 0),
      w: p.w,
      h: p.h,
    };
  }

  const LANE_SPACING = 16;
  const ARROW_TRIM = 10;

  /** TB 正交折线（下行边）：源底 → 汇顶；lane 用于同源/同汇并行边错开，避免叠成一条 */
  function orthogonalPath(x1, y1, x2, y2, laneSrc, laneTgt) {
    const xs = x1 + (laneSrc || 0) * LANE_SPACING;
    const xt = x2 + (laneTgt || 0) * LANE_SPACING;
    const yEnd = y2 - ARROW_TRIM;
    if (Math.abs(xs - xt) < 4) return `M ${xs} ${y1} L ${xt} ${yEnd}`;
    const midY = y1 + Math.max(22, (yEnd - y1) * 0.42);
    return `M ${xs} ${y1} L ${xs} ${midY} L ${xt} ${midY} L ${xt} ${yEnd}`;
  }

  /**
   * 上行（逆向回流）边：源顶 → 汇底，竖直正交向上。
   * 代际/major/跨轨反馈等回边专用，避免「先下沉再跳上」的 zig-zag。
   */
  function orthogonalPathUp(x1, yTop, x2, yBot, laneSrc, laneTgt) {
    const xs = x1 + (laneSrc || 0) * LANE_SPACING;
    const xt = x2 + (laneTgt || 0) * LANE_SPACING;
    const yEnd = yBot + ARROW_TRIM;
    if (Math.abs(xs - xt) < 4) return `M ${xs} ${yTop} L ${xt} ${yEnd}`;
    const midY = yTop - Math.max(22, (yTop - yEnd) * 0.42);
    return `M ${xs} ${yTop} L ${xs} ${midY} L ${xt} ${midY} L ${xt} ${yEnd}`;
  }

  function edgeLaneMaps(edges) {
    const outCount = new Map();
    const inCount = new Map();
    for (const row of edges) {
      outCount.set(row[0], (outCount.get(row[0]) || 0) + 1);
      inCount.set(row[1], (inCount.get(row[1]) || 0) + 1);
    }
    const outIdx = new Map();
    const inIdx = new Map();
    const lanes = new Map();
    for (const row of edges) {
      const key = row[0] + '->' + row[1];
      const oi = outIdx.get(row[0]) || 0;
      outIdx.set(row[0], oi + 1);
      const ii = inIdx.get(row[1]) || 0;
      inIdx.set(row[1], ii + 1);
      const oTotal = outCount.get(row[0]) || 1;
      const iTotal = inCount.get(row[1]) || 1;
      const laneSrc = oTotal > 1 ? oi - (oTotal - 1) / 2 : 0;
      const laneTgt = iTotal > 1 ? ii - (iTotal - 1) / 2 : 0;
      lanes.set(key, { laneSrc, laneTgt });
    }
    return lanes;
  }

  function edgeMarkerId(row) {
    const key = row[0] + '->' + row[1];
    if (XRAIL_EDGE_KEYS.has(key)) return 'emp-wf-arrow-xrail';
    if (row[2]) return 'emp-wf-arrow-hub';
    if (PIPELINE_EDGE_KEYS.has(key)) return 'emp-wf-arrow-pipeline';
    return 'emp-wf-arrow-branch';
  }

  function appendArrowMarker(defs, id, fill) {
    const ns = 'http://www.w3.org/2000/svg';
    const marker = document.createElementNS(ns, 'marker');
    marker.setAttribute('id', id);
    marker.setAttribute('markerWidth', '12');
    marker.setAttribute('markerHeight', '12');
    marker.setAttribute('refX', '10');
    marker.setAttribute('refY', '6');
    marker.setAttribute('orient', 'auto');
    marker.setAttribute('markerUnits', 'userSpaceOnUse');
    const arrow = document.createElementNS(ns, 'path');
    arrow.setAttribute('d', 'M0,1 L11,6 L0,11 Z');
    arrow.setAttribute('fill', fill);
    marker.appendChild(arrow);
    defs.appendChild(marker);
  }

  function renderEdges(svg, positions, edges, minX, minY, pad, topReserve) {
    const ns = 'http://www.w3.org/2000/svg';
    const lanes = edgeLaneMaps(edges);
    for (const row of edges) {
      const src = positions.get(row[0]);
      const tgt = positions.get(row[1]);
      if (!src || !tgt) continue;
      const s = displayBox(src, minX, minY, pad, topReserve);
      const t = displayBox(tgt, minX, minY, pad, topReserve);
      const sCx = s.x + s.w / 2;
      const tCx = t.x + t.w / 2;
      const key = row[0] + '->' + row[1];
      const lane = lanes.get(key) || { laneSrc: 0, laneTgt: 0 };
      const path = document.createElementNS(ns, 'path');
      /* 汇点整体在源点上方 → 逆向回流边，走上行竖直正交，避免下沉再跳起 */
      const isBack = t.y + t.h <= s.y - 4;
      const d = isBack
        ? orthogonalPathUp(sCx, s.y, tCx, t.y + t.h, lane.laneSrc, lane.laneTgt)
        : orthogonalPath(sCx, s.y + s.h, tCx, t.y, lane.laneSrc, lane.laneTgt);
      path.setAttribute('d', d);
      let cls = 'emp-wf-radial-edge';
      if (XRAIL_EDGE_KEYS.has(key)) cls += ' emp-wf-radial-edge--xrail';
      else if (row[2]) cls += ' emp-wf-radial-edge--hub';
      else if (PIPELINE_EDGE_KEYS.has(key)) cls += ' emp-wf-radial-edge--pipeline';
      else cls += ' emp-wf-radial-edge--branch';
      if (isBack) cls += ' emp-wf-radial-edge--back';
      path.setAttribute('class', cls);
      path.setAttribute('marker-end', 'url(#' + edgeMarkerId(row) + ')');
      svg.appendChild(path);
    }
  }

  function bindPanZoom(host, viewport, stage) {
    if (window.EmpWfPanZoom && typeof window.EmpWfPanZoom.bind === 'function') {
      window.EmpWfPanZoom.bind(host, viewport, stage);
    }
  }

  async function renderRadial(root) {
    root.classList.add('is-loading');
    root.classList.remove('is-error');
    root.textContent = '正在布局辐射图…';
    try {
      const dagreLib = await loadDagre();
      const layout = computeLayout(dagreLib);
      const positions = layout.positions;
      root.innerHTML = '';

      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const p of positions.values()) {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x + p.w);
        maxY = Math.max(maxY, p.y + p.h);
      }
      const pad = 48;
      const width = maxX - minX + pad * 2;
      const height = maxY - minY + pad * 2 + TOP_RESERVE;
      if (!Number.isFinite(width) || !Number.isFinite(height) || width < 80 || height < 80) {
        throw new Error('布局尺寸无效');
      }

      const stage = document.createElement('div');
      stage.className = 'emp-wf-radial-stage';
      stage.style.width = width + 'px';
      stage.style.height = height + 'px';

      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'emp-wf-radial-svg');
      svg.setAttribute('width', String(width));
      svg.setAttribute('height', String(height));
      const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      appendArrowMarker(defs, 'emp-wf-arrow-pipeline', '#56d364');
      appendArrowMarker(defs, 'emp-wf-arrow-branch', '#79c0ff');
      appendArrowMarker(defs, 'emp-wf-arrow-hub', '#58e2c2');
      appendArrowMarker(defs, 'emp-wf-arrow-xrail', '#f778ba');
      svg.appendChild(defs);
      stage.appendChild(svg);

      const centerDef = NODES.find((n) => n.id === CENTER_ID);
      const flowEdges = FLOW_EDGES.map((r) => [r[0], r[1], !!r[2]]);
      renderEdges(svg, positions, flowEdges, minX, minY, pad, TOP_RESERVE);
      /* 枢纽 → 03:05 容灾备份（日更闭环真正入口）：竖直正交，避免斜穿全图 */
      const rPos = positions.get('BK');
      if (rPos && centerDef) {
        const hubCx = width / 2;
        const hubBottom = HUB_TOP + CENTER_H;
        const rBox = displayBox(rPos, minX, minY, pad, TOP_RESERVE);
        const rtx = rBox.x + rBox.w / 2;
        const rty = rBox.y;
        const bendY = hubBottom + 24;
        const rtyEnd = rty - ARROW_TRIM;
        const ns = 'http://www.w3.org/2000/svg';
        const deco = document.createElementNS(ns, 'path');
        deco.setAttribute(
          'd',
          `M ${hubCx} ${hubBottom} L ${hubCx} ${bendY} L ${rtx} ${bendY} L ${rtx} ${rtyEnd}`,
        );
        deco.setAttribute('class', 'emp-wf-radial-edge emp-wf-radial-edge--hub');
        deco.setAttribute('marker-end', 'url(#emp-wf-arrow-hub)');
        svg.appendChild(deco);
      }

      const layer = document.createElement('div');
      layer.className = 'emp-wf-radial-nodes';
      for (const n of NODES) {
        if (n.id === CENTER_ID) continue;
        const p = positions.get(n.id);
        if (!p) continue;
        const el = document.createElement('div');
        const kindCls =
          n.id === CENTER_ID
            ? ' emp-wf-radial-node--center'
            : n.kind === 'decision'
              ? ' emp-wf-radial-node--decision'
              : n.kind === 'phase'
                ? ' emp-wf-radial-node--phase'
                : ' emp-wf-radial-node--step';
        const compactCls = COMPACT_IDS.has(n.id) ? ' emp-wf-radial-node--compact' : '';
        el.className = 'emp-wf-radial-node' + kindCls + compactCls;
        el.style.left = p.x - minX + pad + 'px';
        el.style.top = p.y - minY + pad + TOP_RESERVE + 'px';
        el.style.width = p.w + 'px';
        el.style.height = p.h + 'px';
        el.style.minHeight = p.h + 'px';
        if (n.phase && PHASE_COLORS[n.phase]) {
          el.style.setProperty('--phase-color', PHASE_COLORS[n.phase]);
          el.className += ' emp-wf-radial-node--' + n.phase;
        }
        if (n.label.indexOf('\n') >= 0) el.style.whiteSpace = 'pre-line';
        el.textContent = n.label;
        el.title = [n.desc, n.label, '点击查看主责/协作员工'].filter(Boolean).join('\n');
        /* 对接契约 P0：所有节点必带 data-emp-wf-node；下游 EmpWfNodeStaff / 集成方
           都靠它定位（之前版本漏挂导致 click 弹层全失效，已修复） */
        el.dataset.empWfNode = n.id;
        if (n.phase) el.dataset.empWfPhase = n.phase;
        el.setAttribute('data-emp-wf-bound', '1');
        el.style.cursor = 'pointer';
        el.addEventListener('click', (ev) => {
          const panHost =
            document.getElementById('emp-wf-radial-root') || document.getElementById('event-arch-root');
          if (panHost && panHost.dataset.panMoved === '1') return;
          dispatchNodeClick(el, ev, n);
        });
        const tabId = TAB_LINK_NODES[n.id];
        if (tabId) {
          el.title += '\n双击打开对应 Tab';
          el.addEventListener('dblclick', (ev) => {
            ev.stopPropagation();
            if (typeof window.go === 'function') window.go(tabId);
          });
        }
        /* i18n 解析：labelResolver 注入时用解析结果覆盖 textContent + title 中的 label */
        if (labelResolver) {
          try {
            const resolved = labelResolver(n);
            if (resolved && typeof resolved.then === 'function') {
              resolved.then((txt) => { if (txt) el.textContent = txt; }).catch(() => { });
            } else if (resolved) {
              el.textContent = String(resolved);
            }
          } catch (_err) { /* 解析器失败时回退到原 label */ }
        }
        layer.appendChild(el);
      }
      if (centerDef) {
        const hub = document.createElement('div');
        hub.className = 'emp-wf-radial-node emp-wf-radial-node--center';
        hub.style.left = width / 2 - CENTER_W / 2 + 'px';
        hub.style.top = HUB_TOP + 'px';
        hub.style.width = CENTER_W + 'px';
        hub.style.height = CENTER_H + 'px';
        hub.style.minHeight = CENTER_H + 'px';
        hub.textContent = centerDef.label;
        hub.title = centerDef.desc
          ? [centerDef.desc, centerDef.label, '点击查看主责/协作员工'].filter(Boolean).join('\n')
          : centerDef.label + '\n点击查看主责/协作员工';
        hub.dataset.empWfNode = CENTER_ID;
        hub.setAttribute('data-emp-wf-bound', '1');
        hub.style.cursor = 'pointer';
        hub.addEventListener('click', (ev) => {
          const panHost = document.getElementById('emp-wf-radial-root');
          if (panHost && panHost.dataset.panMoved === '1') return;
          dispatchNodeClick(hub, ev, centerDef);
        });
        layer.appendChild(hub);
      }
      stage.appendChild(layer);
      const viewport = document.createElement('div');
      viewport.className = 'emp-wf-radial-viewport';
      viewport.appendChild(stage);
      root.appendChild(viewport);
      bindPanZoom(root, viewport, stage);
      attachResizeObserver(root);
      root.classList.remove('is-error', 'is-loading');
      if (window.EmpWfNodeStaff && typeof window.EmpWfNodeStaff.bindRadial === 'function') {
        window.EmpWfNodeStaff.bindRadial(layer);
      }
      if (window.EmpWfSurfaceAudit && typeof window.EmpWfSurfaceAudit.bindRadialDoubleOpen === 'function') {
        window.EmpWfSurfaceAudit.bindRadialDoubleOpen(layer);
      }
      startRuntimeStatusPolling(root, layer);
      scrollDiagramToTop();
    } catch (err) {
      root.classList.add('is-error');
      root.classList.remove('is-loading');
      root.textContent = '辐射视图渲染失败：' + (err && err.message ? err.message : 'unknown');
      throw err;
    }
  }

  async function fetchRuntimeStatus() {
    const paths = [
      '/api/xcmax/production-line/time-rail/status',
      '/api/admin/production-line/time-rail/status',
    ];
    const bases = [''];
    if (location.protocol === 'file:') bases.push('http://127.0.0.1:5000', 'http://127.0.0.1:8788');
    let lastError = '';
    for (const base of bases) {
      for (const path of paths) {
        try {
          const url = base ? base + path : path;
          const r = await fetch(url, { signal: AbortSignal.timeout(2500) });
          const ct = (r.headers.get('content-type') || '').toLowerCase();
          if (ct.includes('text/html')) {
            lastError = `non-JSON response ${r.status} ${path}`;
            continue;
          }
          const j = await r.json();
          if (!r.ok || j.success === false || j.ok === false) {
            lastError = String(j.error || j.message || `HTTP ${r.status}`);
            continue;
          }
          const data = (j && j.data) || null;
          if (data && data.nodes) return data;
          lastError = 'time-rail status missing nodes';
        } catch (err) {
          lastError = err && err.message ? err.message : String(err);
        }
      }
    }
    return { error: lastError || 'time-rail status unavailable' };
  }

  function proofShort(row) {
    if (!row) return 'miss';
    if (row.guard_active) return 'guard';
    const ps = String(row.proof_status || '');
    if (ps === 'missing_evidence') return 'miss';
    if (ps === 'maintenance_queued') return 'todo';
    if (row.ok === false) return 'fail';
    if (row.ok === true) return 'ok';
    if (ps.indexOf('decision_') === 0) return ps === 'decision_true' ? 'yes' : 'no';
    if (row.observed) return 'seen';
    return 'miss';
  }

  function getMaintenanceSyncControls() {
    return {
      statusEl: document.getElementById('emp-wf-maintenance-sync-status'),
      syncBtn: document.getElementById('btn-time-rail-maintenance-sync'),
    };
  }

  function setMaintenanceSyncStatus(message, level) {
    const { statusEl } = getMaintenanceSyncControls();
    if (!statusEl) return;
    statusEl.textContent = message || '';
    statusEl.dataset.empWfMaintenanceSyncStatus = level || 'ready';
    statusEl.classList.remove(
      'emp-wf-maintenance-sync-status--ok',
      'emp-wf-maintenance-sync-status--running',
      'emp-wf-maintenance-sync-status--error',
    );
    if (level === 'ok' || level === 'success') {
      statusEl.classList.add('emp-wf-maintenance-sync-status--ok');
    }
    if (level === 'running') {
      statusEl.classList.add('emp-wf-maintenance-sync-status--running');
    }
    if (level === 'error') {
      statusEl.classList.add('emp-wf-maintenance-sync-status--error');
    }
  }

  function setMaintenanceSyncReady(enabled) {
    const { syncBtn } = getMaintenanceSyncControls();
    if (!syncBtn) return;
    syncBtn.disabled = !enabled;
  }

  function timeRailApiBases() {
    const bases = [''];
    if (location.protocol === 'file:') {
      bases.push('http://127.0.0.1:5000', 'http://127.0.0.1:8788');
    }
    return bases;
  }

  function readCsrfToken() {
    const raw = typeof document !== 'undefined' ? String(document.cookie || '') : '';
    for (const part of raw.split(';')) {
      const item = part.trim();
      if (!item.startsWith('csrf_token=')) continue;
      const token = item.slice('csrf_token='.length);
      try {
        return decodeURIComponent(token);
      } catch (_err) {
        return token;
      }
    }
    return '';
  }

  function csrfJsonHeaders() {
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
    const csrf = readCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
    return headers;
  }

  async function syncMissingEvidenceBacklog(limit = 32) {
    const paths = [
      '/api/xcmax/production-line/time-rail/maintenance/sync',
      '/api/admin/production-line/time-rail/maintenance/sync',
    ];
    let lastError = '';
    for (const base of timeRailApiBases()) {
      for (const path of paths) {
        try {
          const url = base ? base + path : path;
          const r = await fetch(url, {
            method: 'POST',
            headers: csrfJsonHeaders(),
            credentials: 'include',
            body: JSON.stringify({ limit }),
            signal: AbortSignal.timeout(2500),
          });
          const ct = (r.headers.get('content-type') || '').toLowerCase();
          if (ct.includes('text/html')) {
            lastError = `non-JSON response ${r.status} ${path}`;
            continue;
          }
          const j = await r.json();
          if (!r.ok || j.success === false || j.ok === false) {
            lastError = String(j.error || j.message || `HTTP ${r.status}`);
            continue;
          }
          return (j && j.data) || j;
        } catch (err) {
          lastError = err && err.message ? err.message : String(err);
        }
      }
    }
    throw new Error(lastError || 'time-rail maintenance sync unavailable');
  }

  function startRuntimeStatusPolling(root, layer) {
    if (!root || !layer) return;
    if (root.__empWfRuntimeTimer) {
      clearInterval(root.__empWfRuntimeTimer);
      root.__empWfRuntimeTimer = null;
    }
    const run = () => {
      setMaintenanceSyncStatus('运行时状态拉取中…', 'running');
      fetchRuntimeStatus()
        .then((wrap) => {
          if (!wrap || wrap.error) {
            root.classList.add('is-runtime-status-error');
            const msg = (wrap && wrap.error) || 'time-rail status 不可用（MODstore 未启动或 API 503）';
            root.setAttribute('data-runtime-status-error', msg);
            setMaintenanceSyncReady(false);
            setMaintenanceSyncStatus(msg, 'error');
            return;
          }
          root.classList.remove('is-runtime-status-error');
          root.removeAttribute('data-runtime-status-error');
          if (wrap.coverage) {
            root.dataset.empWfStatusCoverage = String(wrap.coverage.status_coverage_pct ?? '');
            root.dataset.empWfObservedCoverage = String(wrap.coverage.observed_coverage_pct ?? '');
            root.dataset.empWfMissingEvidence = String(wrap.coverage.missing_evidence_nodes ?? '');
            const total = Number(wrap.coverage.total_nodes || Object.keys(wrap.nodes || {}).length || 0);
            const missing = Number(wrap.coverage.missing_evidence_nodes || 0);
            const queued = Number(wrap.coverage.maintenance_queued_nodes || 0);
            const autoPolicy = shouldAutoMaintenanceSync(root, wrap.coverage);
            if (autoPolicy) {
              void autoTriggerMaintenanceSync(root, wrap.coverage);
            }
            setMaintenanceSyncStatus(`已连接状态服务（覆盖 ${total}；缺证 ${missing}；待自维护 ${queued}）`, 'ok');
            setMaintenanceSyncReady(true);
          }
          if (wrap.nodes) applyRuntimeStatusToLayer(layer, wrap.nodes);
          const seconds = Number(wrap.refresh_after_seconds || 15);
          const nextMs = Math.max(5000, Math.min(seconds * 1000, 60000));
          if (root.__empWfRuntimeIntervalMs !== nextMs) {
            if (root.__empWfRuntimeTimer) clearInterval(root.__empWfRuntimeTimer);
            root.__empWfRuntimeIntervalMs = nextMs;
            root.__empWfRuntimeTimer = setInterval(run, nextMs);
          }
        })
        .catch((err) => {
          root.classList.add('is-runtime-status-error');
          root.setAttribute(
            'data-runtime-status-error',
            err && err.message ? err.message : 'time-rail status fetch failed',
          );
          setMaintenanceSyncReady(false);
          setMaintenanceSyncStatus(err && err.message ? err.message : 'time-rail status fetch failed', 'error');
        });
    };
    root.__empWfRuntimeRefreshStatus = run;
    run();
  }

  function applyRuntimeStatusToLayer(layer, nodesById) {
    if (!layer || !nodesById) return;
    layer.querySelectorAll('.emp-wf-radial-node[data-emp-wf-node]').forEach((el) => {
      const nid = (el.dataset.empWfNode || '').trim();
      const row = nodesById[nid];
      el.classList.remove(
        'emp-wf-radial-node--runtime-ok',
        'emp-wf-radial-node--runtime-fail',
        'emp-wf-radial-node--runtime-guard',
        'emp-wf-radial-node--runtime-unknown',
        'emp-wf-radial-node--runtime-missing',
        'emp-wf-radial-node--runtime-seen',
        'emp-wf-radial-node--runtime-todo',
      );
      if (!row) {
        el.classList.add('emp-wf-radial-node--runtime-missing');
        el.dataset.empWfProofShort = 'miss';
        return;
      }
      if (row.guard_active) el.classList.add('emp-wf-radial-node--runtime-guard');
      else if (row.ok === true) el.classList.add('emp-wf-radial-node--runtime-ok');
      else if (row.ok === false) el.classList.add('emp-wf-radial-node--runtime-fail');
      else if (row.observed) el.classList.add('emp-wf-radial-node--runtime-seen');
      else if (row.proof_status === 'maintenance_queued') el.classList.add('emp-wf-radial-node--runtime-todo');
      else if (row.proof_status === 'missing_evidence') el.classList.add('emp-wf-radial-node--runtime-missing');
      else el.classList.add('emp-wf-radial-node--runtime-unknown');
      const missing = Array.isArray(row.missing_evidence) ? row.missing_evidence.join('; ') : '';
      const hint = [
        row.last_run ? 'last_run: ' + row.last_run : '',
        row.ok === true ? 'ok' : row.ok === false ? 'fail' : 'unknown',
        row.guard_active ? 'guard_active' : '',
        row.proof_status ? 'proof: ' + row.proof_status : '',
        row.evidence_count != null ? 'evidence: ' + row.evidence_count : '',
        row.source ? 'src: ' + row.source : '',
        missing ? 'missing: ' + missing : '',
      ].filter(Boolean).join(' · ');
      const baseTitle = el.dataset.empWfBaseTitle || el.title || '';
      el.dataset.empWfBaseTitle = baseTitle;
      if (hint) el.title = baseTitle + '\n' + hint;
      el.dataset.empWfRuntimeOk = row.ok === true ? '1' : row.ok === false ? '0' : '';
      el.dataset.empWfGuardActive = row.guard_active ? '1' : '0';
      el.dataset.empWfObserved = row.observed ? '1' : '0';
      el.dataset.empWfProofStatus = row.proof_status || '';
      el.dataset.empWfEvidenceCount = String(row.evidence_count || 0);
      el.dataset.empWfProofShort = proofShort(row);
    });
  }

  /**
   * 容器尺寸变化（iframe 嵌入 / 父级 flex 重排 / 浏览器缩放）时，
   * 自动调 pan/zoom 的 reset() 把图重新居中缩放，避免节点溢出。
   * ResizeObserver 在多次 render 时会复用同一个 observer 实例。
   */
  function attachResizeObserver(root) {
    if (typeof ResizeObserver === 'undefined') return; // 老浏览器降级
    if (resizeObserver) {
      try { resizeObserver.disconnect(); } catch (_e) { /* ignore */ }
    }
    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const target = entry.target;
        if (!target || !target.isConnected) continue;
        const pz = target.__empWfPanZoom;
        if (pz && typeof pz.reset === 'function') {
          requestAnimationFrame(() => pz.reset());
        }
      }
    });
    resizeObserver.observe(root);
  }

  let switchingView = false;

  /**
   * 派发视图切换事件：集成方只需监听 `emp-wf:view-change`（推荐）
   * 或旧名 `emp-wf-view-change`，detail 包含 prev/curr + 触发源。
   * 旧名 `view-change` 同步派发，保留双轨兼容。
   */
  function dispatchViewChange(prev, curr, source) {
    const host =
      document.getElementById('emp-wf-radial-root') ||
      document.getElementById('emp-wf-arch-diagram') ||
      document.body;
    if (!host) return;
    const detail = { prev: prev || '', curr: curr || '', source: source || 'unknown', at: Date.now() };
    const ev = new CustomEvent('emp-wf:view-change', { detail, bubbles: true, cancelable: false });
    const legacy = new CustomEvent('emp-wf-view-change', { detail, bubbles: true, cancelable: false });
    host.dispatchEvent(ev);
    host.dispatchEvent(legacy);
  }

  function setView(mode) {
    if (switchingView) return;
    switchingView = true;
    try {
      const wasRadial = currentView === 'radial';
      const prevView = currentView;
      currentView = mode;
      const wrap = document.getElementById('emp-wf-arch-diagram');
      const radialRoot = document.getElementById('emp-wf-radial-root');
      const mermaidBlocks = wrap ? wrap.querySelectorAll('.mermaid.emp-wf-mermaid, .emp-wf-mermaid-part-label') : [];
      const toolbar = document.querySelector('.emp-wf-diagram-toolbar');
      if (toolbar) {
        toolbar.querySelectorAll('[data-emp-wf-view]').forEach((btn) => {
          btn.classList.toggle('active', btn.getAttribute('data-emp-wf-view') === mode);
        });
      }
      if (!wrap || !radialRoot) return;
      if (mode === 'radial') {
        wrap.classList.add('emp-wf-diagram-wrap--radial');
        mermaidBlocks.forEach((el) => {
          el.hidden = true;
        });
        radialRoot.hidden = false;
        renderRadial(radialRoot).catch(() => { });
      } else {
        wrap.classList.remove('emp-wf-diagram-wrap--radial');
        mermaidBlocks.forEach((el) => {
          el.hidden = false;
        });
        radialRoot.hidden = true;
        if (wasRadial && typeof window.__empWfShowMermaid === 'function') {
          window.__empWfShowMermaid();
        } else if (
          typeof EmployeeWorkflow !== 'undefined' &&
          typeof EmployeeWorkflow.renderArchitectureDiagram === 'function'
        ) {
          EmployeeWorkflow.renderArchitectureDiagram();
        }
      }
      if (prevView !== mode) dispatchViewChange(prevView, mode, 'setView');
    } finally {
      switchingView = false;
    }
  }

  /** 仅切换 DOM 到 Mermaid 分段模式（全页用） */
  function ensureMermaidView() {
    const wrap = document.getElementById('emp-wf-arch-diagram');
    const radialRoot = document.getElementById('emp-wf-radial-root');
    if (!wrap || !radialRoot) return;
    const prev = currentView;
    currentView = 'mermaid';
    wrap.classList.remove('emp-wf-diagram-wrap--radial');
    wrap.querySelectorAll('.mermaid.emp-wf-mermaid, .emp-wf-mermaid-part-label').forEach((el) => {
      el.hidden = false;
    });
    radialRoot.hidden = true;
    const toolbar = document.querySelector('.emp-wf-diagram-toolbar');
    if (toolbar) {
      toolbar.querySelectorAll('[data-emp-wf-view]').forEach((btn) => {
        btn.classList.toggle('active', btn.getAttribute('data-emp-wf-view') === 'mermaid');
      });
    }
    if (prev !== 'mermaid') dispatchViewChange(prev, 'mermaid', 'ensureMermaidView');
  }

  /** 嵌入运维台：单条日更时间轴（dagre TB 全链路，非三段 Mermaid） */
  function ensureRadialView() {
    const wrap = document.getElementById('emp-wf-arch-diagram');
    const radialRoot = document.getElementById('emp-wf-radial-root');
    if (!wrap || !radialRoot) return;
    const prev = currentView;
    currentView = 'radial';
    wrap.classList.add('emp-wf-diagram-wrap--radial');
    wrap.querySelectorAll('.mermaid.emp-wf-mermaid, .emp-wf-mermaid-part-label').forEach((el) => {
      el.hidden = true;
    });
    radialRoot.hidden = false;
    const toolbar = document.querySelector('.emp-wf-diagram-toolbar');
    if (toolbar) {
      toolbar.querySelectorAll('[data-emp-wf-view]').forEach((btn) => {
        btn.classList.toggle('active', btn.getAttribute('data-emp-wf-view') === 'radial');
      });
    }
    if (prev !== 'radial') dispatchViewChange(prev, 'radial', 'ensureRadialView');
  }

  function scrollDiagramToTop() {
    const wrap = document.getElementById('emp-wf-arch-diagram');
    if (wrap) wrap.scrollTop = 0;
    const host = document.getElementById('emp-wf-radial-root');
    const viewport = host && host.querySelector('.emp-wf-radial-viewport');
    const stage = host && host.querySelector('.emp-wf-radial-stage');
    host?.__empWfPanZoom?.reset?.();
    window.scrollTo(0, 0);
  }

  function bindToolbar() {
    const toolbar = document.querySelector('.emp-wf-diagram-toolbar');
    if (!toolbar || toolbar.getAttribute('data-bound') === '1') return;
    toolbar.setAttribute('data-bound', '1');
    const controls = getMaintenanceSyncControls();
    setMaintenanceSyncStatus('等待运行时状态加载…');
    if (controls.syncBtn) {
      controls.syncBtn.disabled = true;
      if (!controls.syncBtn.__empWfBound) {
        controls.syncBtn.__empWfBound = true;
        controls.syncBtn.addEventListener('click', async () => {
          const root = document.getElementById('emp-wf-radial-root');
          const refresh = root && root.__empWfRuntimeRefreshStatus;
          controls.syncBtn.disabled = true;
          controls.syncBtn.textContent = '补齐中…';
          setMaintenanceSyncStatus('自维护任务提交中…', 'running');
          try {
            const r = await syncMissingEvidenceBacklog(32);
            const added = Number(r && r.added ? r.added : 0);
            const skipped = Number(r && r.skipped ? r.skipped : 0);
            const total = Number(r && r.total_missing ? r.total_missing : 0);
            const chunks = [];
            if (!Number.isNaN(added)) chunks.push(`已入队 ${added}`);
            if (!Number.isNaN(skipped)) chunks.push(`已存在 ${skipped}`);
            if (!Number.isNaN(total)) chunks.push(`缺证 ${total}`);
            setMaintenanceSyncStatus(`补齐完成：${chunks.length ? chunks.join('，') : '任务已触发'}`, 'ok');
            if (typeof refresh === 'function') {
              setMaintenanceSyncStatus('自维护完成，刷新状态…', 'running');
              await refresh();
            }
          } catch (err) {
            setMaintenanceSyncStatus(`补齐失败：${err && err.message ? err.message : String(err || 'unknown')}`, 'error');
          } finally {
            controls.syncBtn.textContent = '自维护：补齐缺证';
            controls.syncBtn.disabled = false;
          }
        });
      }
    }
  }

  function resolveInitialView() {
    return 'radial';
  }

  function activate() {
    bindToolbar();
    ensureRadialView();
    const root = document.getElementById('emp-wf-radial-root');
    if (root) renderRadial(root).catch(() => { });
  }

  function boot() {
    try {
      validateSchema();
    } catch (err) {
      console.error('[emp-wf-radial] schema 校验失败：', err);
      throw err;
    }
    if (document.getElementById('emp-wf-arch-diagram')) bindToolbar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  return {
    activate,
    setView,
    ensureMermaidView,
    ensureRadialView,
    bindToolbar,
    renderRadial,
    scrollDiagramToTop,
    /* 对接契约：版本号 + 标签解析器（多模型协作用） */
    SOT_VERSION,
    setLabelResolver,
    fetchRuntimeStatus,
    applyRuntimeStatusToLayer,
  };
})();

window.EmpWfRadialGraph = EmpWfRadialGraph;
