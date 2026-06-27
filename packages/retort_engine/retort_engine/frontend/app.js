const $ = id => document.getElementById(id);
const canvas = $("blackholeCanvas");
const ctx = canvas.getContext("2d");
const state = {
  mode: "github",
  running: false,
  tasks: [],
  llmTaskId: "",
  llmParallel: false,
  absorption: null,
  events: [],
  progress: {timer: 0, active: false, started: 0, duration: 0, percent: 0, phase: "evidence", title: "等待深评"}
};
const DEEP_REVIEW_WAIT_SECONDS = 240;
const progressPlan = [
  {key: "evidence", title: "证据采集", detail: "读取项目与门禁证据"},
  {key: "dispatch", title: "派发排比", detail: "等待排比 LLM 接收任务"},
  {key: "reasoning", title: "深度推理", detail: "等待排比 LLM 对证据打分"},
  {key: "scoring", title: "校准评分", detail: "要求返回结构化分数"},
  {key: "record", title: "保留记录", detail: "只保存完成的深评结果"}
];

const dimensionText = {
  product_level: "项目水平",
  architecture_depth: "架构深度",
  test_gate_evidence: "测试门禁",
  api_contract_quality: "接口契约",
  operational_readiness: "运行就绪",
  evolution_readiness: "进化就绪",
  external_ingestion: "外部摄取",
  comparative_analysis_depth: "对比深度",
  absorption_tasking: "吸收任务",
  employee_execution_integration: "员工执行",
  feedback_loop_closure: "反馈闭环",
  product_operability: "产品可用性",
  safety_license_gate: "安全许可",
  branch_absorption_workflow: "分支吸收",
  retort_product_maturity: "Retort 成熟度",
  evidence_loop_score: "证据闭环",
  capability_absorption_score: "能力吸收",
  calibrated_overall: "校准总分"
};
const statusText = {
  tasks_generated: "已生成吸收任务",
  absorption_execution_applied: "已执行真实吸收",
  absorption_execution_failed: "真实吸收失败",
  applied: "CLI 已改代码",
  noop: "CLI 无新增改动",
  failed: "CLI 执行失败",
  timeout: "CLI 执行超时",
  disabled: "未启用",
  no_external_advantage_found: "未发现外部优势",
  blocked_by_branch_workflow: "分支流程阻断",
  branch_created: "已创建吸收分支",
  merged: "已合并",
  converged: "已收敛",
  blocked: "已阻断",
  max_rounds: "达到轮次上限",
  awaiting_execution_evidence: "等待执行证据",
  internalized_by_self_evolution: "已由反问内化",
  closed_loop_verified: "闭环证据已验证",
  closed_loop_evidence_required_before_scores_can_pass: "缺少闭环证据，不能通过高分门槛",
  all_scores_strictly_above_threshold: "全部分数已超过阈值",
  max_rounds_reached_before_all_scores_passed: "达到轮次上限但仍有分数未通过",
  ready: "就绪",
  saturated: "已饱和",
  not_saturated: "未饱和",
  needs_attention: "需要处理"
};
const taskText = {
  "Absorb stronger implementation depth": "吸收更强实现深度",
  "Absorb better user experience": "吸收更好的用户体验",
  "Absorb better operational gates": "吸收更强运行门禁",
  "Adopt deterministic review pipeline stages": "接入确定性审查流水线",
  "Add external file grouping before deep comparison": "深度对比前增加外部文件分组",
  "Add absorption quality benchmark counters": "增加吸收质量基准计数",
  "Expose Retort absorption through plugin friendly commands": "提供适合插件调用的吸收命令"
};
const ownerText = {"fhd-core-maintainer": "核心维护", "market-frontend-dev": "前端体验", "deploy-release-officer": "发布运维", "test-qa-runner": "测试门禁"};

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
const ease = v => v < .5 ? 2 * v * v : 1 - Math.pow(-2 * v + 2, 2) / 2;
const labelOf = v => dimensionText[v] || statusText[v] || taskText[v] || String(v || "");
const shortPath = value => String(value || "").replace(/^.*\/packages\/retort_engine\//, "").replace(/^.*\/XCMAX\//, "");
const titleOf = v => {
  const text = String(v || "");
  const match = text.match(/^Raise (.+) above (\d+)$/);
  return match ? `将${labelOf(match[1])}提升到 ${match[2]} 以上` : labelOf(text);
};

function setRunning(running, text) {
  state.running = running;
  if (text) $("statusText").textContent = text;
  for (const id of ["assessBtn", "absorbBtn", "evolveBtn", "llmReviewBtn", "llmParallelBtn", "llmStatusBtn", "radarBtn", "loopBtn", "saturationBtn"]) {
    const el = $(id);
    if (el) el.disabled = running;
  }
}

function formatDuration(seconds) {
  const safe = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return minutes ? `${minutes}:${String(rest).padStart(2, "0")}` : `${rest}s`;
}

function stopProgressTimer() {
  if (!state.progress.timer) return;
  clearInterval(state.progress.timer);
  state.progress.timer = 0;
}

function progressPhase(ratio) {
  if (ratio < .12) return "evidence";
  if (ratio < .24) return "dispatch";
  if (ratio < .78) return "reasoning";
  if (ratio < .94) return "scoring";
  return "record";
}

function progressMeta(key) {
  return progressPlan.find(item => item.key === key) || progressPlan[0];
}

function renderProgress(percent, title, phaseKey, elapsed, detail, mode) {
  const root = $("deepProgress");
  if (!root) return;
  const safePercent = clamp(Number(percent) || 0, 0, 100);
  root.className = `deep-progress ${mode}`;
  root.style.setProperty("--progress", `${safePercent}%`);
  $("progressTitle").textContent = title;
  $("progressPercent").textContent = mode === "running" ? `估算 ${Math.round(safePercent)}%` : mode === "fail" ? "未完成" : `${Math.round(safePercent)}%`;
  $("progressElapsed").textContent = `耗时 ${formatDuration(elapsed)}`;
  $("progressEta").textContent = detail;
  const phaseIndex = Math.max(0, progressPlan.findIndex(item => item.key === phaseKey));
  document.querySelectorAll("#progressSteps span").forEach((step, index) => {
    step.className = "";
    if (mode === "done") step.classList.add("done");
    else if (mode !== "idle" && index < phaseIndex) step.classList.add("done");
    else if (mode !== "idle" && index === phaseIndex) step.classList.add("active");
  });
}

function updateProgress() {
  if (!state.progress.active) return;
  const elapsed = (performance.now() - state.progress.started) / 1000;
  const duration = Math.max(10, Number(state.progress.duration) || DEEP_REVIEW_WAIT_SECONDS);
  const ratio = clamp(elapsed / duration, 0, 1);
  const phaseKey = progressPhase(ratio);
  const phase = progressMeta(phaseKey);
  const estimated = clamp(4 + ease(clamp(ratio, 0, .96)) * 88, 4, 92);
  state.progress.percent = estimated;
  state.progress.phase = phaseKey;
  const remaining = Math.max(0, duration - elapsed);
  const detail = remaining > 0 ? `${phase.detail} · 剩余上限 ${formatDuration(remaining)}` : `${phase.detail} · 等待排比返回`;
  renderProgress(estimated, `${state.progress.title} · ${phase.title}`, phaseKey, elapsed, detail, "running");
}

function beginProgress(title, seconds = DEEP_REVIEW_WAIT_SECONDS) {
  stopProgressTimer();
  state.progress.active = true;
  state.progress.started = performance.now();
  state.progress.duration = Math.max(10, Number(seconds) || DEEP_REVIEW_WAIT_SECONDS);
  state.progress.percent = 4;
  state.progress.phase = "evidence";
  state.progress.title = title;
  renderProgress(4, `${title} · 证据采集`, "evidence", 0, "读取项目与门禁证据", "running");
  state.progress.timer = setInterval(updateProgress, 250);
}

function completeProgress(title = "深评完成") {
  const elapsed = state.progress.started ? (performance.now() - state.progress.started) / 1000 : 0;
  stopProgressTimer();
  state.progress.active = false;
  state.progress.percent = 100;
  state.progress.phase = "record";
  renderProgress(100, title, "record", elapsed, "排比 LLM 深评已返回，记录已保留", "done");
}

function failProgress(message) {
  const elapsed = state.progress.started ? (performance.now() - state.progress.started) / 1000 : 0;
  const percent = state.progress.percent || 0;
  const phase = state.progress.phase || "evidence";
  stopProgressTimer();
  state.progress.active = false;
  renderProgress(percent, "深评阻断", phase, elapsed, `未完成，不保留评分：${message}`, "fail");
}

function resetProgress() {
  stopProgressTimer();
  state.progress.active = false;
  state.progress.percent = 0;
  state.progress.phase = "evidence";
  renderProgress(0, "等待深评", "evidence", 0, "点击深评后开始", "idle");
}

function pushEvent(title, detail = "", level = "info") {
  state.events.unshift({title, detail, level, at: new Date().toLocaleTimeString("zh-CN", {hour12: false})});
  state.events = state.events.slice(0, 8);
  renderEvents();
}

function renderEvents() {
  const target = $("eventList");
  if (!target) return;
  target.textContent = "";
  for (const item of state.events) {
    const row = document.createElement("div");
    row.className = `event ${item.level}`;
    const time = document.createElement("span");
    time.textContent = item.at;
    const body = document.createElement("b");
    body.textContent = item.title;
    const detail = document.createElement("em");
    detail.textContent = item.detail;
    row.append(time, body, detail);
    target.appendChild(row);
  }
}

function setMode(mode) {
  state.mode = mode;
  $("sourceGithub").classList.toggle("active", mode === "github");
  $("sourceFolder").classList.toggle("active", mode === "folder");
  $("githubRow").classList.toggle("hidden", mode !== "github");
  $("folderRow").classList.toggle("hidden", mode !== "folder");
}

function body() {
  const own = $("ownProjectFolder").value.trim();
  const out = {
    own_project: own,
    project: own,
    branch_workflow: $("branchWorkflow").checked,
    merge_after: $("mergeAfter").checked,
    run_local_gates: $("runGates").checked,
    use_llm: true,
    wait_llm_sec: DEEP_REVIEW_WAIT_SECONDS,
    require_deep_review: true,
    execute_absorption: true,
    execution_timeout_sec: 1800,
    employee_queue: `${own}/.retort/employee_queue.jsonl`,
    history_store: `${own}/.retort/retort_history.sqlite`
  };
  if (state.mode === "github") out.github_url = $("githubUrl").value.trim();
  else out.external_path = $("externalProjectFolder").value.trim();
  return out;
}

async function api(path, payload) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || "request failed");
  return j;
}

function scoreValue(assessment, fallback) {
  const scores = assessment?.scores || [];
  for (const dimension of ["calibrated_overall", "product_level", "retort_product_maturity"]) {
    const item = scores.find(score => score.dimension === dimension);
    if (item) return Number(item.value);
  }
  return fallback;
}

function scoreSource(assessment) {
  return String(assessment?.metadata?.score_source || "");
}

function assertDeepAssessment(assessment) {
  if (scoreSource(assessment) === "paibi_llm") return;
  const status = assessment?.llm_review_status?.status || assessment?.llm_review?.dispatch?.status || assessment?.llm_review?.status || "未完成";
  throw new Error(`排比 LLM 深评${status}，本次评分不保留`);
}

function fileCountFrom(assessment) {
  const evidence = assessment?.evidence || [];
  const row = evidence.map(String).find(item => item.startsWith("source_files="));
  return row ? Number(row.replace("source_files=", "")) || 0 : 0;
}

function sourceName(source) {
  const text = String(source || "");
  const github = text.match(/github\.com[:/]([^/\s#?]+\/[^/\s#?]+)/);
  if (github) return github[1].replace(/\.git$/, "");
  return text.split("/").filter(Boolean).slice(-2).join("/") || "外部项目";
}

function beginAbsorption(payload) {
  const source = payload.github_url || payload.external_path || "";
  const volume = clamp((source.length + (payload.own_project || "").length * .35) / 120, .35, 1.65);
  state.absorption = {
    started: performance.now(),
    source,
    name: sourceName(source),
    volume,
    absorb: .7,
    externalScore: null,
    ownScore: null,
    externalFiles: 0,
    finishStarted: 0
  };
}

function updateAbsorption(result) {
  if (!state.absorption) return;
  const visual = result.absorption_visual || {};
  const external = visual.external || {};
  const own = visual.own || {};
  const externalScore = Number(external.score ?? scoreValue(result.external_assessment, null));
  const ownScore = Number(own.score ?? scoreValue(result.own_assessment, null));
  const externalFiles = Number(external.file_count ?? fileCountFrom(result.external_assessment));
  const tasks = (result.tasks || []).length;
  state.absorption.externalScore = Number.isFinite(externalScore) ? externalScore : null;
  state.absorption.ownScore = Number.isFinite(ownScore) ? ownScore : null;
  state.absorption.externalFiles = externalFiles;
  state.absorption.volume = clamp(.55 + Math.log10(externalFiles + 1) * .42 + (state.absorption.externalScore || 70) / 280, .6, 2.25);
  state.absorption.absorb = clamp(.68 + tasks * .09 + ((state.absorption.externalScore || 70) - (state.absorption.ownScore || 70)) * .012, .75, 1.9);
}

function finishAbsorption() {
  if (!state.absorption) return wait(0);
  state.absorption.finishStarted = performance.now() + 650;
  return wait(3700);
}

function cancelAbsorption() {
  if (!state.absorption) return;
  state.absorption.finishStarted = performance.now();
}

function renderRows(target, list, limit = 6) {
  target.innerHTML = "";
  const scores = list || [];
  const pick = scores.filter(s => ["product_level", "retort_product_maturity", "external_ingestion", "comparative_analysis_depth", "branch_absorption_workflow", "calibrated_overall"].includes(s.dimension));
  const rows = (pick.length ? pick : scores).slice(0, limit);
  for (const s of rows) {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `<span>${labelOf(s.dimension)}</span><b>${Math.round(s.value)}</b><div class="meter"><i style="--w:${s.value}%"></i></div>`;
    target.appendChild(row);
  }
  return rows;
}

function scores(list) {
  const rows = renderRows($("scoreGrid"), list);
  const overall = (list || []).find(item => item.dimension === "calibrated_overall");
  $("coreScore").textContent = overall ? Math.round(overall.value) : (rows[0] ? Math.round(rows[0].value) : "--");
}

function capabilityAudit(assessment) {
  const audit = assessment?.metadata?.capability_absorption_audit;
  const target = $("capabilityState");
  if (!target) return;
  target.textContent = "";
  if (!audit) {
    target.textContent = "未评估";
    return;
  }
  const rows = [
    ["能力分", Math.round(Number(audit.score || 0))],
    ["总分上限", Math.round(Number(audit.overall_cap || 0))],
    ["外部项目", Number(audit.external_project_count || 0)],
    ["员工模式", audit.employee_execution_mode || "无"],
    ["原因", labelOf(audit.reason) || audit.reason || ""]
  ];
  for (const [k, v] of rows) {
    const row = document.createElement("div");
    row.className = "kv";
    row.append(Object.assign(document.createElement("span"), {textContent: k}), Object.assign(document.createElement("b"), {textContent: String(v)}));
    target.appendChild(row);
  }
  const behavior = [...(audit.behavior_source_files || []), ...(audit.behavior_test_files || [])].slice(0, 5);
  if (behavior.length) {
    const list = document.createElement("div");
    list.className = "filelist";
    for (const file of behavior) {
      const item = document.createElement("code");
      item.textContent = shortPath(file);
      list.appendChild(item);
    }
    target.appendChild(list);
  }
}

function externalScores(assessment, visual) {
  const grid = $("externalScoreGrid");
  if (!grid) return;
  if (!assessment?.scores?.length) {
    grid.innerHTML = "<div class=\"empty\">未运行</div>";
    return;
  }
  renderRows(grid, assessment.scores, 4);
  const meta = document.createElement("div");
  meta.className = "mini";
  meta.textContent = `文件 ${visual?.external?.file_count ?? fileCountFrom(assessment)} · 核心分 ${Math.round(scoreValue(assessment, 0))}`;
  grid.appendChild(meta);
}

function evidence(result) {
  const target = $("evidenceState");
  if (!target) return;
  target.textContent = "";
  const execution = result?.execution || {};
  const files = execution.changed_files || [];
  const gates = execution.gates || [];
  const lines = [
    ["外部来源", sourceName(result?.external_ref?.source || "")],
    ["吸收任务", String((result?.tasks || []).length)],
    ["改动文件", String(files.length)],
    ["门禁通过", gates.length ? `${gates.filter(gate => gate.ok).length}/${gates.length}` : "0/0"],
    ["运行耗时", execution.duration_sec == null ? "未知" : `${execution.duration_sec}s`],
  ];
  for (const [k, v] of lines) {
    const row = document.createElement("div");
    row.className = "kv";
    row.append(Object.assign(document.createElement("span"), {textContent: k}), Object.assign(document.createElement("b"), {textContent: v}));
    target.appendChild(row);
  }
  if (files.length) {
    const fileList = document.createElement("div");
    fileList.className = "filelist";
    for (const file of files.slice(0, 8)) {
      const code = document.createElement("code");
      code.textContent = shortPath(file);
      fileList.appendChild(code);
    }
    target.appendChild(fileList);
  }
}

function tasks(list) {
  $("taskList").innerHTML = "";
  for (const t of list) {
    const el = document.createElement("div");
    el.className = "task";
    el.innerHTML = `<b>${titleOf(t.title)}</b><div>${ownerText[t.owner_hint] || t.owner_hint} · ${t.priority}</div>`;
    $("taskList").appendChild(el);
  }
}

function renderKV(target, rows) {
  target.textContent = "";
  for (const [k, v] of rows) {
    const row = document.createElement("div");
    row.className = "kv";
    row.append(Object.assign(document.createElement("span"), {textContent: k}), Object.assign(document.createElement("b"), {textContent: String(v)}));
    target.appendChild(row);
  }
}

function renderCandidateTasks(candidates) {
  $("taskList").innerHTML = "";
  for (const item of candidates) {
    const el = document.createElement("div");
    el.className = "task";
    el.innerHTML = `<b>${item.full_name || sourceName(item.url)}</b><div>同类深度 ${item.similarity_depth_score || 0} · ${item.reason || ""}</div>`;
    $("taskList").appendChild(el);
  }
}

function renderRadar(result) {
  renderKV($("evidenceState"), [
    ["候选项目", result.summary?.candidate_count || 0],
    ["可吸收同类", result.summary?.accepted_count || 0],
    ["已吃过", result.summary?.already_absorbed_count || 0],
    ["最低同类分", result.summary?.min_score || 0],
  ]);
  renderCandidateTasks(result.candidates || []);
}

function renderLoop(result) {
  renderKV($("evidenceState"), [
    ["选择项目", result.summary?.selected_count || 0],
    ["完成项目", result.summary?.completed_count || 0],
    ["门禁通过", result.summary?.gates_passed_count || 0],
    ["剩余候选", result.summary?.remaining_candidate_count || 0],
  ]);
  const rows = (result.runs || []).map(run => ({
    full_name: run.candidate?.full_name || sourceName(run.candidate?.url),
    similarity_depth_score: run.candidate?.similarity_depth_score || 0,
    reason: `${labelOf(run.status)} · ${run.gates_passed ? "门禁通过" : "待验证"}`
  }));
  renderCandidateTasks(rows);
}

function renderSaturation(result) {
  renderKV($("evidenceState"), [
    ["状态", labelOf(result.status)],
    ["吸收次数", result.summary?.absorption_run_count || 0],
    ["近轮绿灯", result.summary?.recent_gate_green_count || 0],
    ["无新增深度", result.summary?.consecutive_no_new_core_depth_count || 0],
    ["剩余候选", result.summary?.remaining_candidate_count || 0],
  ]);
  renderCandidateTasks((result.recent_runs || []).map(run => ({
    full_name: sourceName(run.source),
    similarity_depth_score: run.new_core_signal_count,
    reason: `${run.gates_passed ? "门禁通过" : "门禁未过"} · 新深度 ${run.new_core_signal_count}`
  })));
}

function llm(review, status = null, assessment = null) {
  if (!review || review.enabled === false) {
    $("llmState").textContent = "排比 LLM 深评未完成，本次不保留评分";
    return;
  }
  const d = review.dispatch || review;
  if (d.task_id) state.llmTaskId = d.task_id;
  state.llmParallel = Boolean(review.parallel);
  if (scoreSource(assessment) === "paibi_llm") {
    const taskId = assessment?.metadata?.llm_task_id || status?.task_id || d.task_id || "";
    const level = status?.json_result?.level ? ` · ${status.json_result.level}` : "";
    $("llmState").textContent = `排比 LLM 深评完成${taskId ? `：${taskId}` : ""}${level}`;
    return;
  }
  if (status?.status) {
    $("llmState").textContent = `排比 LLM ${status.status}，未返回深评分；本次不保留评分`;
    return;
  }
  const prefix = state.llmParallel ? `已派发并发排比 ${d.subtask_count || review.panels?.length || 0} 个面板` : "已派发排比任务";
  $("llmState").textContent = d.status === "accepted" ? `${prefix}：${d.task_id || "等待任务 ID"}` : `已写入排比待发箱：${d.reason || d.status || "等待调度"}`;
  pushEvent("排比任务", d.task_id || d.reason || d.status || "已记录", d.status === "accepted" ? "ok" : "warn");
}

function executionState(execution) {
  const target = $("executionState");
  if (!target) return;
  if (!execution) {
    target.textContent = "未运行";
    return;
  }
  const files = execution.changed_files || [];
  const gates = execution.gates || [];
  const gateText = gates.length ? `${gates.filter(gate => gate.ok).length}/${gates.length}` : "未运行";
  target.textContent = "";
  const title = document.createElement("b");
  title.textContent = labelOf(execution.status) || execution.status;
  const meta = document.createElement("div");
  meta.textContent = `耗时 ${execution.duration_sec || 0}s · 改动 ${files.length} 个文件 · 门禁 ${gateText}`;
  target.append(title, meta);
  if (gates.length) {
    const list = document.createElement("div");
    list.className = "gates";
    for (const gate of gates) {
      const row = document.createElement("span");
      row.className = gate.ok ? "ok" : "bad";
      row.textContent = `${gate.ok ? "通过" : "失败"} ${gate.command?.slice(-3).join(" ") || ""}`;
      list.appendChild(row);
    }
    target.appendChild(list);
  }
}

async function assess() {
  setRunning(true, "排比 LLM 深评中");
  beginProgress("排比 LLM 深评", DEEP_REVIEW_WAIT_SECONDS);
  pushEvent("开始深评", shortPath($("ownProjectFolder").value.trim()));
  try {
    const r = await api("/api/assess", {project: $("ownProjectFolder").value.trim(), run_local_gates: $("runGates").checked, use_llm: true, wait_llm_sec: DEEP_REVIEW_WAIT_SECONDS, require_deep_review: true});
    llm(r.llm_review, r.llm_review_status, r);
    assertDeepAssessment(r);
    scores(r.scores);
    capabilityAudit(r);
    completeProgress("深评完成");
    $("statusText").textContent = "深评完成";
    pushEvent("深评完成", `排比 LLM 核心分 ${Math.round(scoreValue(r, 0))}`, "ok");
  } catch (e) {
    failProgress(e.message);
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
    pushEvent("深评失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function absorb() {
  setRunning(true, "评估双方项目");
  const payload = body();
  pushEvent("开始吸收", sourceName(payload.github_url || payload.external_path || ""), "info");
  beginAbsorption(payload);
  try {
    const r = await api("/api/absorb", payload);
    updateAbsorption(r);
    scores(r.own_assessment.scores);
    capabilityAudit(r.own_assessment);
    externalScores(r.external_assessment, r.absorption_visual);
    executionState(r.execution);
    evidence(r);
    tasks(r.tasks || []);
    llm(r.llm_review);
    $("branchState").textContent = labelOf(r.branch_workflow?.status) || "尚未运行分支流程";
    $("statusText").textContent = labelOf(r.status);
    pushEvent("吸收完成", `${labelOf(r.status)} · 改动 ${(r.execution?.changed_files || []).length} 个文件`, r.execution?.gates_passed ? "ok" : "warn");
    await finishAbsorption();
  } catch (e) {
    cancelAbsorption();
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
    pushEvent("吸收失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function evolve() {
  setRunning(true, "排比 LLM 反问深评中");
  beginProgress("反问 LLM 深评", DEEP_REVIEW_WAIT_SECONDS);
  pushEvent("开始反问深评", "无限反问评分弱项");
  try {
    const r = await api("/api/self-evolve", {project: $("ownProjectFolder").value.trim(), run_local_gates: $("runGates").checked, max_rounds: 8, use_llm: true, wait_llm_sec: DEEP_REVIEW_WAIT_SECONDS, require_deep_review: true});
    llm(r.final_assessment?.llm_review || r.llm_review, r.final_assessment?.llm_review_status, r.final_assessment);
    assertDeepAssessment(r.final_assessment);
    scores(r.final_assessment.scores);
    capabilityAudit(r.final_assessment);
    tasks(r.tasks || []);
    completeProgress("反问深评完成");
    $("branchState").textContent = `${labelOf(r.status)}：${labelOf(r.stop_reason)}`;
    $("statusText").textContent = "已反问";
    pushEvent("反问深评完成", `${labelOf(r.status)} · ${labelOf(r.stop_reason)}`, r.status === "converged" ? "ok" : "warn");
  } catch (e) {
    failProgress(e.message);
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
    pushEvent("反问深评失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function similarRadar() {
  setRunning(true, "同类雷达扫描中");
  pushEvent("同类雷达", "扫描 GitHub PR reviewer 项目", "info");
  try {
    const r = await api("/api/similar-project-radar", {project: $("ownProjectFolder").value.trim(), query: "AI PR reviewer", limit: 10, min_score: 55});
    renderRadar(r);
    $("statusText").textContent = labelOf(r.status);
    $("branchState").textContent = `同类候选 ${r.summary?.accepted_count || 0} 个`;
    pushEvent("同类雷达完成", `候选 ${r.summary?.accepted_count || 0} 个`, "ok");
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
    pushEvent("同类雷达失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function similarLoop() {
  setRunning(true, "连续吸收同类项目");
  pushEvent("连续吸收", "按雷达排序吸收 3 个同类项目", "info");
  try {
    const r = await api("/api/similar-project-loop", {project: $("ownProjectFolder").value.trim(), limit: 3, min_score: 55, run_local_gates: $("runGates").checked, branch_workflow: $("branchWorkflow").checked, merge_after: $("mergeAfter").checked, allow_dirty_branch: true});
    renderLoop(r);
    renderSaturation(r.saturation);
    $("statusText").textContent = labelOf(r.status);
    $("branchState").textContent = `${labelOf(r.saturation?.status)} · 完成 ${r.summary?.completed_count || 0}`;
    pushEvent("连续吸收完成", `完成 ${r.summary?.completed_count || 0} 个 · ${labelOf(r.saturation?.status)}`, r.status === "ready" ? "ok" : "warn");
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
    pushEvent("连续吸收失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function saturationReport() {
  setRunning(true, "饱和判定中");
  pushEvent("饱和判定", "检查最近同类吸收是否还产生核心深度", "info");
  try {
    const r = await api("/api/absorption-saturation", {project: $("ownProjectFolder").value.trim(), recent_limit: 3});
    renderSaturation(r);
    $("statusText").textContent = labelOf(r.status);
    $("branchState").textContent = `${labelOf(r.status)} · 无新增深度 ${r.summary?.consecutive_no_new_core_depth_count || 0}`;
    pushEvent("饱和判定完成", labelOf(r.status), r.status === "saturated" ? "ok" : "warn");
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
    pushEvent("饱和判定失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function llmReview() {
  setRunning(true, "排比评审中");
  pushEvent("请求排比评审", "单评审员");
  try {
    const payload = body();
    const r = await api("/api/llm-review", {project: payload.project, mode: "manual", github_url: payload.github_url || "", external_path: payload.external_path || "", run_local_gates: payload.run_local_gates});
    llm(r);
    $("statusText").textContent = "已请求排比评审";
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("llmState").textContent = `错误：${e.message}`;
    pushEvent("排比失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function llmParallelReview() {
  setRunning(true, "并发排比中");
  pushEvent("请求并发排比", "证据/能力/阻塞三面板");
  try {
    const payload = body();
    const r = await api("/api/llm-review-parallel", {project: payload.project, mode: "parallel_assess", github_url: payload.github_url || "", external_path: payload.external_path || "", run_local_gates: payload.run_local_gates, max_parallel: 3});
    llm(r);
    $("statusText").textContent = "已请求并发排比";
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("llmState").textContent = `错误：${e.message}`;
    pushEvent("并发排比失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

async function llmStatus() {
  if (!state.llmTaskId) {
    $("llmState").textContent = "没有可同步的排比任务";
    return;
  }
  setRunning(true, "同步排比中");
  try {
    const r = await api(state.llmParallel ? "/api/llm-review-group-status" : "/api/llm-review-status", {task_id: state.llmTaskId});
    const json = r.json_result ? ` · JSON ${r.json_result.level || "已返回"}` : "";
    const blockers = r.unblock_tasks?.length ? ` · 解阻 ${r.unblock_tasks.length}` : "";
    $("llmState").textContent = `排比任务 ${r.status || "unknown"} · 子任务 ${r.subtasks?.map(s => s.status).join("/") || "无"}${json}${blockers}`;
    $("statusText").textContent = "已同步排比";
    pushEvent("排比同步", `${r.status || "unknown"}${blockers}`, r.unblock_tasks?.length ? "warn" : "ok");
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("llmState").textContent = `错误：${e.message}`;
    pushEvent("同步失败", e.message, "bad");
  } finally {
    setRunning(false);
  }
}

function star(i, w, h, t, dpr) {
  const seed = Math.sin(i * 981.17) * 43758.5453;
  const x = (seed - Math.floor(seed)) * w;
  const y = (((Math.sin(i * 427.41) * 43758.5453) % 1) + 1) % 1 * h;
  const tw = .35 + .65 * Math.sin(t * .7 + i);
  ctx.beginPath();
  ctx.fillStyle = `rgba(190,220,255,${.12 + .25 * tw})`;
  ctx.arc(x, y, (.45 + (i % 3) * .25) * dpr, 0, Math.PI * 2);
  ctx.fill();
}

function disk(cx, cy, w, h, t, dpr, scale, boost) {
  const speed = state.running ? 1.75 : .72;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-.22);
  ctx.globalCompositeOperation = "lighter";
  for (let i = 0; i < 34; i++) {
    const p = i / 33;
    const rx = w * (.205 + p * .205) * scale * (1 + boost * .04);
    const ry = h * (.035 + p * .064) * scale * (1 + boost * .06);
    const phase = t * speed + i * .18;
    const alpha = .035 + (1 - p) * .1;
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, 0, phase, phase + Math.PI * .95);
    ctx.strokeStyle = `rgba(77,211,255,${alpha * .65})`;
    ctx.lineWidth = (1.2 + p * 3.2) * dpr;
    ctx.stroke();
    ctx.beginPath();
    ctx.ellipse(0, 0, rx * .98, ry * 1.02, 0, phase + Math.PI * .92, phase + Math.PI * 1.95);
    ctx.strokeStyle = `rgba(255,184,82,${alpha * 1.45})`;
    ctx.lineWidth = (1.4 + p * 3.9) * dpr;
    ctx.stroke();
  }
  for (let i = 0; i < 130; i++) {
    const p = (i % 65) / 65;
    const a = i * .71 + t * speed * (.65 + (i % 7) * .035);
    const rx = w * (.18 + p * .27) * scale;
    const ry = h * (.031 + p * .081) * scale;
    const x = Math.cos(a) * rx;
    const y = Math.sin(a) * ry;
    const tail = 12 * dpr + p * 24 * dpr;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x - Math.sin(a) * tail, y + Math.cos(a) * tail * .22);
    ctx.strokeStyle = i % 4 ? `rgba(255,207,118,${.2 + p * .46})` : `rgba(94,218,255,${.18 + p * .35})`;
    ctx.lineWidth = (.8 + p * 1.5) * dpr;
    ctx.stroke();
  }
  ctx.restore();
}

function projectPlanet(x, y, radius, t, dpr, alpha) {
  if (radius <= 0 || alpha <= 0) return;
  const pulse = .5 + .5 * Math.sin(t * 2.1);
  const shear = Math.sin(t * .7) * .08;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.translate(x, y);
  ctx.rotate(-.34 + shear);
  for (let i = 0; i < 18; i++) {
    const a = i * .83 + t * (.58 + i * .012);
    const sx = Math.cos(a) * radius * (1.05 + (i % 5) * .08);
    const sy = Math.sin(a) * radius * (.42 + (i % 4) * .035);
    const len = radius * (.18 + (i % 4) * .055);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx - Math.sin(a) * len, sy + Math.cos(a) * len * .32);
    ctx.strokeStyle = i % 3 ? `rgba(255,203,112,${.2 * alpha})` : `rgba(93,232,219,${.22 * alpha})`;
    ctx.lineWidth = (.7 + (i % 3) * .25) * dpr;
    ctx.stroke();
  }
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  ctx.translate(x, y);
  ctx.rotate(-.18 + shear);
  const core = ctx.createRadialGradient(-radius * .38, -radius * .42, radius * .05, 0, 0, radius);
  core.addColorStop(0, `rgba(255,244,206,${alpha})`);
  core.addColorStop(.18, `rgba(93,232,219,${.94 * alpha})`);
  core.addColorStop(.5, `rgba(28,73,88,${.96 * alpha})`);
  core.addColorStop(.78, `rgba(10,20,28,${alpha})`);
  core.addColorStop(1, `rgba(3,7,10,${alpha})`);
  ctx.shadowColor = `rgba(255,203,112,${.42 * alpha})`;
  ctx.shadowBlur = (16 + pulse * 10) * dpr * alpha;
  ctx.beginPath();
  ctx.ellipse(0, 0, radius * 1.02, radius * .92, 0, 0, Math.PI * 2);
  ctx.fillStyle = core;
  ctx.fill();
  ctx.shadowBlur = 0;

  ctx.save();
  ctx.clip();
  ctx.globalCompositeOperation = "lighter";
  for (let i = -3; i <= 3; i++) {
    const yy = i * radius * .21 + Math.sin(t * 1.4 + i) * radius * .025;
    const grad = ctx.createLinearGradient(-radius, yy, radius, yy);
    grad.addColorStop(0, `rgba(93,232,219,0)`);
    grad.addColorStop(.35, `rgba(93,232,219,${.08 * alpha})`);
    grad.addColorStop(.58, `rgba(255,203,112,${.18 * alpha})`);
    grad.addColorStop(1, `rgba(255,203,112,0)`);
    ctx.beginPath();
    ctx.moveTo(-radius * 1.1, yy - radius * .18);
    ctx.bezierCurveTo(-radius * .35, yy + radius * .08, radius * .38, yy - radius * .08, radius * 1.1, yy + radius * .18);
    ctx.strokeStyle = grad;
    ctx.lineWidth = (1.1 + Math.abs(i) * .14) * dpr;
    ctx.stroke();
  }
  for (let i = 0; i < 7; i++) {
    const xx = -radius * .78 + i * radius * .26 + Math.sin(t + i) * radius * .025;
    ctx.beginPath();
    ctx.moveTo(xx, -radius * .68);
    ctx.lineTo(xx + radius * .38, radius * .66);
    ctx.strokeStyle = `rgba(255,255,255,${.035 * alpha})`;
    ctx.lineWidth = .8 * dpr;
    ctx.stroke();
  }
  ctx.restore();

  ctx.globalCompositeOperation = "lighter";
  ctx.beginPath();
  ctx.strokeStyle = `rgba(255,211,122,${.64 * alpha})`;
  ctx.lineWidth = 2.2 * dpr;
  ctx.ellipse(0, 0, radius * 1.08, radius * .97, 0, -.25, Math.PI * 1.36);
  ctx.stroke();

  ctx.beginPath();
  ctx.strokeStyle = `rgba(93,232,219,${.52 * alpha})`;
  ctx.lineWidth = 1.5 * dpr;
  ctx.ellipse(0, 0, radius * 1.19, radius * .48, .2, t * .85, t * .85 + Math.PI * 1.55);
  ctx.stroke();

  for (let i = 0; i < 9; i++) {
    const a = t * (.52 + i * .016) + i * .72;
    const px = Math.cos(a) * radius * (1.18 + (i % 3) * .11);
    const py = Math.sin(a) * radius * (.58 + (i % 4) * .04);
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(a + .8);
    ctx.fillStyle = i % 2 ? `rgba(255,203,112,${.28 * alpha})` : `rgba(93,232,219,${.3 * alpha})`;
    ctx.fillRect(-radius * .035, -radius * .012, radius * (.08 + (i % 3) * .018), radius * .024);
    ctx.restore();
  }
  ctx.restore();
}

function drawAbsorptionScene(cx, cy, r, w, h, t, dpr) {
  const a = state.absorption;
  if (!a) return {cx, cy, scale: 1, boost: 0};
  const now = performance.now();
  const pull = ease(clamp((now - a.started) / 1250, 0, 1));
  const consume = a.finishStarted ? ease(clamp((now - a.finishStarted) / 2600, 0, 1)) : 0;
  if (consume >= 1) {
    state.absorption = null;
    return {cx, cy, scale: 1, boost: 0};
  }
  const blackholeX = cx + w * .17 * pull;
  const blackholeY = cy - h * .015 * pull;
  const planetStartX = cx - r * .16;
  const planetLeftX = w * .24;
  const planetX = planetStartX + (planetLeftX - planetStartX) * pull + (blackholeX - planetLeftX) * consume;
  const planetY = cy + h * .02 * pull + (blackholeY - (cy + h * .02 * pull)) * consume;
  const scale = 1 - .18 * pull + .05 * consume;
  const scoreFactor = a.externalScore == null ? 1 : clamp(.82 + a.externalScore / 260, .9, 1.22);
  const planetRadius = r * (.047 + .026 * a.volume) * scoreFactor * (1 - consume * .88);
  const boost = (pull * .35 + consume * .95) * a.absorb;
  return {cx: blackholeX, cy: blackholeY, scale, boost, planetX, planetY, planetLeftX, planetRadius, pull, consume, name: a.name, externalScore: a.externalScore, ownScore: a.ownScore};
}

function drawAbsorptionPlanet(scene, cy, r, h, t, dpr) {
  if (!state.absorption || !scene.planetRadius) return;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.beginPath();
  ctx.strokeStyle = `rgba(255,190,96,${.26 * scene.pull * (1 - scene.consume)})`;
  ctx.lineWidth = 1.2 * dpr;
  ctx.setLineDash([7 * dpr, 12 * dpr]);
  ctx.moveTo(scene.planetLeftX, cy + h * .02);
  ctx.bezierCurveTo(scene.planetLeftX + r * .26, cy - h * .11, scene.cx - r * .24, cy + h * .18, scene.cx, scene.cy);
  ctx.stroke();
  ctx.setLineDash([]);
  for (let i = 0; i < 34; i++) {
    const q = i / 33;
    const tx = scene.planetX + (scene.cx - scene.planetX) * q;
    const ty = scene.planetY + (scene.cy - scene.planetY) * q;
    ctx.beginPath();
    ctx.fillStyle = `rgba(255,177,84,${(.08 + q * .28) * scene.pull * (1 - scene.consume)})`;
    ctx.arc(tx, ty, Math.max(.8 * dpr, scene.planetRadius * .075 * (1 - q)), 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  projectPlanet(scene.planetX, scene.planetY, Math.max(0, scene.planetRadius), t, dpr, scene.pull * (1 - scene.consume * .4));
  drawSceneLabel(scene.planetX, scene.planetY - scene.planetRadius - 18 * dpr, `${scene.name} ${scene.externalScore == null ? "评分中" : Math.round(scene.externalScore)}`, dpr, scene.pull * (1 - scene.consume * .55));
  drawSceneLabel(scene.cx, scene.cy + r * .19 * scene.scale, `主项目 ${scene.ownScore == null ? "" : Math.round(scene.ownScore)}`, dpr, scene.pull);
}

function drawSceneLabel(x, y, text, dpr, alpha) {
  if (alpha <= .04) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = `${12 * dpr}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const width = ctx.measureText(text).width + 18 * dpr;
  ctx.fillStyle = "rgba(3,7,12,.64)";
  ctx.strokeStyle = "rgba(255,255,255,.16)";
  roundRect(x - width / 2, y - 13 * dpr, width, 26 * dpr, 7 * dpr);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#dbeafe";
  ctx.fillText(text, x, y);
  ctx.restore();
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function draw() {
  const rect = canvas.getBoundingClientRect();
  const dpr = devicePixelRatio || 1;
  const w = Math.max(1, rect.width * dpr);
  const h = Math.max(1, rect.height * dpr);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const baseCx = w * .52;
  const baseCy = h * .49;
  const t = performance.now() / 1000;
  const r = Math.min(w, h);
  ctx.clearRect(0, 0, w, h);
  let bg = ctx.createRadialGradient(baseCx, baseCy, r * .05, baseCx, baseCy, r * .78);
  bg.addColorStop(0, "#020206");
  bg.addColorStop(.18, "#050812");
  bg.addColorStop(.55, "#09182a");
  bg.addColorStop(1, "#020306");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 180; i++) star(i, w, h, t, dpr);

  const scene = drawAbsorptionScene(baseCx, baseCy, r, w, h, t, dpr);
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  let halo = ctx.createRadialGradient(scene.cx, scene.cy, r * (.13 * scene.scale + scene.boost * .016), scene.cx, scene.cy, r * (.58 * scene.scale + scene.boost * .07));
  halo.addColorStop(0, `rgba(94,218,255,${.16 + scene.boost * .1})`);
  halo.addColorStop(.35, `rgba(255,184,82,${.1 + scene.boost * .12})`);
  halo.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = halo;
  ctx.fillRect(0, 0, w, h);
  ctx.restore();

  disk(scene.cx, scene.cy, w, h, t, dpr, scene.scale, scene.boost);
  drawAbsorptionPlanet(scene, baseCy, r, h, t, dpr);
  ctx.save();
  ctx.translate(scene.cx, scene.cy);
  ctx.globalCompositeOperation = "source-over";
  ctx.shadowColor = "rgba(0,0,0,.95)";
  ctx.shadowBlur = (34 + scene.boost * 16) * dpr;
  ctx.beginPath();
  ctx.fillStyle = "#000";
  ctx.arc(0, 0, r * (.142 * scene.scale + scene.boost * .024), 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  let ring = ctx.createRadialGradient(0, 0, r * (.126 * scene.scale + scene.boost * .018), 0, 0, r * (.174 * scene.scale + scene.boost * .035));
  ring.addColorStop(0, "rgba(0,0,0,0)");
  ring.addColorStop(.48, `rgba(255,211,122,${.9 + scene.boost * .08})`);
  ring.addColorStop(.63, `rgba(96,221,255,${.55 + scene.boost * .18})`);
  ring.addColorStop(1, "rgba(0,0,0,0)");
  ctx.beginPath();
  ctx.fillStyle = ring;
  ctx.arc(0, 0, r * (.18 * scene.scale + scene.boost * .04), 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.fillStyle = "#000";
  ctx.arc(0, 0, r * (.128 * scene.scale + scene.boost * .022), 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let i = 0; i < 42; i++) {
    const a = i * .63 - t * (state.running ? 1.6 : .7);
    const rr = r * (.2 + (i % 11) * .018 + scene.boost * .018) * scene.scale;
    const x = scene.cx + Math.cos(a) * rr * 1.58;
    const y = scene.cy + Math.sin(a) * rr * .45;
    ctx.beginPath();
    ctx.strokeStyle = `rgba(105,224,255,${.06 + (i % 5) * .025 + scene.boost * .025})`;
    ctx.lineWidth = (.8 + (i % 4) * .35) * dpr;
    ctx.arc(x, y, r * (.003 + (i % 3) * .001), 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
  requestAnimationFrame(draw);
}

$("sourceGithub").onclick = () => setMode("github");
$("sourceFolder").onclick = () => setMode("folder");
$("assessBtn").onclick = assess;
$("absorbBtn").onclick = absorb;
$("evolveBtn").onclick = evolve;
$("llmReviewBtn").onclick = llmReview;
$("llmParallelBtn").onclick = llmParallelReview;
$("llmStatusBtn").onclick = llmStatus;
$("radarBtn").onclick = similarRadar;
$("loopBtn").onclick = similarLoop;
$("saturationBtn").onclick = saturationReport;

async function loadDefaultProject() {
  try {
    const r = await fetch("/api/default-project");
    const j = await r.json();
    if (j.project) $("ownProjectFolder").value = j.project;
  } catch (_) {
    return;
  }
}

resetProgress();
externalScores(null);
loadDefaultProject();
draw();
