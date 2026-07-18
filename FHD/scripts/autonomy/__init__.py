"""XCMAX 服务器端自治平台（Phase 2）。

七元契约（与桌面端 FHD/desktop/autonomy/ 对称）：
  Signal / Diagnosis / Action / Policy / Adapter / RuntimeTruthSnapshot / AuditEntry

模块组成：
  - types.py: 七元契约的 Python dataclass / TypedDict 定义
  - rca_rules.py: signal kind → root_cause 映射
  - cvm_adapter.py: CvmAutonomyAdapter（采集 truth / 执行 6 action / 写 audit）
  - impact_predictor.py: 6 action 运行时预检（拦截不阻断）
  - cvm_autonomy_watcher.py: 主程序 + CLI 入口（cron SSH 触发）
  - policies/: 4 个 Policy（health_down / manifest_drift / disk_full / compose_unhealthy）
"""
