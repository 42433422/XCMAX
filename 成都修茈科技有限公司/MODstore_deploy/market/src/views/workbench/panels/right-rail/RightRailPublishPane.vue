<script setup lang="ts">
import EmployeeSixDimPanel from '../../../../components/workbench/EmployeeSixDimPanel.vue'
import type { RightRailPublishApi } from '../../../../composables/useRightRailPublish'

/**
 * RightRail 上架面板（自 RightRail.vue 原样迁移）。
 * props.pub 为父级持有的上架域 API 对象（属性均为稳定 ref / 纯函数），
 * 解构后与父级共享同一 ref 实例，状态常驻父级、跨 tab 切换不丢失。
 */
const props = defineProps<{
  pub: RightRailPublishApi
  /** store.target.id（string | null），仅用于禁用态判断 */
  targetId: string | null
}>()

const {
  publishState,
  publishError,
  benchResult,
  auditAnimPhase,
  auditAnimScores,
  DIM_LABELS,
  startBenchTest,
  publishEmployee,
  downloadPack,
  syncState,
  syncError,
  syncResult,
  syncCurrentStep,
  SYNC_STEPS,
  syncStepMeta,
  startSyncTest,
} = props.pub
</script>

<template>
  <div class="rr-pane publish-pane">

    <!-- ① 本地调试：下载员工包 -->
    <section class="pub-section">
      <h4 class="pub-section-title">本地调试</h4>
      <p class="pub-hint">服务端会将画布补全为登记级格式（如 artifact、employee、employee_config_v2 等）。两种下载均为单个 .xcemp 文件。</p>
      <p class="pub-hint pub-hint--dim"><strong>平台包</strong>：与「保存」解压到库内的结构一致，用于导入宿主 / 上架仓库。</p>
      <button class="pub-btn pub-btn--secondary" :disabled="!targetId" @click="downloadPack(false)">
        ↓ 下载平台包 (.xcemp)
      </button>
      <p class="pub-hint pub-hint--dim pub-hint--standalone-gap"><strong>本地独立包</strong>：在平台包基础上嵌入 zipapp（<code>__main__.py</code>、<code>standalone/</code>），可在本机执行：</p>
      <p class="pub-hint pub-hint--dim">
        <code>python xxx.xcemp validate</code> — 校验包结构<br>
        <code>python xxx.xcemp run</code> — 无 LLM 机械检查<br>
        <code>python xxx.xcemp run --llm</code> — 需设置 <code>OPENAI_API_KEY</code> 或 <code>DEEPSEEK_API_KEY</code>
      </p>
      <button class="pub-btn pub-btn--secondary" :disabled="!targetId" @click="downloadPack(true)">
        ↓ 下载本地独立包 (.xcemp)
      </button>
    </section>

    <!-- ② 同步测试区（bench + publish + 推送宿主 一步完成） -->
    <section class="pub-section pub-section--sync">
      <h4 class="pub-section-title">同步测试</h4>
      <p class="pub-hint">一键完成：基准测试 → 发布到目录 → 推送宿主安装，成功后员工出现在「一键托管」面板与员工工作流管理页。</p>

      <button
        class="pub-btn pub-btn--sync"
        :disabled="syncState === 'running' || !targetId"
        @click="startSyncTest"
      >
        <span v-if="syncState === 'running'" class="pub-spinner" />
        {{ syncState === 'running' ? '同步中…' : syncState === 'done' ? '✓ 同步完成' : '开始同步测试' }}
      </button>

      <!-- 步骤进度流 -->
      <div v-if="syncState !== 'idle'" class="sync-steps">
        <div
          v-for="(step, i) in SYNC_STEPS"
          :key="step"
          class="sync-step"
          :class="{
            'sync-step--done': i < syncCurrentStep,
            'sync-step--active': i === syncCurrentStep && syncState === 'running',
            'sync-step--finish': i === syncCurrentStep && syncState === 'done',
            'sync-step--error': i === syncCurrentStep && syncState === 'error',
          }"
        >
          <span class="sync-step-dot" />
          <div class="sync-step-main">
            <span class="sync-step-label">{{ step }}</span>
            <span v-if="syncStepMeta(i)" class="sync-step-meta">{{ syncStepMeta(i) }}</span>
          </div>
        </div>
      </div>

      <!-- 同步结果 -->
      <div v-if="syncResult" class="sync-result">
        <template v-if="syncResult.ok">
          <div class="sync-ok-box">
            <span class="sync-ok-icon">✓</span>
            <div class="sync-ok-text">
              <strong>{{ syncResult.pkg_id }}</strong> v{{ syncResult.version }}<br />
              <span v-if="syncResult.fhd_install?.ok">已推送到宿主并安装</span>
              <span v-else-if="syncResult.fhd_install?.skipped">未配置宿主 URL，已发布到 catalog</span>
              <span v-else class="sync-warn">宿主推送失败：{{ syncResult.fhd_install?.error }}</span>
            </div>
          </div>
          <!-- 综合得分简报 -->
          <div
            v-if="syncResult.bench"
            class="pub-overall"
            :class="syncResult.bench.passed ? 'pub-overall--pass' : 'pub-overall--fail'"
          >
            <span class="pub-overall-score">{{ syncResult.bench.overall_score.toFixed(1) }}</span>
            <span class="pub-overall-label">{{ syncResult.bench.passed ? '基准通过' : '基准未达标' }}</span>
          </div>
        </template>
        <p v-else class="pub-error">{{ syncResult.reason }}</p>
      </div>

      <p v-if="syncState === 'error' && syncError && !syncResult" class="pub-error">{{ syncError }}</p>
    </section>

    <!-- ③ 上架测试区（单独运行，不推送宿主） -->
    <section class="pub-section">
      <h4 class="pub-section-title">上架测试</h4>
      <p class="pub-hint">大模型将生成 1–5 级共 15 项测试任务，根据完成率与消耗量量化打分，再进行五维审核与六维 LLM 评估。</p>

      <button
        class="pub-btn"
        :disabled="publishState === 'testing' || !targetId"
        @click="startBenchTest"
      >
        <span v-if="publishState === 'testing'" class="pub-spinner" />
        {{ publishState === 'testing' ? '测试中，请稍候…' : '开始测试' }}
      </button>

      <!-- 错误提示 -->
      <p v-if="publishState === 'error' && publishError" class="pub-error">{{ publishError }}</p>

      <!-- 任务完成后显示结果 -->
      <div v-if="benchResult" class="pub-result">

        <!-- 1-5 级得分条 -->
        <div class="pub-levels">
          <div v-for="lv in 5" :key="lv" class="pub-level">
            <span class="pub-level-label">Lv{{ lv }}</span>
            <div class="pub-level-bar">
              <div
                class="pub-level-fill"
                :style="{
                  width: (benchResult.level_scores[lv] ?? 0) + '%',
                  background: (benchResult.level_scores[lv] ?? 0) >= 60 ? '#22c55e' : '#f97316',
                }"
              />
            </div>
            <span class="pub-level-score">{{ (benchResult.level_scores[lv] ?? 0).toFixed(0) }}</span>
          </div>
        </div>

        <!-- 五维审核动画 -->
        <div class="pub-audit">
          <p class="pub-audit-title">五维审核</p>

          <!-- 测试步骤流 -->
          <div class="pub-audit-stages">
            <div class="pub-stage" :class="{ 'pub-stage--done': auditAnimPhase !== 'idle' }">生成测试任务</div>
            <div class="pub-stage-arrow">→</div>
            <div class="pub-stage" :class="{ 'pub-stage--done': auditAnimPhase !== 'idle' }">执行任务</div>
            <div class="pub-stage-arrow">→</div>
            <div class="pub-stage" :class="{ 'pub-stage--done': auditAnimPhase !== 'idle' }">统计消耗</div>
            <div class="pub-stage-arrow">→</div>
            <div class="pub-stage" :class="{ 'pub-stage--done': auditAnimPhase !== 'idle' }">五维审核</div>
            <div class="pub-stage-arrow">→</div>
            <div class="pub-stage" :class="{ 'pub-stage--done': auditAnimPhase === 'done' }">
              {{ benchResult.passed ? '可上架' : '未通过' }}
            </div>
          </div>

          <!-- 五维卡片网格 -->
          <div v-if="benchResult.audit?.dimensions" class="pub-dim-grid">
            <div
              v-for="(dim, key, idx) in benchResult.audit.dimensions"
              :key="key"
              class="pub-dim-card"
              :class="{
                'pub-dim-card--active': auditAnimPhase !== 'idle',
                'pub-dim-card--pass': dim.score >= 60,
                'pub-dim-card--fail': dim.score < 60,
              }"
              :style="{ animationDelay: `${(idx as number) * 260}ms` }"
            >
              <!-- 环形进度 SVG -->
              <svg class="pub-ring" viewBox="0 0 44 44">
                <circle class="pub-ring-bg" cx="22" cy="22" r="18" />
                <circle
                  class="pub-ring-fill"
                  cx="22" cy="22" r="18"
                  :stroke="dim.score >= 60 ? '#4ade80' : '#f87171'"
                  :stroke-dasharray="`${(auditAnimScores[key] ?? 0) * 1.131} 113.1`"
                />
              </svg>
              <span class="pub-dim-score">{{ auditAnimScores[key] ?? 0 }}</span>
              <span class="pub-dim-label">{{ DIM_LABELS[key] ?? key }}</span>
              <!-- 第一条 reason 作为 tooltip -->
              <span v-if="dim.reasons?.[0]" class="pub-dim-reason">{{ dim.reasons[0] }}</span>
            </div>
          </div>

          <!-- 审核失败兜底文字 -->
          <p v-if="benchResult.audit?.error" class="pub-audit-err">
            审核异常：{{ benchResult.audit.error }}
          </p>
        </div>

        <!-- 综合得分总结 -->
        <div class="pub-overall" :class="benchResult.passed ? 'pub-overall--pass' : 'pub-overall--fail'">
          <span class="pub-overall-score">{{ benchResult.overall_score.toFixed(1) }}</span>
          <span class="pub-overall-label">
            {{ benchResult.passed ? '通过测试，可提交上架' : '未达标，请完善员工能力后重试' }}
          </span>
        </div>

        <!-- 六维 LLM 评估（hex-quality-assessor） -->
        <div v-if="benchResult.six_dimension" class="pub-six-dim">
          <p class="pub-audit-title">六维质量评估</p>
          <p v-if="benchResult.six_dimension.llm_summary" class="pub-hint pub-six-dim-summary">
            {{ benchResult.six_dimension.llm_summary }}
          </p>
          <EmployeeSixDimPanel
            :report="benchResult.six_dimension"
            title=""
            compact
            :show-grade-scale="false"
          />
        </div>
        <p v-else-if="benchResult.six_dimension_llm_meta?.llm_error" class="pub-audit-err">
          六维 LLM 评估失败：{{ benchResult.six_dimension_llm_meta.llm_error }}
        </p>
      </div>
    </section>

    <!-- ③ 上架区（仅测试通过后显示） -->
    <section v-if="benchResult?.passed" class="pub-section pub-section--publish">
      <h4 class="pub-section-title">提交上架</h4>
      <button
        class="pub-btn pub-btn--primary"
        :disabled="publishState === 'publishing' || publishState === 'published'"
        @click="publishEmployee"
      >
        <span v-if="publishState === 'publishing'" class="pub-spinner" />
        {{ publishState === 'published' ? '✓ 已上架' : publishState === 'publishing' ? '上架中…' : '提交上架到目录' }}
      </button>
      <p v-if="publishState === 'published'" class="pub-ok">员工包已写入商店目录，可在「员工制作」页查看和分发。</p>
      <p v-if="publishState === 'error' && publishError" class="pub-error">{{ publishError }}</p>
    </section>

  </div>
</template>
