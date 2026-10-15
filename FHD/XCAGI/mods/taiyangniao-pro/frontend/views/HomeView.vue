<template>
  <div class="mod-home page-view">
    <div class="page-grid">
      <div class="page-content page-main">
        <h2>考勤行业包</h2>
        <p class="muted">
          Mod ID: <code>taiyangniao-pro</code> — 在库项目中编辑后执行 <code>modman push</code> 部署到 XCAGI。
        </p>
        <p class="muted small">
          <router-link :to="{ name: 'attendance-industry-settings' }">考勤转换设置</router-link>
          （钉钉 → 明细裁窗、加班规则；原在「审批中心 → 流程规则」中，已迁于此）
        </p>

        <section class="card-block" aria-labelledby="upload-convert-title">
          <h3 id="upload-convert-title">上传转化</h3>
          <p class="muted small">
            将钉钉导出的考勤 xlsx 上传后，由考勤模块
            <code>attendance-industry: backend/attendance_engine/</code>
            按列别名解析「每日统计」等表。默认<strong>按侧栏「人员管理」</strong>（主库产品表：姓名、部门对应「单位」、性质对应「规格」）重排「明细」每人 6 行，再按姓名把钉钉数据一一填入；<strong>无钉钉记录则打卡区留空</strong>。取消勾选下方选项时，改为仅使用固定模板「明细」里原有姓名名单。路径相对
            <code>WORKSPACE_ROOT</code>（默认写入 <code>424/</code>）。成功后会自动下载，也可点「再次下载」。
          </p>

          <div class="form-row">
            <label class="lbl">钉钉考勤表</label>
            <input type="file" accept=".xlsx,.xlsm,.xls" class="file" @change="onFile" />
          </div>

          <div class="form-row">
            <label class="lbl" for="out-rel">输出相对路径</label>
            <input
              id="out-rel"
              v-model.trim="outputRelpath"
              type="text"
              class="inp"
              placeholder="如 424/考勤转换结果.xlsx（建议填新文件名）"
              autocomplete="off"
            />
          </div>

          <div class="form-row">
            <label class="lbl" for="tpl-rel">模板相对路径（固定）</label>
            <input
              id="tpl-rel"
              v-model.trim="templateRelpath"
              type="text"
              class="inp"
              placeholder="如 424/考勤-2026-3月份考勤统计表.xlsx"
              readonly
              autocomplete="off"
            />
            <p class="hint">
              按你指定的固定模板回填：424/考勤-2026-3月份考勤统计表.xlsx
            </p>
          </div>

          <div class="form-row inline">
            <div class="grow">
              <label class="lbl" for="month">统计月份（可选）</label>
              <input id="month" v-model.trim="month" type="text" class="inp" placeholder="YYYY-MM" />
            </div>
            <div class="grow">
              <label class="lbl" for="hdr">表头所在行（0 为自动识别）</label>
              <input id="hdr" v-model.number="headerRow" type="number" min="0" class="inp narrow" />
            </div>
          </div>

          <div class="form-row">
            <label class="lbl checkbox">
              <input type="checkbox" v-model="usePersonnelRoster" />
              按「人员管理」名单重排明细并回填（有钉钉则填，无则空）
            </label>
            <p class="hint">与侧栏「人员管理」同一数据源；请先在其中维护员工名单。</p>
          </div>

          <div class="form-row">
            <label class="lbl checkbox">
              <input type="checkbox" v-model="useLlm" />
              本地规则识别不出时，调用我的 LLM 智能识别表头
            </label>
            <p class="hint">
              仅当出现 "表头未识别" 或 "0 行" 时才会真正调用模型；需后端配置
              <code>OPENAI_API_KEY</code> 或 <code>DEEPSEEK_API_KEY</code>。
            </p>
          </div>

          <div class="actions">
            <button type="button" class="btn primary" :disabled="!file || loading" @click="doUploadConvert">
              {{ loading ? '转换中…' : '上传并转换' }}
            </button>
            <button
              v-if="lastOutputRelpath"
              type="button"
              class="btn"
              :disabled="loadingDl"
              @click="downloadOutput(lastOutputRelpath)"
            >
              {{ loadingDl ? '下载中…' : '再次下载' }}
            </button>
          </div>

          <p v-if="err" class="err">{{ err }}</p>
          <p v-if="okMsg" class="ok">{{ okMsg }}</p>
        </section>
      </div>

      <aside class="rules-sidebar" aria-labelledby="rules-title">
        <div class="rules-card">
          <h3 id="rules-title" class="rules-title">考勤规则</h3>
          <p class="rules-sub muted small">
            与考勤模块 <code>attendance-industry: backend/attendance_engine/rules.py</code> 默认配置一致；转换时使用同一套逻辑。
          </p>
          <p v-if="rulesLoading" class="rules-muted">加载中…</p>
          <p v-else-if="rulesErr" class="rules-err">{{ rulesErr }}</p>
          <template v-else-if="rulesLines.length">
            <p v-if="rulesWindow" class="rules-window">
              当前周六有效时段：<strong>{{ rulesWindow }}</strong>
            </p>
            <ul class="rules-list">
              <li v-for="(ln, i) in rulesLines" :key="i">{{ ln }}</li>
            </ul>

            <section
              v-if="scheduleGroups.length"
              class="schedule-groups"
              aria-labelledby="sched-ref-title"
            >
              <h4 id="sched-ref-title" class="schedule-groups__title">钉钉考勤组（参考）</h4>
              <p class="schedule-groups__hint muted small">
                与钉钉后台「固定班制」排班文案一致，便于对照；转换时按导出表中的考勤组/部门列名匹配规则。
              </p>
              <div
                v-for="(g, gi) in scheduleGroups"
                :key="gi"
                class="schedule-group-card"
              >
                <div class="schedule-group-card__head">
                  <span class="schedule-group-card__name">{{ g.name }}</span>
                  <span class="schedule-group-card__meta">{{ g.headcount }} · {{ g.shift_type }}</span>
                </div>
                <ul class="schedule-group-card__lines">
                  <li v-for="(sl, si) in (g.lines || [])" :key="si">{{ sl }}</li>
                </ul>
              </div>
            </section>

            <details v-if="rulesConfigKeys.length" class="rules-details">
              <summary>默认参数（只读）</summary>
              <dl class="rules-dl">
                <template v-for="k in rulesConfigKeys" :key="k">
                  <dt>{{ k }}</dt>
                  <dd>{{ formatConfigValue(rulesConfig[k]) }}</dd>
                </template>
              </dl>
            </details>
          </template>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./home/（composable + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import { useAttendanceHome } from './home/useAttendanceHome'

const {
  file, outputRelpath, templateRelpath, month, headerRow,
  usePersonnelRoster, useLlm, loading, loadingDl, err, okMsg, lastOutputRelpath,
  rulesLoading, rulesErr, rulesLines, rulesWindow, rulesConfig, rulesConfigKeys,
  scheduleGroups, formatConfigValue, onFile, downloadOutput, doUploadConvert,
} = useAttendanceHome()
</script>

<style scoped src="./home/home.css"></style>
