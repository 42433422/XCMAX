# Staging 监控栈部署 Runbook

> **用途**：计划 2026-06 T34–T38 的**可执行步骤**；不在本机伪造 staging 指标或截图。  
> **前置**：具备 staging K8s 集群、`kubectl` 上下文、Grafana 管理员凭据（见 `grafana/grafana-secret.yaml.example`）。  
> **阻塞**：T36–T37 需 staging 7 天流量或 k6 + PNG — 见 [`specs/BLOCKERS.md`](../../../specs/BLOCKERS.md)。

---

## 0. 前置检查（部署前 / 解除阻塞前）

```bash
cd FHD

# 仓内路径 + promtool +（可选）kubectl / API / Grafana
bash scripts/observability/staging_preflight.sh --check-only

# 仅校验本地 compose 路径（无需 Docker / 集群）
bash scripts/observability/local_stack_up.sh --check-only
```

| 检查项 | 命令 / 位置 | 通过标准 |
|--------|-------------|----------|
| 告警规则语法 | `promtool check rules k8s/monitoring/prometheus/alert_rules.yml` | exit 0 |
| 命名空间 | `kubectl get ns xcagi-staging` | 存在或 `create namespace` |
| Prometheus Pod | `kubectl -n xcagi-staging get pods -l app=prometheus` | Running |
| Grafana Pod | `kubectl -n xcagi-staging get pods -l app=grafana` | Running |
| API `/metrics` | staging API Service 可达 | Prometheus targets UP |
| 7 天验收模板 | [`docs/evidence/slo/acceptance-TEMPLATE.yaml`](../../docs/evidence/slo/acceptance-TEMPLATE.yaml) | 已存在；`acceptance-*.yaml` **数值待填** |

---

## 1. 目标

在 **staging** 命名空间部署：

1. Prometheus（抓取 API / NeuroBus / Mod 指标）
2. Grafana（自动 provisioning 数据源 + 仪表盘）
3. Alertmanager（可选，与 `alert_rules.yml` 对齐）

**验收（T36–T37）**：

- Grafana 可打开 `xcagi-slo`、`xcagi-revenue` 面板
- 连续 **≥ 7 天**真实 scrape，**或** k6 压测补量 + 面板有真实时序
- 四域 PNG 入库 [`docs/evidence/slo/`](../../docs/evidence/slo/)，并按 [`docs/evidence/slo/README.md`](../../docs/evidence/slo/README.md) 填写 `acceptance-*.yaml`
- **禁止**无流量伪造曲线或填假基线

---

## 2. 部署步骤

### 2.1 命名空间与密钥

```bash
export KUBECONFIG=/path/to/staging.kubeconfig
export NS=xcagi-staging

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# Grafana admin（勿提交真实 secret）
cp k8s/monitoring/grafana/grafana-secret.yaml.example /tmp/grafana-secret.yaml
# 编辑 GF_SECURITY_ADMIN_PASSWORD 等后：
kubectl -n "$NS" apply -f /tmp/grafana-secret.yaml
rm -f /tmp/grafana-secret.yaml   # 勿留明文于 /tmp
```

### 2.2 Prometheus

```bash
cd FHD
kubectl apply -k k8s/monitoring/prometheus -n "$NS"

kubectl -n "$NS" get pods -l app=prometheus
kubectl -n "$NS" wait --for=condition=ready pod -l app=prometheus --timeout=120s

promtool check rules k8s/monitoring/prometheus/alert_rules.yml
```

确认 `prometheus/prometheus.yml` 中 `job_name: xcagi-backend` 的 `targets` 指向 **staging** API Service（按环境改 `static_configs` 或接入 ServiceMonitor）。

验证抓取：

```bash
kubectl -n "$NS" port-forward svc/prometheus 9090:9090 &
open http://localhost:9090/targets   # xcagi-backend 应为 UP
```

### 2.3 Grafana + 仪表盘

```bash
kubectl apply -k k8s/monitoring/grafana -n "$NS"
kubectl -n "$NS" wait --for=condition=ready pod -l app=grafana --timeout=120s

kubectl -n "$NS" port-forward svc/grafana 3000:3000
```

浏览器 `http://localhost:3000`，确认 **Dashboards → XCAGI** 中出现：

| UID / 文件 | 说明 | M0 Panel |
|------------|------|----------|
| `xcagi-slo.json` | SLO 汇总（T38 数据源） | 1 / 3 / 7 |
| `xcagi-mod-store.json` | Mod / DB | 5 |
| `xcagi-revenue.json` | 收入/漏斗（T35） | — |
| `xcagi-api-overview.json` | API P95 / 错误率 | k6 期间观察 |

若面板无数据：检查 Prometheus datasource（`grafana/provisioning/datasources/`）与 scrape 标签 `job=xcagi-backend` 是否一致。

### 2.4 Alertmanager（可选）

```bash
kubectl apply -k k8s/monitoring/alertmanager -n "$NS"
# 路由与 receiver 见 alertmanager/alertmanager.yml
```

与 `prometheus/alert_rules.yml` 中 `team` / `severity` label 对齐；staging 可先用 `null` receiver 或 Slack webhook 测试通道。

### 2.5 Import 补充仪表盘（T35）

仓内 JSON 已通过 Kustomize 挂载；若需手动 import：

1. Grafana → **Dashboards** → **Import**
2. Upload `k8s/monitoring/grafana/dashboards/xcagi-revenue.json`
3. 选择 Prometheus 数据源 → **Import**

### 2.6 流量与截图（T36–T37）

**二选一或组合**（均需**真实**时间序列，禁止静态假图）：

#### A. 7 天 staging 自然流量

1. 保持 scrape 与 API 部署稳定 **≥ 7 天**（记录 `window_start` / `window_end`）
2. Grafana `xcagi-slo` → 时间范围 **Last 7 days**
3. 四域 Export PNG 或脚本导出：

```bash
export GRAFANA_URL=http://localhost:3000   # port-forward 后
export GRAFANA_USER=admin
export GRAFANA_PASS='***'
TIME_RANGE=now-7d bash scripts/observability/export_m0_panels.sh --prefix staging
```

4. 复制验收模板并填数（**仅从面板读数填写**）：

```bash
cp docs/evidence/slo/acceptance-TEMPLATE.yaml docs/evidence/slo/acceptance-YYYYMMDD.yaml
# 或见 docs/evidence/slo/README.md §2 内联 YAML
```

#### B. k6 压测（短时补量）

```bash
export BASE_URL=https://api.staging.example   # 真实 staging URL

# 前置检查（不跑压测）
bash scripts/observability/k6_smoke.sh --check-only

# 执行 smoke（复用 scripts/loadtest/smoke.js）
bash scripts/observability/k6_smoke.sh

# 或完整 load（需评估 staging 容量）
# k6 run scripts/loadtest/load.js
```

压测期间在 `xcagi-api-overview` 观察 P95 / 5xx；**k6  alone 不能替代 7 天窗口**，需在 `acceptance-*.yaml` 的 `observation_mode` 中说明。

#### 入库

```bash
# 手动 Export 时命名示例：
# docs/evidence/slo/grafana-staging-m0-api-availability-202609.png
git add docs/evidence/slo/*.png docs/evidence/slo/acceptance-*.yaml
```

字段清单与通过条件：[`docs/evidence/slo/README.md`](../../docs/evidence/slo/README.md)。

### 2.7 更新 SLO 文档（T38）

编辑 [`docs/SLO.md`](../../docs/SLO.md)（若尚未创建则 T38 新建）文首「数据源」：

- 填入 staging Grafana 外链（或内网 URL + 只读账号说明）
- 「当前基线」改为面板读数 + 截图路径（与 `acceptance-*.yaml` 一致）
- 同步 [`docs/CLAIMED_VS_ACTUAL.md`](../../docs/CLAIMED_VS_ACTUAL.md) SLO 行

---

## 3. 故障排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| Targets DOWN | Service 名 / 端口与 `prometheus.yml` 不符 | `kubectl get svc -n $NS`，改 targets 或 ServiceMonitor |
| 面板 No data | `job` 变量与 scrape label 不一致 | 对比 `/metrics` 与 Prometheus `up{job=...}` |
| render API 401 | Grafana 凭据错误或 secret 未 apply | 检查 `grafana-secret`、port-forward |
| 7 天曲线中断 | 部署重启 / scrape 失败 | 在 `acceptance-*.yaml` `notes` 记录缺口；**勿**插值伪造 |
| k6 全失败 | BASE_URL / VPN / 证书 | `curl -v $BASE_URL/api/health` |

---

## 4. 回滚

```bash
kubectl delete -k k8s/monitoring/grafana -n "$NS"
kubectl delete -k k8s/monitoring/prometheus -n "$NS"
# 可选：kubectl delete -k k8s/monitoring/alertmanager -n "$NS"
```

不影响应用 Deployment；仅移除监控组件。

---

## 5. 关联

| 文档 / 脚本 | 说明 |
|-------------|------|
| [`README.md`](README.md) | 仓内监控总览 |
| [`docs/evidence/slo/README.md`](../../docs/evidence/slo/README.md) | M0 四域 + **7 天验收 YAML 模板** |
| [`scripts/observability/README.md`](../../scripts/observability/README.md) | 本地栈、k6、导出脚本 |
| [`specs/BLOCKERS.md`](../../../specs/BLOCKERS.md) | T36–T37 阻塞 SSOT |
| [`docs/M0-remaining-gaps.md`](../../docs/M0-remaining-gaps.md) | M0 剩余三项缺口 |
