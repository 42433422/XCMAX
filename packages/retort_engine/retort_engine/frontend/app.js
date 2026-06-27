const $ = id => document.getElementById(id);
const canvas = $("blackholeCanvas");
const ctx = canvas.getContext("2d");
const state = {mode: "github", running: false, tasks: [], llmTaskId: "", absorption: null};

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
  calibrated_overall: "校准总分"
};
const statusText = {
  tasks_generated: "已生成吸收任务",
  no_external_advantage_found: "未发现外部优势",
  blocked_by_branch_workflow: "分支流程阻断",
  branch_created: "已创建吸收分支",
  merged: "已合并",
  disabled: "未启用",
  converged: "已收敛",
  blocked: "已阻断",
  max_rounds: "达到轮次上限",
  awaiting_execution_evidence: "等待执行证据",
  internalized_by_self_evolution: "已由反问内化",
  closed_loop_verified: "闭环证据已验证",
  closed_loop_evidence_required_before_scores_can_pass: "缺少闭环证据，不能通过高分门槛",
  all_scores_strictly_above_threshold: "全部分数已超过阈值",
  max_rounds_reached_before_all_scores_passed: "达到轮次上限但仍有分数未通过"
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
const titleOf = v => {
  const text = String(v || "");
  const match = text.match(/^Raise (.+) above (\d+)$/);
  return match ? `将${labelOf(match[1])}提升到 ${match[2]} 以上` : labelOf(text);
};

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
    use_llm: $("useLlm").checked,
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
  $("coreScore").textContent = rows[0] ? Math.round(rows[0].value) : "--";
}

function externalScores(assessment, visual) {
  const grid = $("externalScoreGrid");
  if (!grid) return;
  if (!assessment?.scores?.length) {
    grid.innerHTML = "<div class=\"empty\">等待外部项目评分</div>";
    return;
  }
  renderRows(grid, assessment.scores, 4);
  const meta = document.createElement("div");
  meta.className = "mini";
  meta.textContent = `文件 ${visual?.external?.file_count ?? fileCountFrom(assessment)} · 核心分 ${Math.round(scoreValue(assessment, 0))}`;
  grid.appendChild(meta);
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

function llm(review) {
  if (!review || review.enabled === false) {
    $("llmState").textContent = "排比 LLM 未启用";
    return;
  }
  const d = review.dispatch || review;
  if (d.task_id) state.llmTaskId = d.task_id;
  $("llmState").textContent = d.status === "accepted" ? `已派发排比任务：${d.task_id || "等待任务 ID"}` : `已写入排比待发箱：${d.reason || d.status || "等待调度"}`;
}

async function assess() {
  state.running = true;
  $("statusText").textContent = "评估中";
  try {
    const r = await api("/api/assess", {project: $("ownProjectFolder").value.trim(), run_local_gates: $("runGates").checked, use_llm: $("useLlm").checked});
    scores(r.scores);
    llm(r.llm_review);
    $("statusText").textContent = "已评估";
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
  } finally {
    state.running = false;
  }
}

async function absorb() {
  state.running = true;
  $("statusText").textContent = "评估双方项目";
  const payload = body();
  beginAbsorption(payload);
  try {
    const r = await api("/api/absorb", payload);
    updateAbsorption(r);
    scores(r.own_assessment.scores);
    externalScores(r.external_assessment, r.absorption_visual);
    tasks(r.tasks || []);
    llm(r.llm_review);
    $("branchState").textContent = labelOf(r.branch_workflow?.status) || "尚未运行分支流程";
    $("statusText").textContent = labelOf(r.status);
    await finishAbsorption();
  } catch (e) {
    cancelAbsorption();
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
  } finally {
    state.running = false;
  }
}

async function evolve() {
  state.running = true;
  $("statusText").textContent = "反问中";
  try {
    const r = await api("/api/self-evolve", {project: $("ownProjectFolder").value.trim(), run_local_gates: $("runGates").checked, max_rounds: 8, use_llm: $("useLlm").checked});
    scores(r.final_assessment.scores);
    tasks(r.tasks || []);
    llm(r.final_assessment?.llm_review || r.llm_review);
    $("branchState").textContent = `${labelOf(r.status)}：${labelOf(r.stop_reason)}`;
    $("statusText").textContent = "已反问";
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("branchState").textContent = `错误：${e.message}`;
  } finally {
    state.running = false;
  }
}

async function llmReview() {
  state.running = true;
  $("statusText").textContent = "排比评审中";
  try {
    const payload = body();
    const r = await api("/api/llm-review", {project: payload.project, mode: "manual", github_url: payload.github_url || "", external_path: payload.external_path || "", run_local_gates: payload.run_local_gates});
    llm(r);
    $("statusText").textContent = "已请求排比评审";
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("llmState").textContent = `错误：${e.message}`;
  } finally {
    state.running = false;
  }
}

async function llmStatus() {
  if (!state.llmTaskId) {
    $("llmState").textContent = "没有可同步的排比任务";
    return;
  }
  state.running = true;
  $("statusText").textContent = "同步排比中";
  try {
    const r = await api("/api/llm-review-status", {task_id: state.llmTaskId});
    const json = r.json_result ? ` · JSON ${r.json_result.level || "已返回"}` : "";
    $("llmState").textContent = `排比任务 ${r.status || "unknown"} · 子任务 ${r.subtasks?.map(s => s.status).join("/") || "无"}${json}`;
    $("statusText").textContent = "已同步排比";
  } catch (e) {
    $("statusText").textContent = "已阻断";
    $("llmState").textContent = `错误：${e.message}`;
  } finally {
    state.running = false;
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
  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  let g = ctx.createRadialGradient(x - radius * .35, y - radius * .45, radius * .1, x, y, radius);
  g.addColorStop(0, `rgba(247,251,255,${alpha})`);
  g.addColorStop(.2, `rgba(103,212,255,${alpha})`);
  g.addColorStop(.55, `rgba(46,111,157,${alpha})`);
  g.addColorStop(1, `rgba(7,16,28,${alpha})`);
  ctx.shadowColor = `rgba(103,212,255,${.82 * alpha})`;
  ctx.shadowBlur = 24 * dpr * alpha;
  ctx.beginPath();
  ctx.fillStyle = g;
  ctx.arc(x, y, Math.max(0, radius), 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.globalCompositeOperation = "lighter";
  ctx.beginPath();
  ctx.strokeStyle = `rgba(103,212,255,${.55 * alpha})`;
  ctx.lineWidth = 1.7 * dpr;
  ctx.arc(x, y, radius * 1.2, 0, Math.PI * 2);
  ctx.stroke();
  for (let i = 0; i < 5; i++) {
    const a = t * (.35 + i * .03) + i * 1.7;
    ctx.beginPath();
    ctx.strokeStyle = `rgba(255,255,255,${.08 * alpha})`;
    ctx.arc(x + Math.cos(a) * radius * .28, y + Math.sin(a) * radius * .1, radius * (.52 + i * .06), 0, Math.PI * 2);
    ctx.stroke();
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
$("llmStatusBtn").onclick = llmStatus;
externalScores(null);
draw();
