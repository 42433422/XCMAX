<template>
  <section class="private-mod-center" aria-label="客户私有 Mod 生产中心">
    <header class="private-mod-center__header">
      <div>
        <div class="private-mod-center__eyebrow">客户定制交付</div>
        <h3>私有 Mod 生产中心</h3>
        <p>
          模块轨与员工轨分开推进。每个节点是一条有先后约束的流程： 制作 → 测试 → 验收 →
          交付；不通过只能转返工，不能跨阶段跳跃。
        </p>
      </div>
      <button
        type="button"
        class="private-mod-center__refresh"
        :disabled="loading || updating"
        @click="loadDelivery"
      >
        {{ loading ? '同步中…' : '刷新私有状态' }}
      </button>
    </header>

    <div
      v-if="error"
      class="private-mod-center__notice private-mod-center__notice--error"
      role="alert"
    >
      {{ error }}
    </div>
    <div
      v-else-if="remoteError"
      class="private-mod-center__notice private-mod-center__notice--muted"
    >
      私有版本检查暂不可用：{{ remoteError }}
    </div>
    <div v-if="requestError" class="private-mod-center__notice private-mod-center__notice--muted">
      定制工单同步暂不可用：{{ requestError }}
    </div>

    <section class="private-mod-intake" aria-label="发起客户定制">
      <header class="private-mod-intake__header">
        <div>
          <span class="private-mod-track__kicker">定制入口</span>
          <h4>说明你要的模块或员工</h4>
          <p>提交后生产员工会自动制作和测试；质量门通过后由你验收，安装成功才算交付。</p>
        </div>
        <button
          type="button"
          class="private-mod-intake__toggle"
          @click="requestForm.open = !requestForm.open"
        >
          {{ requestForm.open ? '收起' : '发起定制' }}
        </button>
      </header>
      <form
        v-if="requestForm.open"
        class="private-mod-intake__form"
        @submit.prevent="submitCustomRequest"
      >
        <fieldset class="private-mod-intake__kinds">
          <legend>交付类型</legend>
          <label
            v-for="item in requestKinds"
            :key="item.id"
            :data-active="requestForm.kind === item.id"
          >
            <input v-model="requestForm.kind" type="radio" name="custom-kind" :value="item.id" />
            <strong>{{ item.label }}</strong>
            <small>{{ item.summary }}</small>
          </label>
        </fieldset>
        <div class="private-mod-intake__grid">
          <label>
            <span>需求名称</span>
            <input
              v-model="requestForm.title"
              maxlength="128"
              required
              placeholder="例如：销售合同审核模块"
            />
          </label>
          <label>
            <span>期望 ID（可选）</span>
            <input
              v-model="requestForm.suggestedId"
              maxlength="64"
              placeholder="sales-contract-review"
            />
          </label>
        </div>
        <label>
          <span>需求说明</span>
          <textarea
            v-model="requestForm.requirements"
            rows="5"
            maxlength="12000"
            required
            placeholder="输入使用人、输入数据、处理规则、输出结果以及异常处理……"
          />
        </label>
        <label>
          <span>验收标准</span>
          <textarea
            v-model="requestForm.acceptanceCriteria"
            rows="3"
            maxlength="6000"
            required
            placeholder="例如：用 20 份历史合同测试，金额/甲乙方/日期提取准确率≥95%，错误可定位并返工。"
          />
        </label>
        <footer>
          <span>工单、生产运行、验收与安装回执会绑定在同一条交付记录上。</span>
          <button type="submit" class="private-mod-center__update" :disabled="submittingRequest">
            {{ submittingRequest ? '正在受理…' : '提交并开始生产' }}
          </button>
        </footer>
      </form>
    </section>

    <section v-if="requests.length" class="private-mod-requests" aria-label="定制交付工单">
      <header class="private-mod-requests__header">
        <div>
          <span class="private-mod-track__kicker">交付进度</span>
          <h4>我的定制生产</h4>
        </div>
        <span>{{ requests.length }} 条</span>
      </header>
      <article
        v-for="item in requests"
        :key="item.id"
        class="private-mod-request"
        :data-stage="customOf(item).stage"
      >
        <header>
          <div>
            <div class="private-mod-request__meta">
              <code>{{ item.ticket_no }}</code>
              <span>{{ kindLabel(customOf(item).kind) }}</span>
            </div>
            <h5>{{ item.title }}</h5>
          </div>
          <span class="private-mod-request__stage">{{ customOf(item).stage_label }}</span>
        </header>
        <p>{{ item.summary }}</p>
        <ol v-if="latestRun(item)?.steps?.length" class="private-mod-request__steps">
          <li v-for="step in latestRun(item).steps" :key="step.id" :data-status="step.status">
            <span>{{ step.label }}</span>
            <small>{{ stepMessage(step) }}</small>
          </li>
        </ol>
        <div v-if="latestRun(item)?.error" class="private-mod-request__problem">
          生产失败：{{ latestRun(item).error }}
        </div>
        <div
          v-else-if="customOf(item).gate_message"
          class="private-mod-request__gate"
          :data-ok="customOf(item).gate_ok"
        >
          {{ customOf(item).gate_message }}
        </div>

        <div v-if="customOf(item).stage === 'acceptance'" class="private-mod-request__actions">
          <button
            type="button"
            class="private-mod-center__update"
            :disabled="!!requestBusy"
            @click="decideRequest(item, 'accept')"
          >
            {{ requestBusy === `accept:${item.id}` ? '确认中…' : '确认验收' }}
          </button>
          <button
            type="button"
            class="private-mod-node__action private-mod-node__action--rework"
            :disabled="!!requestBusy"
            @click="toggleRequestRework(item)"
          >
            验收不通过
          </button>
        </div>
        <div
          v-if="customOf(item).stage === 'rework' || reworkRequestId === item.id"
          class="private-mod-request__rework"
        >
          <textarea
            v-model="requestReworkNotes[item.id]"
            rows="3"
            maxlength="4000"
            placeholder="说明不符合验收标准的地方，生产员工会带着意见重做。"
          />
          <button
            type="button"
            class="private-mod-node__action private-mod-node__action--rework"
            :disabled="!!requestBusy"
            @click="decideRequest(item, 'rework')"
          >
            {{ requestBusy === `rework:${item.id}` ? '启动返工…' : '提交返工' }}
          </button>
        </div>
        <div v-if="customOf(item).stage === 'delivering'" class="private-mod-request__delivery">
          <div>验收已通过。安装成功后将自动回写交付回执并结案。</div>
          <button
            v-for="artifact in customOf(item).artifacts"
            :key="`${item.id}:${artifact.kind}:${artifact.id}`"
            type="button"
            class="private-mod-center__update"
            :disabled="!!requestBusy"
            @click="installRequestArtifact(item, artifact)"
          >
            {{
              requestBusy === `install:${item.id}:${artifact.kind}`
                ? '安装中…'
                : `安装${artifact.kind === 'employee' ? ' AI 员工' : '私有 Mod'}`
            }}
          </button>
        </div>
        <div v-if="customOf(item).stage === 'delivered'" class="private-mod-request__delivered">
          产物已安装，交付回执已写入。
        </div>
      </article>
    </section>

    <div v-if="loading && !projects.length" class="private-mod-center__empty">
      正在读取客户私有 Mod…
    </div>
    <div v-else-if="!projects.length" class="private-mod-center__empty">
      当前还没有已安装的客户私有 Mod；可以从上方发起第一个定制。
    </div>

    <div v-else class="private-mod-center__projects">
      <article v-for="project in projects" :key="project.mod_id" class="private-mod-project">
        <header class="private-mod-project__header">
          <div>
            <h4>{{ project.name }}</h4>
            <div class="private-mod-project__meta">
              <code>{{ project.mod_id }}</code>
              <span>{{
                project.current_version ? `当前 v${project.current_version}` : '尚未安装'
              }}</span>
              <span class="private-mod-project__overall" :data-status="project.overall_status">
                {{ project.overall_label }}
              </span>
            </div>
          </div>
          <div v-if="project.update_available" class="private-mod-project__update">
            <span>私有版本 v{{ project.latest_version }} 可更新</span>
            <button
              type="button"
              class="private-mod-center__update"
              :disabled="updating === project.mod_id"
              @click="updateProject(project)"
            >
              {{ updating === project.mod_id ? '更新中…' : '更新私有 Mod' }}
            </button>
          </div>
          <span v-else-if="project.latest_version" class="private-mod-project__latest"
            >已是最新私有版本</span
          >
        </header>

        <p v-if="project.description" class="private-mod-project__description">
          {{ project.description }}
        </p>

        <div class="private-mod-project__tracks">
          <section
            v-for="rail in trackRails"
            :key="rail.id"
            class="private-mod-track"
            :class="`private-mod-track--${rail.id}`"
          >
            <header class="private-mod-track__header">
              <div>
                <span class="private-mod-track__kicker">{{ rail.kicker }}</span>
                <h5>{{ rail.label }}</h5>
              </div>
              <span class="private-mod-track__rollup" :data-status="trackStatus(project, rail.id)">
                {{ stageLabel(project, rail.id, trackStatus(project, rail.id)) }}
              </span>
            </header>
            <p class="private-mod-track__summary">{{ rail.summary }}</p>

            <ol class="private-mod-flow" aria-label="主流程阶段">
              <li
                v-for="(step, stepIndex) in happyPath"
                :key="step"
                class="private-mod-flow__step"
                :data-done="flowStepDone(project, rail.id, step)"
              >
                <span class="private-mod-flow__num">{{
                  String(stepIndex + 1).padStart(2, '0')
                }}</span>
                <span class="private-mod-flow__name">{{ stageLabel(project, rail.id, step) }}</span>
                <small>{{ stageGoal(step) }}</small>
              </li>
            </ol>

            <ol
              v-if="nodesOf(project, rail.id).length"
              class="private-mod-rail"
              :aria-label="`${rail.label}节点`"
            >
              <li
                v-for="(node, index) in nodesOf(project, rail.id)"
                :key="node.id"
                class="private-mod-node"
                :data-status="node.status"
              >
                <div class="private-mod-node__top">
                  <div class="private-mod-node__index" aria-hidden="true">
                    {{ String(index + 1).padStart(2, '0') }}
                  </div>
                  <div class="private-mod-node__body">
                    <div class="private-mod-node__title">{{ node.label }}</div>
                    <small v-if="node.summary">{{ node.summary }}</small>
                  </div>
                  <span class="private-mod-node__badge">{{
                    node.status_label || stageLabel(project, rail.id, node.status)
                  }}</span>
                </div>

                <div class="private-mod-node__pipeline" aria-hidden="true">
                  <span
                    v-for="step in happyPath"
                    :key="`${node.id}-${step}`"
                    class="private-mod-node__pip"
                    :data-active="pipelineActive(node, step)"
                    :data-done="pipelineDone(node, step)"
                    :data-rework="node.status === 'rework'"
                    >{{ stageLabel(project, rail.id, step) }}</span
                  >
                </div>

                <p class="private-mod-node__goal">
                  目标：{{ node.goal || stageGoal(node.status) || '按流程推进到下一阶段' }}
                </p>

                <div class="private-mod-node__actions">
                  <button
                    v-for="next in node.next_stages || []"
                    :key="`${node.id}-${next}`"
                    type="button"
                    class="private-mod-node__action"
                    :class="{ 'private-mod-node__action--rework': next === 'rework' }"
                    :disabled="savingStatus === `${project.mod_id}:${rail.id}:${node.id}`"
                    @click="onAdvanceClick(project, rail.id, node, next)"
                  >
                    {{ nextActionLabel(project, rail.id, node.status, next) }}
                  </button>
                  <span v-if="!(node.next_stages || []).length" class="private-mod-node__done"
                    >流程已结束</span
                  >
                </div>
                <p
                  v-if="node.status === 'rework' && lastReworkNote(node)"
                  class="private-mod-node__ticket"
                >
                  {{ lastReworkNote(node) }}
                </p>
              </li>
            </ol>
            <div v-else class="private-mod-track__empty">{{ rail.empty }}</div>
          </section>
        </div>
      </article>
    </div>

    <div
      v-if="reworkDialog.open"
      class="private-mod-rework-mask"
      role="dialog"
      aria-modal="true"
      aria-label="填写返工问题"
      @click.self="closeReworkDialog"
    >
      <form class="private-mod-rework" @submit.prevent="submitRework">
        <header>
          <h4>转返工 · 填写问题</h4>
          <p>问题会开成客服变更工单（bug_fix），不另建工单系统。</p>
        </header>
        <div class="private-mod-rework__meta">
          <span>{{ reworkDialog.projectName }}</span>
          <code>{{ reworkDialog.nodeLabel }}</code>
        </div>
        <label class="private-mod-rework__label" for="private-mod-rework-problem">问题说明</label>
        <textarea
          id="private-mod-rework-problem"
          v-model="reworkDialog.problem"
          rows="5"
          maxlength="2000"
          placeholder="例如：考勤表转化后部门列错位，样例文件已附……"
          required
        />
        <footer class="private-mod-rework__footer">
          <button type="button" class="private-mod-rework__cancel" @click="closeReworkDialog">
            取消
          </button>
          <button
            type="submit"
            class="private-mod-node__action private-mod-node__action--rework"
            :disabled="!!savingStatus"
          >
            {{ savingStatus ? '提交中…' : '开单并转返工' }}
          </button>
        </footer>
      </form>
    </div>
  </section>
</template>

<script setup>
  import { onBeforeUnmount, onMounted, ref } from 'vue';
  import { apiFetch } from '@/utils/apiBase';

  const projects = ref([]);
  const requests = ref([]);
  const happyPath = ref(['production', 'testing', 'acceptance', 'delivered']);
  const stageFlow = ref({});
  const defaultStageLabels = {
    production: '制作中',
    testing: '测试中',
    rework: '返工中',
    acceptance: '验收中',
    delivered: '已交付',
    partial: '部分完成',
  };
  const defaultGoals = {
    production: '完成开发与自测，进入可测状态',
    testing: '用例通过；不通过则返工',
    rework: '修复问题后重回测试',
    acceptance: '生产/客户验收通过后交付',
    delivered: '节点交付完成，流程结束',
  };
  const trackRails = [
    {
      id: 'modules',
      kicker: '交付轨道 01 · 模块',
      label: '业务模块',
      summary: '每个模块节点走完整交付流程（例：太阳鸟「考勤表转化」）。',
      empty: '当前定制包未声明模块节点。',
    },
    {
      id: 'employees',
      kicker: '交付轨道 02 · 员工',
      label: 'AI 员工',
      summary: '每个员工节点独立走制作 / 测试 / 验收 / 上岗流程。',
      empty: '当前定制包未声明员工节点。',
    },
  ];
  const loading = ref(false);
  const updating = ref('');
  const savingStatus = ref('');
  const error = ref('');
  const remoteError = ref('');
  const requestError = ref('');
  const submittingRequest = ref(false);
  const requestBusy = ref('');
  const reworkRequestId = ref(0);
  const requestReworkNotes = ref({});
  const requestKinds = [
    { id: 'module', label: '业务模块', summary: '生成可安装的私有 Mod 模块' },
    { id: 'employee', label: 'AI 员工', summary: '生成员工包、Skill 组和运行校验' },
    { id: 'bundle', label: 'Mod + 员工', summary: '交付模块与配套生产员工' },
  ];
  const requestForm = ref({
    open: false,
    kind: 'bundle',
    title: '',
    suggestedId: '',
    requirements: '',
    acceptanceCriteria: '',
  });
  const reworkDialog = ref({
    open: false,
    project: null,
    track: '',
    nodeId: '',
    projectName: '',
    nodeLabel: '',
    problem: '',
  });

  function responseMessage(body, fallback) {
    return String(body?.detail || body?.message || body?.error || fallback).trim() || fallback;
  }

  function customOf(item) {
    return item?.custom_delivery && typeof item.custom_delivery === 'object'
      ? item.custom_delivery
      : {};
  }

  function latestRun(item) {
    const runs = customOf(item).runs;
    return Array.isArray(runs) && runs.length ? runs[runs.length - 1] : null;
  }

  function kindLabel(kind) {
    return requestKinds.find((row) => row.id === kind)?.label || '客户定制';
  }

  function stepMessage(step) {
    const message = step?.message;
    if (message && typeof message === 'object') return String(message.summary || '');
    return String(
      message ||
        {
          pending: '待执行',
          running: '执行中',
          done: '已通过',
          skipped: '不适用',
          error: '未通过',
        }[step?.status] ||
        ''
    );
  }

  async function submitCustomRequest() {
    const form = requestForm.value;
    const title = String(form.title || '').trim();
    const requirements = String(form.requirements || '').trim();
    const acceptanceCriteria = String(form.acceptanceCriteria || '').trim();
    if (title.length < 2 || requirements.length < 8 || acceptanceCriteria.length < 4) {
      error.value = '请完整填写需求名称、需求说明和验收标准';
      return;
    }
    submittingRequest.value = true;
    error.value = '';
    try {
      const response = await apiFetch('/api/mod-store/private-delivery/requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: form.kind,
          title,
          requirements,
          acceptance_criteria: acceptanceCriteria,
          suggested_id: String(form.suggestedId || '').trim() || undefined,
        }),
        timeoutMs: 60_000,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.success !== true) {
        throw new Error(responseMessage(body, `定制需求受理失败（HTTP ${response.status}）`));
      }
      requestForm.value = {
        open: false,
        kind: 'bundle',
        title: '',
        suggestedId: '',
        requirements: '',
        acceptanceCriteria: '',
      };
      await loadDelivery();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '定制需求受理失败';
    } finally {
      submittingRequest.value = false;
    }
  }

  function toggleRequestRework(item) {
    reworkRequestId.value = reworkRequestId.value === item.id ? 0 : item.id;
  }

  async function decideRequest(item, action) {
    const note = String(requestReworkNotes.value[item.id] || '').trim();
    if (action === 'rework' && note.length < 4) {
      error.value = '返工意见至少 4 个字';
      return;
    }
    requestBusy.value = `${action}:${item.id}`;
    error.value = '';
    try {
      const response = await apiFetch(
        `/api/mod-store/private-delivery/requests/${item.id}/decision`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, note: note || undefined }),
          timeoutMs: 60_000,
        }
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.success !== true) {
        throw new Error(responseMessage(body, `定制交付操作失败（HTTP ${response.status}）`));
      }
      reworkRequestId.value = 0;
      delete requestReworkNotes.value[item.id];
      await loadDelivery();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '定制交付操作失败';
    } finally {
      requestBusy.value = '';
    }
  }

  async function installRequestArtifact(item, artifact) {
    if (!artifact?.kind) return;
    requestBusy.value = `install:${item.id}:${artifact.kind}`;
    error.value = '';
    try {
      const response = await apiFetch(
        `/api/mod-store/private-delivery/requests/${item.id}/install`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_kind: artifact.kind }),
          timeoutMs: 180_000,
        }
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.success !== true) {
        throw new Error(responseMessage(body, `定制产物安装失败（HTTP ${response.status}）`));
      }
      await loadDelivery();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '定制产物安装失败';
    } finally {
      requestBusy.value = '';
    }
  }

  function lastReworkNote(node) {
    const timeline = Array.isArray(node?.timeline) ? node.timeline : [];
    for (let i = timeline.length - 1; i >= 0; i -= 1) {
      const row = timeline[i];
      if (row && row.status === 'rework' && row.note) return String(row.note);
    }
    return '';
  }

  function onAdvanceClick(project, track, node, status) {
    if (status === 'rework') {
      reworkDialog.value = {
        open: true,
        project,
        track,
        nodeId: node.id,
        projectName: project.name || project.mod_id,
        nodeLabel: node.label || node.id,
        problem: '',
      };
      return;
    }
    advanceNode(project, track, node.id, status);
  }

  function closeReworkDialog() {
    reworkDialog.value = {
      open: false,
      project: null,
      track: '',
      nodeId: '',
      projectName: '',
      nodeLabel: '',
      problem: '',
    };
  }

  async function submitRework() {
    const dlg = reworkDialog.value;
    const problem = String(dlg.problem || '').trim();
    if (problem.length < 4) {
      error.value = '转返工须填写问题说明（至少 4 个字）';
      return;
    }
    if (!dlg.project) return;
    await advanceNode(dlg.project, dlg.track, dlg.nodeId, 'rework', problem);
    if (!error.value) closeReworkDialog();
  }

  function nodesOf(project, track) {
    const nodes = project?.track_nodes?.[track];
    return Array.isArray(nodes) ? nodes : [];
  }

  function stageGoal(stage) {
    const fromApi = stageFlow.value?.[stage]?.goal;
    return String(fromApi || defaultGoals[stage] || '').trim();
  }

  function happyIndex(status) {
    const idx = happyPath.value.indexOf(status === 'rework' ? 'testing' : status);
    return idx;
  }

  function pipelineDone(node, step) {
    const cur = String(node?.status || 'production');
    if (cur === 'delivered') return true;
    if (cur === 'rework')
      return happyIndex('production') >= happyPath.value.indexOf(step) && step === 'production';
    const curIdx = happyIndex(cur);
    const stepIdx = happyPath.value.indexOf(step);
    return curIdx > stepIdx;
  }

  function pipelineActive(node, step) {
    const cur = String(node?.status || 'production');
    if (cur === 'rework') return step === 'testing';
    return cur === step;
  }

  function flowStepDone(project, track, step) {
    const nodes = nodesOf(project, track);
    if (!nodes.length) return false;
    return nodes.every(
      (node) =>
        pipelineDone(node, step) ||
        (pipelineActive(node, step) && ['acceptance', 'delivered'].includes(node.status))
    );
  }

  function nextActionLabel(project, track, current, next) {
    const curLabel = stageLabel(project, track, current);
    const nextLabel = stageLabel(project, track, next);
    if (next === 'rework') return `转返工`;
    if (current === 'rework' && next === 'testing') return `返工完成，重回测试`;
    return `推进到${nextLabel}`;
  }

  async function loadDelivery() {
    loading.value = true;
    error.value = '';
    remoteError.value = '';
    requestError.value = '';
    try {
      const response = await apiFetch('/api/mod-store/private-delivery', { timeoutMs: 30_000 });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.success !== true) {
        throw new Error(responseMessage(body, `私有 Mod 状态读取失败（HTTP ${response.status}）`));
      }
      projects.value = (Array.isArray(body?.data?.projects) ? body.data.projects : []).filter(
        (row) => {
          const mid = String(row?.mod_id || '').trim();
          if (!mid || mid.endsWith('-industry')) return false;
          return true;
        }
      );
      requests.value = Array.isArray(body?.data?.requests) ? body.data.requests : [];
      if (Array.isArray(body?.data?.happy_path) && body.data.happy_path.length) {
        happyPath.value = body.data.happy_path;
      }
      if (body?.data?.stage_flow && typeof body.data.stage_flow === 'object') {
        stageFlow.value = body.data.stage_flow;
      }
      remoteError.value = String(body?.data?.remote_error || '').trim();
      requestError.value = String(body?.data?.request_error || '').trim();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '私有 Mod 状态读取失败';
    } finally {
      loading.value = false;
    }
  }

  function trackStatus(project, track) {
    const canonical = track === 'business' ? 'modules' : track;
    return String(
      project?.tracks?.[canonical]?.status || project?.tracks?.business?.status || 'production'
    );
  }

  function stageLabel(project, track, stage) {
    const canonical = track === 'business' ? 'modules' : track;
    const fromFlow = stageFlow.value?.[stage]?.label;
    return String(
      fromFlow ||
        project?.stage_labels?.[canonical]?.[stage] ||
        project?.stage_labels?.business?.[stage] ||
        defaultStageLabels[stage] ||
        stage
    );
  }

  async function advanceNode(project, track, nodeId, status, note = '') {
    if (!status || !nodeId) return;
    const key = `${project.mod_id}:${track}:${nodeId}`;
    savingStatus.value = key;
    error.value = '';
    try {
      const response = await apiFetch('/api/mod-store/private-delivery/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mod_id: project.mod_id,
          track,
          node_id: nodeId,
          status,
          note: note || undefined,
        }),
        timeoutMs: 30_000,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.success !== true) {
        throw new Error(responseMessage(body, `流程推进失败（HTTP ${response.status}）`));
      }
      await loadDelivery();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '流程推进失败';
    } finally {
      savingStatus.value = '';
    }
  }

  async function updateProject(project) {
    if (!project?.mod_id || updating.value) return;
    updating.value = project.mod_id;
    error.value = '';
    try {
      const response = await apiFetch('/api/mod-store/private-mod/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mod_id: project.mod_id,
          expected_version: project.latest_version || '',
        }),
        timeoutMs: 120_000,
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.success !== true) {
        throw new Error(responseMessage(body, `私有 Mod 更新失败（HTTP ${response.status}）`));
      }
      await loadDelivery();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '私有 Mod 更新失败';
    } finally {
      updating.value = '';
    }
  }

  let deliveryPollTimer = null;
  onMounted(() => {
    loadDelivery();
    deliveryPollTimer = window.setInterval(() => {
      if (!loading.value && !submittingRequest.value && !requestBusy.value) loadDelivery();
    }, 15_000);
  });
  onBeforeUnmount(() => {
    if (deliveryPollTimer) window.clearInterval(deliveryPollTimer);
  });
</script>

<style scoped>
  .private-mod-center {
    padding: 22px 22px 36px;
    color: #0f172a;
  }
  .private-mod-center__header,
  .private-mod-project__header,
  .private-mod-track__header,
  .private-mod-node__top {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    justify-content: space-between;
  }
  .private-mod-center__eyebrow,
  .private-mod-track__kicker {
    color: #64748b;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .private-mod-center h3,
  .private-mod-project h4,
  .private-mod-track h5 {
    margin: 4px 0 0;
    font-weight: 750;
  }
  .private-mod-center h3 {
    font-size: 24px;
  }
  .private-mod-project h4 {
    font-size: 19px;
  }
  .private-mod-track h5 {
    font-size: 16px;
  }
  .private-mod-center__header p,
  .private-mod-project__description,
  .private-mod-track__summary,
  .private-mod-node__goal {
    margin: 8px 0 0;
    color: #64748b;
    font-size: 13px;
    line-height: 1.55;
  }
  .private-mod-center__refresh,
  .private-mod-center__update,
  .private-mod-node__action {
    border: 0;
    border-radius: 10px;
    padding: 10px 14px;
    background: #0f172a;
    color: #fff;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
  }
  .private-mod-center__refresh:disabled,
  .private-mod-center__update:disabled,
  .private-mod-node__action:disabled {
    opacity: 0.55;
    cursor: wait;
  }
  .private-mod-node__action--rework {
    background: #b45309;
  }
  .private-mod-intake {
    margin-top: 18px;
    border: 1px solid #bfdbfe;
    border-radius: 16px;
    padding: 18px;
    background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 60%, #f5f3ff 100%);
  }
  .private-mod-intake__header,
  .private-mod-requests__header,
  .private-mod-request > header,
  .private-mod-intake__form footer {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 14px;
  }
  .private-mod-intake h4,
  .private-mod-requests h4,
  .private-mod-request h5 {
    margin: 4px 0 0;
    color: #0f172a;
  }
  .private-mod-intake h4,
  .private-mod-requests h4 {
    font-size: 17px;
  }
  .private-mod-request h5 {
    font-size: 15px;
  }
  .private-mod-intake__header p {
    max-width: 780px;
    margin: 7px 0 0;
    color: #64748b;
    font-size: 12px;
    line-height: 1.55;
  }
  .private-mod-intake__toggle {
    flex: 0 0 auto;
    border: 1px solid #93c5fd;
    border-radius: 10px;
    padding: 9px 13px;
    background: #fff;
    color: #1d4ed8;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
  }
  .private-mod-intake__form {
    display: grid;
    gap: 14px;
    margin-top: 16px;
  }
  .private-mod-intake__form label > span,
  .private-mod-intake__kinds legend {
    display: block;
    margin-bottom: 7px;
    color: #334155;
    font-size: 12px;
    font-weight: 700;
  }
  .private-mod-intake__form input[type='text'],
  .private-mod-intake__form input:not([type]),
  .private-mod-intake__form textarea,
  .private-mod-request__rework textarea {
    width: 100%;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 10px 12px;
    background: #fff;
    color: #0f172a;
    font: inherit;
    box-sizing: border-box;
  }
  .private-mod-intake__form textarea,
  .private-mod-request__rework textarea {
    resize: vertical;
  }
  .private-mod-intake__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .private-mod-intake__kinds {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 9px;
    margin: 0;
    border: 0;
    padding: 0;
  }
  .private-mod-intake__kinds legend {
    grid-column: 1 / -1;
  }
  .private-mod-intake__kinds label {
    position: relative;
    border: 1px solid #dbeafe;
    border-radius: 11px;
    padding: 11px 11px 11px 35px;
    background: rgba(255, 255, 255, 0.82);
    cursor: pointer;
  }
  .private-mod-intake__kinds label[data-active='true'] {
    border-color: #3b82f6;
    box-shadow: inset 0 0 0 1px #3b82f6;
  }
  .private-mod-intake__kinds input {
    position: absolute;
    left: 12px;
    top: 13px;
  }
  .private-mod-intake__kinds strong {
    display: block;
    font-size: 13px;
  }
  .private-mod-intake__kinds small {
    display: block;
    margin-top: 4px;
    color: #64748b;
    font-size: 11px;
    line-height: 1.4;
  }
  .private-mod-intake__form footer {
    align-items: center;
  }
  .private-mod-intake__form footer > span {
    color: #64748b;
    font-size: 11px;
    line-height: 1.45;
  }
  .private-mod-requests {
    margin-top: 20px;
  }
  .private-mod-requests__header {
    align-items: center;
  }
  .private-mod-requests__header > span {
    color: #64748b;
    font-size: 12px;
  }
  .private-mod-request {
    margin-top: 10px;
    border: 1px solid #e2e8f0;
    border-left: 4px solid #3b82f6;
    border-radius: 13px;
    padding: 15px;
    background: #fff;
  }
  .private-mod-request[data-stage='rework'] {
    border-left-color: #d97706;
  }
  .private-mod-request[data-stage='delivered'] {
    border-left-color: #10b981;
  }
  .private-mod-request__meta {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    color: #64748b;
    font-size: 11px;
  }
  .private-mod-request__stage {
    border-radius: 999px;
    padding: 5px 9px;
    background: #dbeafe;
    color: #1d4ed8;
    font-size: 12px;
    font-weight: 700;
  }
  .private-mod-request > p {
    margin: 9px 0 0;
    color: #64748b;
    font-size: 12px;
    line-height: 1.5;
  }
  .private-mod-request__steps {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 7px;
    margin: 12px 0 0;
    padding: 0;
    list-style: none;
  }
  .private-mod-request__steps li {
    border-radius: 9px;
    padding: 8px;
    background: #f8fafc;
  }
  .private-mod-request__steps li[data-status='running'] {
    background: #eff6ff;
    box-shadow: inset 0 0 0 1px #93c5fd;
  }
  .private-mod-request__steps li[data-status='done'] {
    background: #ecfdf5;
  }
  .private-mod-request__steps li[data-status='error'] {
    background: #fef2f2;
  }
  .private-mod-request__steps span {
    display: block;
    color: #334155;
    font-size: 11px;
    font-weight: 700;
  }
  .private-mod-request__steps small {
    display: block;
    margin-top: 3px;
    color: #64748b;
    font-size: 10px;
    line-height: 1.35;
  }
  .private-mod-request__problem,
  .private-mod-request__gate,
  .private-mod-request__delivered {
    margin-top: 11px;
    border-radius: 9px;
    padding: 9px 11px;
    color: #92400e;
    background: #fffbeb;
    font-size: 12px;
  }
  .private-mod-request__gate[data-ok='true'],
  .private-mod-request__delivered {
    color: #047857;
    background: #ecfdf5;
  }
  .private-mod-request__actions,
  .private-mod-request__delivery,
  .private-mod-request__rework {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 9px;
    margin-top: 12px;
  }
  .private-mod-request__delivery > div {
    flex: 1 1 320px;
    color: #475569;
    font-size: 12px;
  }
  .private-mod-request__rework textarea {
    flex: 1 1 420px;
  }
  .private-mod-center__notice,
  .private-mod-center__empty {
    margin-top: 16px;
    border-radius: 12px;
    padding: 12px 14px;
    background: #f8fafc;
    color: #475569;
    font-size: 13px;
  }
  .private-mod-center__notice--error {
    color: #b91c1c;
    background: #fef2f2;
  }
  .private-mod-center__projects {
    display: grid;
    gap: 16px;
    margin-top: 20px;
  }
  .private-mod-project {
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 18px;
    background: #fff;
  }
  .private-mod-project__meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 8px;
    color: #64748b;
    font-size: 12px;
  }
  .private-mod-project__meta code {
    color: #475569;
  }
  .private-mod-project__overall,
  .private-mod-project__latest,
  .private-mod-track__rollup,
  .private-mod-node__badge {
    border-radius: 999px;
    padding: 4px 9px;
    background: #ecfdf5;
    color: #047857;
    font-size: 12px;
    font-weight: 700;
  }
  .private-mod-project__overall[data-status='partial'],
  .private-mod-track__rollup[data-status='partial'],
  .private-mod-track__rollup[data-status='testing'],
  .private-mod-track__rollup[data-status='acceptance'],
  .private-mod-node[data-status='testing'],
  .private-mod-node[data-status='acceptance'] .private-mod-node__badge {
    color: #92400e;
    background: #fef3c7;
  }
  .private-mod-project__overall[data-status='rework'],
  .private-mod-track__rollup[data-status='rework'],
  .private-mod-node[data-status='rework'] .private-mod-node__badge {
    color: #b91c1c;
    background: #fee2e2;
  }
  .private-mod-project__update {
    display: flex;
    align-items: center;
    gap: 10px;
    color: #92400e;
    font-size: 12px;
    font-weight: 700;
  }
  .private-mod-project__latest {
    font-size: 12px;
  }
  .private-mod-project__description {
    margin-top: 12px;
  }
  .private-mod-project__tracks {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
    margin-top: 16px;
  }
  .private-mod-track {
    border-radius: 13px;
    padding: 15px;
    background: #f8fafc;
  }
  .private-mod-track--modules {
    border: 1px solid #dbeafe;
  }
  .private-mod-track--employees {
    border: 1px solid #ede9fe;
  }
  .private-mod-flow {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    margin: 14px 0 0;
    padding: 0;
    list-style: none;
  }
  .private-mod-flow__step {
    border-radius: 10px;
    padding: 10px;
    background: #fff;
    border: 1px dashed #cbd5e1;
  }
  .private-mod-flow__step[data-done='true'] {
    border-style: solid;
    border-color: #86efac;
    background: #f0fdf4;
  }
  .private-mod-flow__num {
    display: block;
    color: #94a3b8;
    font-size: 11px;
    font-weight: 700;
  }
  .private-mod-flow__name {
    display: block;
    margin-top: 4px;
    color: #0f172a;
    font-size: 13px;
    font-weight: 700;
  }
  .private-mod-flow__step small {
    display: block;
    margin-top: 4px;
    color: #64748b;
    font-size: 11px;
    line-height: 1.4;
  }
  .private-mod-rail {
    display: grid;
    gap: 12px;
    margin: 14px 0 0;
    padding: 0;
    list-style: none;
  }
  .private-mod-node {
    border-radius: 12px;
    padding: 12px;
    background: #fff;
    border: 1px solid #e2e8f0;
  }
  .private-mod-node__index {
    flex: 0 0 auto;
    width: 28px;
    height: 28px;
    border-radius: 999px;
    display: grid;
    place-items: center;
    background: #0f172a;
    color: #fff;
    font-size: 11px;
    font-weight: 700;
  }
  .private-mod-node__body {
    flex: 1 1 auto;
    min-width: 0;
  }
  .private-mod-node__title {
    color: #0f172a;
    font-size: 13px;
    font-weight: 700;
  }
  .private-mod-node small {
    display: block;
    margin-top: 3px;
    color: #64748b;
    font-size: 11px;
    line-height: 1.45;
  }
  .private-mod-node__pipeline {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 6px;
    margin-top: 12px;
  }
  .private-mod-node__pip {
    border-radius: 8px;
    padding: 6px 4px;
    text-align: center;
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
    background: #f1f5f9;
  }
  .private-mod-node__pip[data-done='true'] {
    color: #047857;
    background: #d1fae5;
  }
  .private-mod-node__pip[data-active='true'] {
    color: #1d4ed8;
    background: #dbeafe;
    box-shadow: inset 0 0 0 1px #93c5fd;
  }
  .private-mod-node__pip[data-rework='true'][data-active='true'] {
    color: #b45309;
    background: #ffedd5;
    box-shadow: inset 0 0 0 1px #fdba74;
  }
  .private-mod-node__actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
  }
  .private-mod-node__done {
    color: #059669;
    font-size: 12px;
    font-weight: 700;
    align-self: center;
  }
  .private-mod-node__ticket {
    margin: 10px 0 0;
    border-radius: 8px;
    padding: 8px 10px;
    background: #fff7ed;
    color: #9a3412;
    font-size: 12px;
    line-height: 1.45;
  }
  .private-mod-track__empty {
    margin-top: 13px;
    color: #94a3b8;
    font-size: 12px;
  }
  .private-mod-rework-mask {
    position: fixed;
    inset: 0;
    z-index: 40;
    display: grid;
    place-items: center;
    padding: 18px;
    background: rgba(15, 23, 42, 0.45);
  }
  .private-mod-rework {
    width: min(520px, 100%);
    border-radius: 16px;
    padding: 18px;
    background: #fff;
    box-shadow: 0 24px 60px rgba(15, 23, 42, 0.25);
  }
  .private-mod-rework h4 {
    margin: 0;
    font-size: 18px;
  }
  .private-mod-rework header p {
    margin: 6px 0 0;
    color: #64748b;
    font-size: 12px;
    line-height: 1.5;
  }
  .private-mod-rework__meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
    color: #475569;
    font-size: 12px;
  }
  .private-mod-rework__meta code {
    color: #0f172a;
  }
  .private-mod-rework__label {
    display: block;
    margin-top: 14px;
    color: #0f172a;
    font-size: 13px;
    font-weight: 700;
  }
  .private-mod-rework textarea {
    display: block;
    width: 100%;
    margin-top: 8px;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 10px 12px;
    resize: vertical;
    font: inherit;
    color: #0f172a;
    box-sizing: border-box;
  }
  .private-mod-rework__footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 14px;
  }
  .private-mod-rework__cancel {
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 10px 14px;
    background: #fff;
    color: #334155;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
  }

  @media (max-width: 1100px) {
    .private-mod-project__tracks,
    .private-mod-flow,
    .private-mod-node__pipeline {
      grid-template-columns: 1fr 1fr;
    }
  }
  @media (max-width: 900px) {
    .private-mod-center {
      padding: 18px 14px 30px;
    }
    .private-mod-center__header,
    .private-mod-project__header {
      flex-direction: column;
    }
    .private-mod-project__tracks {
      grid-template-columns: 1fr;
    }
    .private-mod-project__update {
      align-items: flex-start;
      flex-direction: column;
    }
    .private-mod-intake__header,
    .private-mod-intake__form footer,
    .private-mod-request > header {
      flex-direction: column;
    }
    .private-mod-intake__grid,
    .private-mod-intake__kinds {
      grid-template-columns: 1fr;
    }
  }
</style>
