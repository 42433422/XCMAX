<template>
  <div class="page-view cs-page" id="view-internal-customer-service">
    <div class="page-content">
      <!-- 顶栏：标题 + 量化数据 + 操作 -->
      <header class="cs-topbar">
        <div class="cs-topbar-left">
          <h2>内部客服</h2>
          <div v-if="stats" class="cs-metrics">
            <span class="cs-metric"><em>{{ stats.pending }}</em> 待受理</span>
            <span class="cs-metric-sep">·</span>
            <span class="cs-metric"><em>{{ stats.processing }}</em> 处理中</span>
            <span class="cs-metric-sep">·</span>
            <span class="cs-metric"><em>{{ stats.resolved }}</em> 已回复</span>
            <span class="cs-metric-sep">·</span>
            <span class="cs-metric muted"><em>{{ stats.total }}</em> 累计</span>
          </div>
        </div>
        <div class="cs-topbar-actions">
          <button class="btn btn-sm btn-secondary" type="button" @click="openAddCustomerModal">添加客户</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="refresh">刷新</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="goDataSources">导入微信</button>
        </div>
      </header>

      <section v-if="!loadingEnterpriseUsers && enterpriseUsers.length" class="cs-funnel-bar">
        <button type="button" class="cs-funnel-toggle" @click="funnelExpanded = !funnelExpanded">
          商机漏斗
          <span class="muted">（{{ funnelTotalClients }} 客户）</span>
          <i class="fa" :class="funnelExpanded ? 'fa-chevron-up' : 'fa-chevron-down'" aria-hidden="true" />
        </button>
        <div v-show="funnelExpanded" class="cs-funnel-body">
          <p v-if="funnelLoading" class="muted">加载漏斗…</p>
          <p v-else-if="funnelError" class="form-error cs-funnel-error">
            {{ funnelError }}
            <button type="button" class="btn btn-xs btn-ghost" @click="loadPipelineFunnel">重试</button>
          </p>
          <div v-else class="cs-funnel-stages">
            <button
              v-for="st in funnelStages"
              :key="st.id"
              type="button"
              class="cs-funnel-stage"
              :class="{ active: funnelStageFilter === st.id, 'has-count': st.count > 0 }"
              :title="st.label"
              @click="toggleFunnelStageFilter(st.id)"
            >
              <span class="cs-funnel-stage__count">{{ st.count }}</span>
              <span class="cs-funnel-stage__label">{{ st.label }}</span>
            </button>
          </div>
          <p v-if="funnelStageFilter" class="cs-funnel-filter-hint muted">
            已筛选阶段「{{ stageLabel(funnelStageFilter) }}」
            <button type="button" class="btn btn-xs btn-ghost" @click="funnelStageFilter = ''">显示全部</button>
          </p>
        </div>
      </section>

      <div v-if="loadingEnterpriseUsers" class="loading-hint">加载客户…</div>
      <div v-else-if="!enterpriseUsers.length" class="cs-empty">
        <p>暂无企业客户</p>
        <button type="button" class="btn btn-sm btn-secondary" @click="goAdminEntitlements">去用户 Mod 管理</button>
      </div>

      <div v-else class="cs-clients">
        <article
          v-for="u in filteredEnterpriseUsers"
          :key="u.id"
          class="cs-card"
          :class="{ 'is-open': expandedClientId === u.id }"
        >
          <!-- 收起：仅名字；展开：名字 + 工作台 -->
          <button type="button" class="cs-card-head" @click="toggleClient(u.id)">
            <span class="cs-card-name" :title="cardNameTitle(u)">{{ displayClientName(u) }}</span>
            <span v-if="!u.isEnterprise && u.hasPipeline" class="cs-card-badge">待设企业</span>
            <span
              v-if="getClientSummary(u.id).stage && getClientSummary(u.id).stage !== 'idle'"
              class="cs-card-stage"
            >{{ stageLabel(getClientSummary(u.id).stage) }}</span>
          </button>

          <div v-if="expandedClientId === u.id" class="cs-card-body">
            <section class="cs-enterprise-creds">
              <div class="cs-enterprise-creds__head">
                <span class="cs-stage-badge">企业专属账号</span>
                <span v-if="enterpriseCreds.is_enterprise" class="cs-tag cs-tag--ok">已开通</span>
              </div>
              <p class="muted cs-enterprise-creds__hint">
                用于修茈市场 (xiu-ci.com) 与企业版 XCAGI 宿主登录；密码在生成或重置后回显并写入客服档案。
              </p>
              <p v-if="enterpriseCreds.loading" class="muted">加载账号信息…</p>
              <template v-else>
                <dl class="cs-enterprise-creds__dl">
                  <dt>登录账号</dt>
                  <dd>
                    <code class="cs-enterprise-creds__code">{{ enterpriseCreds.username || '—' }}</code>
                    <button
                      v-if="enterpriseCreds.username"
                      type="button"
                      class="btn btn-xs"
                      @click="copyEnterpriseCredential('username')"
                    >
                      复制
                    </button>
                  </dd>
                  <template v-if="enterpriseCreds.email">
                    <dt>邮箱</dt>
                    <dd><code class="cs-enterprise-creds__code">{{ enterpriseCreds.email }}</code></dd>
                  </template>
                  <dt>登录密码</dt>
                  <dd>
                    <code v-if="enterpriseCreds.password" class="cs-enterprise-creds__code">{{ enterpriseCreds.password }}</code>
                    <span v-else class="muted">未记录明文（可点击下方生成临时密码）</span>
                    <button
                      v-if="enterpriseCreds.password"
                      type="button"
                      class="btn btn-xs"
                      @click="copyEnterpriseCredential('password')"
                    >
                      复制
                    </button>
                  </dd>
                  <template v-if="enterpriseCreds.issued_at">
                    <dt>签发时间</dt>
                    <dd class="muted">{{ formatPassivePollTime(enterpriseCreds.issued_at) }}</dd>
                  </template>
                </dl>
                <p v-if="enterpriseCreds.error" class="form-error">{{ enterpriseCreds.error }}</p>
                <div class="cs-enterprise-creds__actions">
                  <button
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="enterpriseCreds.issuing || !selectedUserId"
                    @click="issueEnterpriseCredentials"
                  >
                    {{
                      enterpriseCreds.issuing
                        ? '生成中…'
                        : (enterpriseCreds.password_recorded ? '重新生成临时密码' : '生成临时密码')
                    }}
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs"
                    :disabled="enterpriseCreds.loading"
                    @click="loadEnterpriseCredentials"
                  >
                    刷新
                  </button>
                </div>
              </template>
            </section>

            <!-- 商机进度：只读展示 + 阶段说明（不切换下方功能区） -->
            <section class="cs-progress-panel" :class="{ 'has-unsaved-changes': stageDraftDirty }">
              <div class="cs-progress-bar">
                <div class="cs-progress-track">
                  <div class="cs-progress-fill" :style="{ width: progressPercent(u.id) + '%' }" />
                </div>
                <ol class="cs-progress-steps">
                  <li
                    v-for="(st, idx) in pipelineStages"
                    :key="st.id"
                    class="cs-progress-step"
                    :class="[stepperItemClass(st.id, idx), { 'is-pick': stageDraft === st.id }]"
                    role="button"
                    tabindex="0"
                    :title="st.id === currentStageId ? `当前阶段：${st.label}` : `预选：${st.label}（需点保存阶段）`"
                    @click="pickPipelineStageDraft(st.id)"
                    @keydown.enter.prevent="pickPipelineStageDraft(st.id)"
                  >
                    <span class="cs-progress-dot">{{ idx + 1 }}</span>
                    <span class="cs-progress-label">{{ st.label }}</span>
                  </li>
                </ol>
              </div>

              <div class="cs-stage-intro">
                <div class="cs-stage-intro-head">
                  <div class="cs-stage-intro-title">
                    <span class="cs-stage-badge">{{ stageDraftDirty ? '预选阶段' : '当前阶段' }}</span>
                    <strong>{{ stageLabel(viewingStageId) }}</strong>
                    <span v-if="stageDraftDirty" class="muted cs-stage-viewing-from">（当前为「{{ stageLabel(currentStageId) }}」）</span>
                  </div>
                  <div v-if="showIntakeStageShortcuts" class="cs-stage-intake-quick">
                    <button
                      type="button"
                      class="btn btn-xs"
                      :disabled="intakeLinkLoading"
                      @click="openOfficialIntakeForm"
                    >
                      帮客户填写
                    </button>
                    <button
                      type="button"
                      class="btn btn-xs"
                      :disabled="intakeLinkLoading"
                      @click="copyIntakeFormUrl"
                    >
                      {{ intakeLinkLoading ? '获取中…' : '复制表单链接' }}
                    </button>
                  </div>
                  <div v-if="currentStageId === 'intake' || currentStageId === 'intake_done'" class="cs-audit-code-row">
                    <label class="cs-audit-code-label">
                      <span class="muted">客户审核码</span>
                      <input
                        v-model="intakeAuditCode"
                        type="text"
                        class="cs-input cs-audit-code-input"
                        placeholder="XC-000123"
                        autocomplete="off"
                        @keydown.enter.prevent="fetchIntakeFormByAuditCode"
                      />
                    </label>
                    <button
                      type="button"
                      class="btn btn-xs"
                      :disabled="auditCodeFetching || auditCodeRedeeming || !intakeAuditCode.trim()"
                      @click="fetchIntakeFormByAuditCode"
                    >
                      {{ auditCodeFetching ? '获取中…' : '获取表单' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-xs btn-accent"
                      :disabled="auditCodeRedeeming || auditCodeFetching || !intakeAuditCode.trim()"
                      @click="redeemIntakeAuditCode"
                    >
                      {{ auditCodeRedeeming ? '确认中…' : '确认并进入下一阶段' }}
                    </button>
                  </div>
                  <p v-if="auditCodeError" class="form-error cs-audit-code-error">{{ auditCodeError }}</p>
                  <div v-if="intakeAuditPreviewRows?.length" class="cs-intake-summary cs-audit-preview">
                    <p class="cs-intake-summary__title">
                      已拉取官网问卷（审核码 {{ intakeAuditPreviewCode }}）
                      <span v-if="intakeAuditPreviewAt" class="cs-intake-summary__time">{{ formatPassivePollTime(intakeAuditPreviewAt) }}</span>
                    </p>
                    <dl class="cs-intake-summary__dl">
                      <template v-for="row in intakeAuditPreviewRows" :key="'audit-' + row.label">
                        <dt>{{ row.label }}</dt>
                        <dd>{{ row.value }}</dd>
                      </template>
                    </dl>
                    <p class="muted cs-audit-preview-hint">核对无误后点击「确认并进入下一阶段」写入客户档案。</p>
                  </div>
                  <div class="cs-stage-intro-actions">
                    <label class="cs-stage-edit">
                      <span class="muted">调整阶段</span>
                      <select v-model="stageDraft" class="cs-stage-select" :disabled="stageSaving">
                        <option v-for="st in pipelineStages" :key="'sel-' + st.id" :value="st.id">
                          {{ st.label }}
                        </option>
                      </select>
                    </label>
                    <button
                      type="button"
                      class="btn btn-xs btn-accent"
                      :class="{ 'is-pending': stageDraftDirty }"
                      :disabled="!canSavePipelineStage"
                      :title="saveStageButtonTitle"
                      @click="savePipelineStage()"
                    >
                      {{ stageSaving ? '保存中…' : (stageDraftDirty ? `保存为「${stageLabel(stageDraft)}」` : '保存阶段') }}
                    </button>
                    <button type="button" class="btn btn-xs cs-analyze-btn" :disabled="pipelineAnalyzing" @click="analyzeCustomerProgress">
                      {{ pipelineAnalyzing ? '分析中…' : '分析进度' }}
                    </button>
                  </div>
                </div>
                <p v-if="stageDraftDirty" class="cs-stage-pending-hint">
                  已预选「{{ stageLabel(stageDraft) }}」，请确认后点击「保存为…」才会写入（点进度条不会自动保存）。
                </p>
                <p class="muted cs-stage-edit-hint">调整阶段：在进度条或下拉框预选，再点「保存阶段」。「分析进度」仅根据群聊建议阶段，不会自动改当前阶段。</p>
                <p v-if="currentStageGuide.headline" class="cs-stage-lead">{{ currentStageGuide.headline }}</p>
                <p class="cs-stage-desc">{{ currentStageGuide.description }}</p>
                <ul v-if="currentStageGuide.checklist.length" class="cs-stage-checklist">
                  <li
                    v-for="item in currentStageGuide.checklist"
                    :key="item.key"
                    :class="{ 'is-done': checklistItemDone(item.key) }"
                  >
                    <span class="cs-check-mark">{{ checklistItemDone(item.key) ? '✓' : '○' }}</span>
                    {{ item.text }}
                  </li>
                </ul>
                <p v-if="intakeSubmittedAwaitingAdvance && !autoStageAdvancing" class="cs-stage-pending-hint">
                  检测到需求表单已提交，系统应自动进入「需求已提交」。若仍停在本阶段，请点「分析进度」或重新展开本客户卡片。
                </p>
                <p v-if="autoStageAdvancing" class="muted cs-auto-advance-hint">清单已完成，正在进入下一阶段…</p>
                <p v-if="currentStageGuide.actionHint" class="cs-stage-hint">{{ currentStageGuide.actionHint }}</p>
                <div v-if="currentStageId === 'connected'" class="cs-stage-actions">
                  <button
                    v-if="!customerPipeline.connected_welcome_sent"
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="connectedWelcomeSending"
                    @click="sendConnectedWelcome()"
                  >
                    {{ connectedWelcomeSending ? '发送中…' : '发送建联欢迎语' }}
                  </button>
                  <button
                    v-else
                    type="button"
                    class="btn btn-xs btn-ghost"
                    :disabled="connectedWelcomeSending"
                    @click="sendConnectedWelcome(true)"
                  >
                    {{ connectedWelcomeSending ? '发送中…' : '重新发送欢迎语' }}
                  </button>
                </div>
                <p v-if="currentStageId === 'connected' && customerPipeline.connected_welcome_sent" class="cs-stage-done-hint">
                  建联欢迎语已发送至微信群（若群内未收到可点「重新发送欢迎语」）
                </p>
                <p v-if="stageRank(currentStageId) >= stageRank('connected')" class="cs-stage-done-hint muted">
                  客户提交需求表单（审核码兑换或官网填写）后，将自动设为企业客户，并把卡片名称改为表单中的公司名。
                </p>
                <div v-if="currentStageId === 'intake'" class="cs-stage-actions">
                  <button
                    v-if="!customerPipeline.intake_form_notice_sent"
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="intakeNoticeSending"
                    @click="sendIntakeFormNotice()"
                  >
                    {{ intakeNoticeSending ? '发送中…' : '发送表单链接到微信群' }}
                  </button>
                  <button
                    v-else
                    type="button"
                    class="btn btn-xs btn-ghost"
                    :disabled="intakeNoticeSending"
                    @click="sendIntakeFormNotice(true)"
                  >
                    {{ intakeNoticeSending ? '发送中…' : '重新发送表单说明' }}
                  </button>
                  <button type="button" class="btn btn-xs" :disabled="intakeLinkLoading" @click="copyIntakeFormUrl">
                    复制表单链接
                  </button>
                </div>
                <p v-if="currentStageId === 'intake' && customerPipeline.intake_form_notice_sent" class="cs-stage-done-hint">
                  表单链接与填写说明已发送至微信群（提交后请让客户把审核码发在群内）
                </p>
                <div v-if="showCrmFinalizeActions" class="cs-stage-actions cs-intake-done-actions">
                  <button
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="intakeFinalizeLoading"
                    @click="finalizeIntakeFromPipeline()"
                  >
                    {{ intakeFinalizeLoading ? '同步中…' : '同步 CRM 并关联 ERP' }}
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs"
                    :disabled="intakeFinalizeLoading || !customerPipeline.intake_submitted_at"
                    @click="syncDemandFormFromMarket()"
                  >
                    拉取官网最新提交
                  </button>
                </div>
                <p v-if="showCrmFinalizeActions && customerPipeline.erp_customer_name" class="cs-stage-done-hint">
                  已关联 ERP：{{ customerPipeline.erp_customer_name }}
                  <span v-if="customerPipeline.crm_funnel_synced_at" class="muted">
                    · {{ formatPassivePollTime(customerPipeline.crm_funnel_synced_at) }}
                  </span>
                </p>
                <p
                  v-else-if="showCrmFinalizeActions && customerPipeline.intake_submitted_at"
                  class="cs-stage-done-hint cs-stage-warn-hint"
                >
                  需求已入库，CRM/ERP 未完全关联；打开客户时将自动尝试同步。也可手动点「同步 CRM 并关联 ERP」。
                </p>
                <p
                  v-if="showIntakeFunnelWarn"
                  class="cs-stage-done-hint cs-stage-warn-hint"
                >
                  官网/contact 表单提交会自动进入 CRM 漏斗；内部手工录入请点「同步 CRM 并关联 ERP」。
                </p>
                <p v-if="currentStageGuide.groupTip" class="cs-stage-group-tip">{{ currentStageGuide.groupTip }}</p>
                <div v-if="showCrmLinkagePanel" class="cs-crm-panel">
                  <p class="cs-crm-panel__title">销售 CRM（线索 → 商机 → 报价）</p>
                  <dl class="cs-crm-panel__dl">
                    <dt>商机 ID</dt>
                    <dd>{{ customerPipeline.crm_opportunity_id || '未入库' }}</dd>
                    <dt>官网需求单</dt>
                    <dd>{{ formatAuditCodeFromLandingId(customerPipeline.landing_contact_id) || '—' }}</dd>
                    <dt>ERP 客户</dt>
                    <dd>{{ customerPipeline.erp_customer_name || '未关联' }}</dd>
                    <dt>报价单</dt>
                    <dd>
                      <template v-if="customerPipeline.crm_quote_id">
                        #{{ customerPipeline.crm_quote_id }}
                        <span v-if="crmQuoteStatus" class="muted">（{{ crmQuoteStatus }}）</span>
                        <span v-if="crmQuoteSummary" class="cs-crm-quote-sum">{{ crmQuoteSummary }}</span>
                      </template>
                      <template v-else>待生成</template>
                    </dd>
                  </dl>
                  <button
                    type="button"
                    class="btn btn-xs"
                    :disabled="crmSyncLoading || !selectedUserId"
                    @click="syncCrmRecord()"
                  >
                    {{ crmSyncLoading ? '同步中…' : '刷新 CRM / 报价记录' }}
                  </button>
                  <button
                    v-if="showCrmFinalizeActions"
                    type="button"
                    class="btn btn-xs btn-secondary"
                    :disabled="crmRepairLoading || !selectedUserId"
                    @click="repairCrmRecord()"
                  >
                    {{ crmRepairLoading ? '修复中…' : '一键修复 CRM/ERP' }}
                  </button>
                  <div class="cs-external-crm">
                    <p class="cs-external-crm__title muted">外部 CRM（HubSpot 等）</p>
                    <p class="cs-external-crm__hint muted">
                      出站推送商机；可手动从 HubSpot / Salesforce 拉取阶段回写 Pipeline（非 webhook 实时同步）。
                      自建 Pipeline ↔ CRM SQLite 仍为双向同步。
                    </p>
                    <p v-if="customerPipeline.external_crm_deal_id" class="muted cs-external-crm__meta">
                      Deal ID：<code>{{ customerPipeline.external_crm_deal_id }}</code>
                    </p>
                    <p v-if="customerPipeline.external_crm_last_at" class="muted cs-external-crm__meta">
                      最近推送 {{ formatPassivePollTime(customerPipeline.external_crm_last_at) }}
                      <span v-if="externalCrmStatusLabel"> · {{ externalCrmStatusLabel }}</span>
                    </p>
                    <p v-else class="muted">尚未推送到 HubSpot / Salesforce</p>
                    <p
                      v-if="customerPipeline.external_crm_last_pull_at"
                      class="muted cs-external-crm__meta"
                    >
                      最近拉取 {{ formatPassivePollTime(customerPipeline.external_crm_last_pull_at) }}
                      <span v-if="externalCrmPullStatusLabel"> · {{ externalCrmPullStatusLabel }}</span>
                    </p>
                    <p v-if="customerPipeline.external_crm_last_error" class="cs-stage-warn-hint">
                      {{ customerPipeline.external_crm_last_error }}
                    </p>
                    <p v-if="customerPipeline.external_crm_last_pull_error" class="cs-stage-warn-hint">
                      {{ customerPipeline.external_crm_last_pull_error }}
                    </p>
                    <div class="cs-external-crm__actions">
                      <button
                        type="button"
                        class="btn btn-xs"
                        :disabled="externalCrmPushLoading || !selectedUserId"
                        @click="pushExternalCrm()"
                      >
                        {{ externalCrmPushLoading ? '推送中…' : '推送到外部 CRM' }}
                      </button>
                      <button
                        type="button"
                        class="btn btn-xs btn-secondary"
                        :disabled="externalCrmPullLoading || !selectedUserId"
                        @click="pullExternalCrm()"
                      >
                        {{ externalCrmPullLoading ? '拉取中…' : '从外部 CRM 拉取阶段' }}
                      </button>
                    </div>
                  </div>
                </div>
                <div v-if="showCrmLinkagePanel" class="cs-crm-panel cs-finance-panel">
                  <p class="cs-crm-panel__title">财务单据（统一）</p>
                  <p v-if="financeLedgerLoading" class="muted">加载中…</p>
                  <p v-else-if="!financeLedgerItems.length" class="muted">
                    到款或开票后自动归档；也可在侧栏「财务统计」查看全局列表。
                  </p>
                  <table v-else class="cs-finance-table">
                    <thead>
                      <tr>
                        <th>轨道</th>
                        <th>单号</th>
                        <th>金额</th>
                        <th>状态</th>
                        <th>时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in financeLedgerItems" :key="`${row.source_type}-${row.source_id}`">
                        <td>{{ financeTrackLabel(row.track) }}</td>
                        <td>{{ row.invoice_no || row.payment_ref || `${row.source_type}#${row.source_id}` }}</td>
                        <td>¥{{ formatLedgerYuan(row.amount_cents) }}</td>
                        <td>{{ row.status }}</td>
                        <td>{{ formatLedgerTime(row.occurred_at) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="showQuoteNegotiateActions" class="cs-stage-actions cs-stage-actions--quote">
                  <button type="button" class="btn btn-xs" @click="copyGroupScript(groupScriptForStage())">
                    复制{{ groupScriptActionLabel }}话术
                  </button>
                  <button type="button" class="btn btn-xs" @click="fillWechatDraft(groupScriptForStage())">
                    填入下方群消息
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="wechatSend.loading || !wechatSendContactName"
                    @click="sendGroupScript(groupScriptForStage())"
                  >
                    {{ wechatSend.loading ? '发送中…' : `发送${groupScriptActionLabel}到微信群` }}
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs btn-ghost"
                    :disabled="pipelineAnalyzing"
                    @click="analyzeCustomerProgress()"
                  >
                    {{ pipelineAnalyzing ? '分析中…' : '同步群聊并分析进度' }}
                  </button>
                  <button
                    v-if="currentStageId === 'intake_done'"
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="stageSaving"
                    @click="savePipelineStage('quoted', { confirmMessage: '群内已报价？将阶段标记为「已报价」。' })"
                  >
                    标记为已报价
                  </button>
                  <button
                    v-if="currentStageId === 'quoted'"
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="stageSaving"
                    @click="savePipelineStage('negotiating', { confirmMessage: '进入议价？将阶段标记为「议价」。' })"
                  >
                    标记为议价中
                  </button>
                  <button
                    v-if="currentStageId === 'negotiating'"
                    type="button"
                    class="btn btn-xs btn-accent"
                    :disabled="stageSaving"
                    @click="savePipelineStage('contract_pending', { confirmMessage: '群内已谈妥？将阶段标记为「待签」。' })"
                  >
                    标记为待签
                  </button>
                </div>
                <p v-if="currentStageGuide.comingSoon" class="cs-coming-soon cs-coming-soon-inline">{{ currentStageGuide.comingSoon }}</p>
              </div>

              <details class="cs-stage-roadmap">
                <summary>查看全流程 · 各阶段要做什么</summary>
                <div class="cs-roadmap-grid">
                  <article
                    v-for="st in pipelineStages"
                    :key="'roadmap-' + st.id"
                    class="cs-roadmap-item"
                    :class="stepperItemClass(st.id, 0)"
                  >
                    <h5 class="cs-roadmap-title">{{ st.label }}</h5>
                    <p class="cs-roadmap-headline">{{ stageGuideFor(st.id).headline }}</p>
                    <ul v-if="stageGuideFor(st.id).checklist.length" class="cs-roadmap-todos">
                      <li v-for="item in stageGuideFor(st.id).checklist" :key="item.key">{{ item.text }}</li>
                    </ul>
                  </article>
                </div>
              </details>
            </section>

            <!-- 微信：绑定与消息分开，互不切换 -->
            <div class="cs-wechat-split">
              <section class="cs-block">
                <h4 class="cs-block-title">群聊绑定</h4>
                <div v-if="loadingWechatGroups" class="loading-hint">加载群列表…</div>
                <div v-else-if="!wechatGroupsCatalog.length" class="cs-block-empty">
                  <button type="button" class="btn btn-xs btn-accent" @click="goDataSources">去导入微信</button>
                </div>
                <template v-else>
                  <input v-model="groupFilter" type="search" class="cs-input" placeholder="搜索群名" @click.stop>
                  <p class="muted cs-group-list-hint">
                    共 {{ filteredBindGroups.length }} 个已导入群聊（可勾选多个绑定到当前企业）
                  </p>
                  <div class="cs-group-list">
                    <label v-for="g in filteredBindGroups" :key="g.id" class="cs-group-item" @click.stop>
                      <input v-model="selectedGroupIdStrings" type="checkbox" :value="String(g.id)" @change="onGroupSelectionChange">
                      <span>{{ g.contact_name || g.remark || '未命名群' }}</span>
                    </label>
                  </div>
                  <div class="cs-block-actions">
                    <button type="button" class="btn btn-xs" :disabled="savingBindings || !selectedGroupIdStrings.length" @click="handleSaveBindings()">
                      {{ savingBindings ? '保存中…' : '保存绑定' }}
                    </button>
                    <button type="button" class="btn btn-xs btn-accent" :disabled="savingBindings || !selectedGroupIdStrings.length" @click="handleSaveBindings({ syncAfter: true })">
                      保存并同步
                    </button>
                  </div>
                </template>
              </section>

              <section class="cs-block">
                <h4 class="cs-block-title">群聊消息</h4>
                <div class="cs-block-actions">
                  <button type="button" class="btn btn-xs btn-accent" :disabled="syncing" @click="handleSyncWechat()">
                    {{ syncing ? '同步中…' : '同步群聊' }}
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs"
                    :disabled="passivePolling || !selectedUserId"
                    title="先复制微信库到快照再读取，不直接打开源库"
                    @click="runPassivePoll(true)"
                  >
                    {{ passivePolling ? '探测中…' : '被动探测' }}
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs btn-ghost"
                    :disabled="passivePolling || passiveLoopBusy || !selectedUserId"
                    title="对绑定群内新消息自动回复（Mac 微信需在前台）"
                    @click="runPassivePoll(false)"
                  >
                    被动回复
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs btn-ghost"
                    :disabled="passivePolling || passiveLoopBusy || !hasBinding || !selectedUserId"
                    title="从当前群聊进度重新监听，只回复此后新消息"
                    @click="resetPassiveWatch"
                  >
                    重新监听
                  </button>
                </div>
                <div class="cs-passive-loop-row">
                  <label class="cs-passive-loop-toggle">
                    <input
                      v-model="passiveLoopEnabled"
                      type="checkbox"
                      :disabled="!selectedUserId || passivePolling"
                      @change="onPassiveLoopToggle"
                    />
                    <span>轮询客服</span>
                  </label>
                  <label class="cs-passive-loop-interval">
                    <span class="muted">间隔</span>
                    <select
                      v-model.number="passiveLoopIntervalSec"
                      :disabled="!passiveLoopEnabled"
                      @change="onPassiveLoopIntervalChange"
                    >
                      <option :value="10">10 秒</option>
                      <option :value="30">30 秒</option>
                      <option :value="60">60 秒</option>
                      <option :value="120">2 分钟</option>
                      <option :value="180">3 分钟</option>
                    </select>
                  </label>
                  <span v-if="passiveLoopEnabled && passiveLoopLastAt" class="muted cs-passive-loop-last">
                    {{ passiveLoopBusy ? '轮询中…' : `上次：${passiveLoopLastAt}` }}
                  </span>
                  <span v-if="passiveLlmStatus" class="muted cs-passive-llm-status">{{ passiveLlmStatus }}</span>
                  <span v-if="passiveLoopSummary" class="cs-passive-loop-summary">{{ passiveLoopSummary }}</span>
                </div>
                <p class="muted cs-passive-loop-hint">
                  开启后由<strong>服务端</strong>按间隔自动解密、回复（可离开本页或切换菜单，无需保持浏览器常开）。每个群每轮最多 1 条；Mac 上 LLM 与打开输入框并行。本页仅刷新状态，同群连发需间隔数秒。
                  若提示「本轮未入库新消息」，不等于微信没说话，可能是本机库尚未写入；请先点「同步群聊」。
                </p>
                <div v-if="wechatLoading" class="loading-hint">加载消息…</div>
                <ul v-else-if="formattedFeed.length" class="cs-feed">
                  <li v-for="row in formattedFeed" :key="row.contactId" class="cs-feed-item" @click="openWechatDrawer(row.contactId)">
                    <span class="cs-feed-name">{{ row.name }}</span>
                    <span class="cs-feed-text">{{ row.subtitle }}</span>
                    <span class="cs-feed-time">{{ row.timeLabel }}</span>
                  </li>
                </ul>
                <p v-else class="empty-hint">绑定群聊并同步后显示消息</p>
                <button v-if="latestFeedSubtitle" type="button" class="btn btn-xs" @click="copyLatestReplyHint">复制跟进话术</button>
                <div v-if="showWechatSendBlock" class="cs-send-compose">
                  <textarea v-model="wechatSend.message" rows="3" class="cs-input" placeholder="输入要发送到微信群的消息…" />
                  <div class="cs-block-actions">
                    <button
                      type="button"
                      class="btn btn-xs btn-accent"
                      :disabled="wechatSend.loading || !wechatSend.message.trim() || !wechatSendContactName"
                      @click="sendWechatToGroup"
                    >
                      {{ wechatSend.loading ? '发送中…' : '发送到微信群' }}
                    </button>
                  </div>
                  <p v-if="wechatSendContactName" class="cs-send-target">目标群：{{ wechatSendContactName }}</p>
                  <p v-if="wechatSend.error" class="cs-send-error">{{ wechatSend.error }}</p>
                </div>
              </section>
            </div>

            <!-- 商务操作：按实际阶段展示，与微信区独立 -->
            <section v-if="showIntakeBlock" class="cs-block cs-block-biz">
              <h4 class="cs-block-title">需求采集</h4>
              <p class="cs-block-desc">{{ PHASE_GUIDES.intake.description }}</p>
              <input v-model="demandIntake.clientName" type="text" class="cs-input" placeholder="默认填匹配的公司名，勿用登录账号">
              <textarea v-model="demandIntake.brief" rows="2" class="cs-input" placeholder="业务背景 *" />
              <div class="cs-block-actions">
                <button type="button" class="btn btn-xs btn-accent" :disabled="demandIntake.loading || !demandIntake.brief.trim()" @click="generateDemandIntake">
                  {{ demandIntake.loading ? '生成中…' : '生成话术' }}
                </button>
                <button type="button" class="btn btn-xs" :disabled="intakeLinkLoading" @click="openOfficialIntakeForm">
                  打开官网表单
                </button>
                <button v-if="demandIntake.messageText" type="button" class="btn btn-xs" @click="copyDemandMessage">复制到微信</button>
                <button
                  v-if="demandIntake.messageText"
                  type="button"
                  class="btn btn-xs btn-accent"
                  :disabled="demandIntake.sendingWechat || !wechatSendContactName"
                  @click="sendDemandIntakeToWechat"
                >
                  {{ demandIntake.sendingWechat ? '发送中…' : '一键发到微信群' }}
                </button>
              </div>
              <div v-if="intakeSubmissionSummary" class="cs-intake-summary">
                <p class="cs-intake-summary__title">
                  客户已提交需求
                  <span v-if="customerPipeline.intake_submitted_at" class="cs-intake-summary__time">{{ formatPassivePollTime(customerPipeline.intake_submitted_at) }}</span>
                </p>
                <dl class="cs-intake-summary__dl">
                  <template v-for="row in intakeSubmissionSummary" :key="row.label">
                    <dt>{{ row.label }}</dt>
                    <dd>{{ row.value }}</dd>
                  </template>
                </dl>
              </div>
              <pre v-if="demandIntake.messageText" class="cs-preview">{{ demandIntake.messageText }}</pre>
            </section>

            <section v-if="showContractBlock" class="cs-block cs-block-biz">
              <h4 class="cs-block-title">合同签约</h4>
              <p class="cs-block-desc">{{ PHASE_GUIDES.contract_pending.description }}</p>
              <div class="cs-contract-grid">
                <label class="cs-field"><span>甲方名称 *</span><input v-model="contractForm.party_a_name" class="cs-input"></label>
                <label class="cs-field"><span>信用代码</span><input v-model="contractForm.party_a_credit_code" class="cs-input"></label>
                <label class="cs-field"><span>合同金额 *</span><input v-model="contractForm.total_amount_number" class="cs-input" placeholder="10000.00"></label>
                <label class="cs-field cs-field-wide">
                  <span>关联市场订单号</span>
                  <input
                    v-model="contractForm.expected_out_trade_no"
                    class="cs-input"
                    placeholder="客户在修茈市场支付后的 out_trade_no，用于自动核对到款"
                  >
                </label>
                <label class="cs-field"><span>签署日期</span><input v-model="contractForm.sign_date" type="date" class="cs-input"></label>
                <label class="cs-field cs-field-wide"><span>主要功能/模块</span><textarea v-model="contractForm.main_function_list" rows="2" class="cs-input" /></label>
              </div>
              <div class="cs-block-actions">
                <a class="btn btn-xs" :href="contractSamplePdfUrl" target="_blank" rel="noopener">乙方预填样例</a>
                <button type="button" class="btn btn-xs" :disabled="contractForm.savingFields" @click="saveContractFields">
                  {{ contractForm.savingFields ? '保存中…' : '保存合同字段' }}
                </button>
                <button type="button" class="btn btn-xs btn-accent" :disabled="contractForm.loading" @click="generateContract">
                  {{ contractForm.loading ? '生成中…' : '生成合同' }}
                </button>
                <a v-if="contractForm.downloadUrl" class="btn btn-xs btn-accent" :href="contractForm.downloadUrl" download>下载</a>
                <button v-if="contractForm.wechatHint" type="button" class="btn btn-xs" @click="copyContractHint">复制话术</button>
              </div>
              <p v-if="contractForm.filename" class="cs-contract-file">已生成：{{ contractForm.filename }}</p>
              <ContractEsignPanel
                v-if="showEsignPanel && selectedUserId"
                class="cs-esign-panel-wrap"
                :market-user-id="selectedUserId"
                :username="selectedEnterpriseUser?.username || ''"
                :party-a="contractForm.party_a_name || customerPipeline.erp_customer_name"
                :compact="true"
                @updated="(p) => applyPipelineFromDoc(p)"
              />
            </section>

            <section v-if="showDeliveryBlock" class="cs-block cs-block-biz cs-block-delivery">
              <h4 class="cs-block-title">项目交付</h4>
              <p class="cs-block-desc">{{ stageGuideFor(currentStageId).description }}</p>
              <div class="cs-delivery-grid">
                <label class="cs-field">
                  <span>客户期望交付时间</span>
                  <input v-model="deliveryForm.expected_delivery_at" type="date" class="cs-input">
                </label>
                <label class="cs-field">
                  <span>制作进度</span>
                  <span class="cs-delivery-pct">{{ deliveryForm.progress_percent }}%</span>
                </label>
              </div>
              <div class="cs-delivery-progress-track">
                <div class="cs-delivery-progress-fill" :style="{ width: `${deliveryForm.progress_percent}%` }" />
              </div>
              <ul class="cs-milestone-list">
                <li v-for="m in deliveryForm.milestones" :key="m.id" class="cs-milestone-item">
                  <label>
                    <input v-model="m.done" type="checkbox" @change="onMilestoneToggle">
                    <span>{{ m.label }}</span>
                    <span class="muted">（{{ m.weight }}%）</span>
                  </label>
                </li>
              </ul>
              <div class="cs-block-actions">
                <button
                  type="button"
                  class="btn btn-xs btn-accent"
                  :disabled="deliveryForm.saving"
                  @click="saveDeliveryPlan(currentStageId === 'signed')"
                >
                  {{ deliveryForm.saving ? '保存中…' : (currentStageId === 'signed' ? '保存并进入交付中' : '保存进度') }}
                </button>
                <button
                  type="button"
                  class="btn btn-xs"
                  :disabled="deliveryForm.notifying || !wechatSendContactName"
                  @click="notifyDeliveryProgress()"
                >
                  {{ deliveryForm.notifying ? '发送中…' : '同步进度到微信群' }}
                </button>
                <button
                  type="button"
                  class="btn btn-xs btn-accent"
                  :disabled="deliveryForm.sendingSoftware || !wechatSendContactName || !clientDesktopOs"
                  :title="clientDesktopOs ? '' : '请客户在需求表单中选择 Mac 或 Windows'"
                  @click="notifySoftwareDelivery(false)"
                >
                  {{ deliveryForm.sendingSoftware ? '发送中…' : (customerPipeline.software_delivery_sent_at ? '重新发送安装包' : '发送安装包到微信群') }}
                </button>
                <p v-if="clientDesktopOs" class="cs-stage-done-hint muted">
                  交付包：{{ clientDesktopOs === 'mac' ? 'macOS' : 'Windows' }} 电脑端
                  <span v-if="clientNeedMobile"> + Android 手机端</span>
                  <span v-if="customerPipeline.software_delivery_sent_at">
                    · 已于 {{ formatPassivePollTime(customerPipeline.software_delivery_sent_at) }} 推送
                  </span>
                </p>
                <button
                  type="button"
                  class="btn btn-xs btn-accent"
                  :disabled="deliveryForm.checkingPayment"
                  @click="checkPaymentAndInvoice(false)"
                >
                  {{ deliveryForm.checkingPayment ? '检查中…' : '检查到款并出账' }}
                </button>
                <button
                  type="button"
                  class="btn btn-xs"
                  :disabled="deliveryForm.checkingPayment"
                  @click="checkPaymentAndInvoice(true)"
                >
                  强制确认到款
                </button>
                <button
                  v-if="currentStageId === 'delivering'"
                  type="button"
                  class="btn btn-xs"
                  :disabled="signoffLoading"
                  @click="requestDeliverySignoff()"
                >
                  {{ signoffLoading ? '处理中…' : '发起客户签收' }}
                </button>
                <button
                  v-if="customerPipeline.delivery_signoff?.status === 'pending'"
                  type="button"
                  class="btn btn-xs btn-accent"
                  :disabled="signoffLoading"
                  @click="confirmDeliverySignoff()"
                >
                  确认签收并完成交付
                </button>
                <button
                  v-if="currentStageId === 'delivering' && deliveryForm.progress_percent >= 100 && !customerPipeline.delivery_signoff"
                  type="button"
                  class="btn btn-xs"
                  :disabled="stageSaving"
                  @click="savePipelineStage('delivered', { confirmMessage: '确认已全部交付并验收？' })"
                >
                  标记为已交付
                </button>
              </div>
              <p v-if="paymentStatus" class="cs-stage-done-hint">
                到款状态：{{ paymentStatusLabel }}
                <span v-if="paymentOutTradeNo"> · 订单 {{ paymentOutTradeNo }}</span>
                <span v-if="paymentVerification"> · {{ paymentVerificationLabel }}</span>
                <span v-if="invoiceNo"> · 账单 {{ invoiceNo }}</span>
              </p>
            </section>

            <section
              v-if="stageRank(currentStageId) >= stageRank('signed')"
              class="cs-block cs-change-requests"
            >
              <p class="cs-block-title">客户变更工单（外部客服门户）</p>
              <p class="muted cs-block-hint">
                客户在「外部客服」提交的交付期变更/Bug 会出现在此，可同步至微信群并更新状态。
              </p>
              <div v-if="changeRequestsLoading" class="loading-hint">加载工单…</div>
              <ul v-else-if="changeRequests.length" class="cs-change-request-list">
                <li v-for="cr in changeRequests" :key="cr.id" class="cs-change-request-item">
                  <div class="cs-change-request-head">
                    <strong>{{ cr.ticket_no }}</strong>
                    <span class="req-type-badge type-问题">{{ cr.change_type_label }}</span>
                    <span class="req-status" :class="'st-' + cr.status">{{ cr.status_label }}</span>
                  </div>
                  <p class="cs-change-request-title">{{ cr.title }}</p>
                  <p v-if="cr.description" class="muted cs-change-request-desc">{{ cr.description }}</p>
                  <div class="cs-block-actions">
                    <select
                      class="input-xs"
                      :value="cr.status"
                      @change="onChangeRequestStatus(cr, ($event.target as HTMLSelectElement).value)"
                    >
                      <option value="pending">待受理</option>
                      <option value="acknowledged">已确认</option>
                      <option value="in_progress">处理中</option>
                      <option value="resolved">已解决</option>
                      <option value="rejected">已驳回</option>
                    </select>
                    <button
                      type="button"
                      class="btn btn-xs"
                      :disabled="changeRequestNotifyingId === cr.id || !wechatSendContactName"
                      @click="notifyChangeRequestWechat(cr)"
                    >
                      {{ changeRequestNotifyingId === cr.id ? '发送中…' : '同步到微信群' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-xs btn-accent"
                      :disabled="changeRequestOpsDispatchingId === cr.id"
                      @click="dispatchChangeRequestOps(cr)"
                    >
                      {{ changeRequestOpsDispatchingId === cr.id ? '派发中…' : '派发运维任务' }}
                    </button>
                    <span v-if="cr.ops_dispatch_job_id" class="muted cs-ops-job">
                      job: {{ cr.ops_dispatch_job_id }}
                      <router-link :to="{ name: 'xcmax-admin', query: { tab: 'dispatch' } }">管理员</router-link>
                    </span>
                    <span v-else-if="cr.ops_dispatch_error" class="cs-stage-warn-hint">{{ cr.ops_dispatch_error }}</span>
                  </div>
                </li>
              </ul>
              <p v-else class="empty-hint">暂无客户变更工单</p>
            </section>
          </div>
        </article>
      </div>
    </div>

    <div v-if="addCustomerModal.visible" class="modal-overlay" @click.self="addCustomerModal.visible = false">
      <div class="modal-content cs-add-customer-modal">
        <div class="modal-header">
          <h3>添加企业客户</h3>
          <button class="modal-close" type="button" @click="addCustomerModal.visible = false">&times;</button>
        </div>
        <div class="modal-body">
          <p class="muted cs-add-customer-hint">
            内部客服列表显示「已勾选企业用户」的市场账号，以及已有商机 pipeline 档案的用户。勾选企业后刷新即可出现在左侧列表。
          </p>
          <input
            v-model="addCustomerModal.filter"
            type="search"
            class="cs-input"
            placeholder="搜索用户名或邮箱"
            @keydown.enter.prevent
          >
          <div v-if="addCustomerModal.loading" class="loading-hint">加载用户…</div>
          <ul v-else class="cs-add-customer-list">
            <li
              v-for="u in addCustomerPickerRows"
              :key="u.id"
              class="cs-add-customer-row"
              :class="{ 'is-listed': isCustomerListed(u.id) }"
            >
              <div class="cs-add-customer-row__main">
                <strong>{{ u.username }}</strong>
                <span class="muted">#{{ u.id }}</span>
                <span v-if="u.is_enterprise" class="cs-tag cs-tag--ok">企业</span>
                <span v-else-if="u.has_pipeline" class="cs-tag">有 pipeline</span>
              </div>
              <button
                v-if="!u.is_enterprise"
                type="button"
                class="btn btn-xs btn-secondary"
                :disabled="addCustomerModal.savingId === u.id"
                @click="markUserEnterprise(u)"
              >
                {{ addCustomerModal.savingId === u.id ? '保存中…' : '设为企业客户' }}
              </button>
              <span v-else-if="isCustomerListed(u.id)" class="muted">已在列表</span>
              <button
                v-else
                type="button"
                class="btn btn-xs btn-ghost"
                @click="focusListedCustomer(u.id)"
              >
                打开
              </button>
            </li>
          </ul>
          <p v-if="!addCustomerModal.loading && !addCustomerPickerRows.length" class="empty-hint">
            无匹配用户。可在
            <button type="button" class="btn-link" @click="goAdminEntitlements">用户 Mod 管理</button>
            中创建市场账号后再添加。
          </p>
        </div>
      </div>
    </div>

    <div v-if="wechatDrawer.visible" class="modal-overlay" @click.self="wechatDrawer.visible = false">
      <div class="modal-content cs-drawer">
        <div class="modal-header">
          <h3>{{ wechatDrawer.title }}</h3>
          <button class="modal-close" type="button" @click="wechatDrawer.visible = false">&times;</button>
        </div>
        <div class="modal-body cs-drawer-body">
          <div v-if="wechatDrawer.loading" class="loading-hint">加载…</div>
          <div v-else-if="!wechatDrawer.messages.length" class="empty-hint">暂无消息</div>
          <div v-for="(msg, idx) in wechatDrawer.messages" v-else :key="idx" class="cs-chat-msg">
            <div class="cs-chat-role">
              <template v-if="msg.role === 'self'">我</template>
              <template v-else>
                {{ msg.sender_display || msg.sender || '成员' }}
                <span
                  v-if="msg.sender && msg.sender_display && msg.sender !== msg.sender_display"
                  class="cs-chat-sender-id"
                >{{ msg.sender }}</span>
              </template>
            </div>
            <div class="cs-chat-text">{{ formatChatText(msg) }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { get, post, put } from '@/api'
import { getUnifiedLedger, type UnifiedLedgerEntry } from '@/api/financeLedger'
import { wechatApi } from '@/api/wechat'
import { wechatGroupBridgeApi } from '@/api/wechatGroupBridge'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { useWechatGroupBridge } from '@/composables/useWechatGroupBridge'
import { useWechatEnterpriseBinding } from '@/composables/useWechatEnterpriseBinding'
import { useServiceBridge } from '@/composables/useServiceBridge'
import { appAlert, appConfirm } from '@/utils/appDialog'
import ContractEsignPanel from '@/components/contract/ContractEsignPanel.vue'

const router = useRouter()
const route = useRoute()

const DEFAULT_PIPELINE_STAGES = [
  { id: 'idle', label: '未接触' },
  { id: 'connected', label: '已建联' },
  { id: 'intake', label: '需求采集' },
  { id: 'intake_done', label: '已提交' },
  { id: 'quoted', label: '已报价' },
  { id: 'negotiating', label: '议价' },
  { id: 'contract_pending', label: '待签' },
  { id: 'signed', label: '已签' },
  { id: 'delivering', label: '交付中' },
  { id: 'delivered', label: '已交付' },
]

type PhaseCheckKey =
  | 'bind'
  | 'sync'
  | 'messages'
  | 'connected_welcome'
  | 'intake_sent'
  | 'form_done'
  | 'contract_draft'
  | 'crm_record'
  | 'erp_linked'
  | 'delivery_plan'
  | 'delivery_progress'
  | 'payment_received'
  | 'invoice_issued'

type PhaseGuide = {
  id: string
  label: string
  headline: string
  description: string
  actionHint?: string
  groupTip?: string
  comingSoon?: string
  checklist: Array<{ key: PhaseCheckKey; text: string }>
}

const PHASE_GUIDES: Record<string, PhaseGuide> = {
  idle: {
    id: 'idle',
    label: '未接触',
    headline: '绑定微信群，建立服务通道',
    description: '先确认该客户对应哪些群，保存绑定后系统才能同步消息、跟踪进度。',
    checklist: [
      { key: 'bind', text: '勾选负责的微信群并保存' },
      { key: 'sync', text: '保存后自动同步一次群消息' },
    ],
  },
  connected: {
    id: 'connected',
    label: '已建联',
    headline: '发送建联欢迎语，同步群聊跟进',
    description:
      '进入本阶段后，系统会向已绑定的微信群发送建联欢迎语（AI 助理自我介绍）。下一阶段「需求采集」起，将在群内发送官网需求表单链接与填写说明（含审核码指引）。',
    actionHint: '若欢迎语未发出，可点击下方「发送建联欢迎语」重试（需 Mac/PC 微信已登录）。',
    checklist: [
      { key: 'bind', text: '群聊已绑定' },
      { key: 'connected_welcome', text: '已向客户发送建联欢迎语（AI 助理自我介绍）' },
      { key: 'sync', text: '已同步最新消息' },
      { key: 'messages', text: '看过最近对话并跟进' },
    ],
  },
  intake: {
    id: 'intake',
    label: '需求采集',
    headline: '向微信群发送表单链接与填写说明',
    description:
      '从本阶段起，请在已绑定微信群发送官网专属需求表单链接，并说明填写方式与审核码回传。客户提交后可用审核码拉取表单；您也可生成更详细话术后再发。',
    actionHint: '点击下方「发送表单链接到微信群」一键发送（需微信已登录）；未发出前可点「重新发送」。',
    checklist: [
      { key: 'intake_sent', text: '已向客户介绍服务并发送采集话术/表单链接' },
      { key: 'form_done', text: '需求已在官网表单提交并同步' },
    ],
  },
  intake_done: {
    id: 'intake_done',
    label: '已提交',
    headline: '确认需求，准备报价',
    description: '客户已提交或口头确认需求。请在群内核对范围与交付边界，确认后再发正式报价。',
    actionHint: '用下方话术在微信群确认需求；客户回复后点「同步群聊并分析进度」可自动识别进入已报价/议价。',
    groupTip: '报价与议价均在已绑定微信群完成，无需等待自动报价模块。',
    checklist: [
      { key: 'form_done', text: '需求已提交或已确认' },
      { key: 'erp_linked', text: '已关联 ERP 客户主数据' },
      { key: 'messages', text: '群内已核对关键需求点' },
    ],
  },
  quoted: {
    id: 'quoted',
    label: '已报价',
    headline: '跟进报价反馈',
    description: '报价已在群内发出。关注客户回复，若谈价格或折扣请继续在群内沟通并记录让步点。',
    actionHint: '保存为「已报价」后 CRM 会更新报价单状态；还价时请调至「议价」。',
    groupTip: '客户还价时可直接用议价话术回复；达成一致后手动将阶段调至「待签」。',
    checklist: [
      { key: 'crm_record', text: 'CRM 商机与报价单已入库' },
      { key: 'erp_linked', text: '已关联 ERP 客户' },
      { key: 'messages', text: '已跟进报价反馈' },
    ],
  },
  negotiating: {
    id: 'negotiating',
    label: '议价',
    headline: '议价沟通，调整方案或价格',
    description: '正在群内谈价格或交付条件。保持回复及时，关键让步与最终口径留在群记录中。',
    actionHint: '保存为「议价」后 CRM 报价单标记为议价中；谈妥后进入「待签」生成合同。',
    groupTip: '议价以微信群沟通为准，发送前请核对金额与范围后再点发送。',
    checklist: [
      { key: 'crm_record', text: 'CRM 报价单状态为议价中' },
      { key: 'messages', text: '议价要点已在群内对齐' },
    ],
  },
  contract_pending: {
    id: 'contract_pending',
    label: '待签',
    headline: '填写合同并生成 Word',
    description: '乙方信息已预填（成都修茈科技）。填写甲方与金额，生成合同发给客户签署。',
    actionHint: '必填：甲方名称、合同总金额。生成后可下载 Word 并复制发送话术。',
    checklist: [
      { key: 'contract_draft', text: '已生成合同草案' },
      { key: 'messages', text: '已在微信群发送并跟进' },
    ],
  },
  signed: {
    id: 'signed',
    label: '已签',
    headline: '启动交付计划',
    description: '合同已签。请填写客户期望交付时间与制作里程碑，保存后进入「交付中」阶段。',
    actionHint: '填写预计交付日期并保存计划；可一键向微信群同步首次交付说明。',
    checklist: [
      { key: 'contract_draft', text: '合同已生成或已签署' },
      { key: 'delivery_plan', text: '已填写预计交付时间与里程碑' },
    ],
  },
  delivering: {
    id: 'delivering',
    label: '交付中',
    headline: '定制软件制作进行中',
    description: '按里程碑更新制作进度，定期向客户群同步；客户到款后系统自动生成账单。',
    actionHint: '勾选已完成里程碑并保存；进度可发到微信群。检测到款后点「检查到款并出账」。',
    groupTip: '进度以里程碑为准，建议每完成一阶段在群内通报一次。',
    checklist: [
      { key: 'delivery_progress', text: '制作进度已更新并同步客户' },
      { key: 'payment_received', text: '已确认到款' },
      { key: 'invoice_issued', text: '已自动生成账单' },
    ],
  },
  delivered: {
    id: 'delivered',
    label: '已交付',
    headline: '交付完成，售后跟进',
    description: '项目已验收交付。确认到款与账单无误后，持续响应售后咨询。',
    actionHint: '若尚未出账，可再次「检查到款并出账」；验收问题在群内跟进。',
    checklist: [
      { key: 'delivery_progress', text: '全部里程碑已完成' },
      { key: 'invoice_issued', text: '账单已出具' },
      { key: 'messages', text: '验收与售后已跟进' },
    ],
  },
}

const { stats, loadStats } = useServiceBridge()

const {
  feed,
  loading: wechatLoading,
  syncing,
  loadFeed,
  syncGroups,
  formatFeedItem,
} = useWechatGroupBridge()

const expandedClientId = ref<number | null>(null)

const {
  enterpriseUsers,
  selectedUserId,
  selectedUser: selectedEnterpriseUser,
  wechatGroups: wechatGroupsCatalog,
  selectedGroupIdStrings,
  groupFilter,
  filteredGroups: filteredBindGroups,
  loadingUsers: loadingEnterpriseUsers,
  loadingGroups: loadingWechatGroups,
  loadingBindings,
  savingBindings,
  bindingsDirty,
  loadEnterpriseUsers,
  loadWechatGroups,
  selectEnterprise,
  onGroupSelectionChange,
  saveBindings,
} = useWechatEnterpriseBinding()

const pipelineAnalyzing = ref(false)
const stageDraft = ref('idle')
const stageSaving = ref(false)
const autoStageAdvancing = ref(false)
const connectedWelcomeSending = ref(false)
const intakeNoticeSending = ref(false)
const intakeFinalizeLoading = ref(false)
const changeRequests = ref<
  Array<{
    id: string
    ticket_no?: string
    change_type_label?: string
    title?: string
    description?: string
    status?: string
    status_label?: string
    ops_dispatch_job_id?: string
    ops_dispatched_at?: string
    ops_dispatch_error?: string
  }>
>([])
const changeRequestsLoading = ref(false)
const changeRequestNotifyingId = ref('')
const changeRequestOpsDispatchingId = ref('')
const funnelExpanded = ref(true)
const funnelLoading = ref(false)
const funnelError = ref('')
const funnelStages = ref<Array<{ id: string; label: string; count: number }>>([])
const funnelTotalClients = ref(0)
const funnelStageFilter = ref('')
const externalCrmPushLoading = ref(false)
const externalCrmPullLoading = ref(false)
const intakeAutoFinalizeAttempted = ref(0)
const passivePolling = ref(false)
const passiveLoopEnabled = ref(false)
const passiveLoopIntervalSec = ref(60)
const passiveLoopLastAt = ref('')
const passiveLoopSummary = ref('')
const passiveLlmStatus = ref('')
const passiveLoopBusy = ref(false)
let passiveLoopTimer: ReturnType<typeof setInterval> | null = null
const pipelineStages = ref([...DEFAULT_PIPELINE_STAGES])
type IntakeFormFields = {
  name?: string
  email?: string
  phone?: string
  company?: string
  message?: string
  desktop_os?: string
  need_mobile?: boolean
}

const customerPipeline = reactive({
  stage: 'idle',
  username: '',
  last_message_preview: '',
  intake_sent: false,
  intake_form_notice_sent: false,
  connected_welcome_sent: false,
  intake_submitted_at: '',
  landing_contact_id: 0,
  intake_form: null as IntakeFormFields | null,
  erp_customer_id: 0,
  erp_customer_name: '',
  crm_funnel_synced_at: '',
  intake_done_notice_sent: false,
  crm_opportunity_id: 0,
  crm_quote_id: 0,
  crm_db_synced_at: '',
  crm_invoice_id: 0,
  external_crm_deal_id: '',
  external_crm_last_at: '',
  external_crm_last_error: '',
  external_crm_last_pull_at: '',
  external_crm_last_pull_error: '',
  enterprise_auto_provisioned_at: '',
  enterprise_login_username: '',
  enterprise_login_password: '',
  enterprise_credentials_issued_at: '',
  software_delivery_sent_at: '',
  software_delivery_os: '',
  delivery_signoff: null as { id?: number; status?: string } | null,
})

const signoffLoading = ref(false)

const enterpriseCreds = reactive({
  loading: false,
  issuing: false,
  username: '',
  email: '',
  password: '',
  password_recorded: false,
  issued_at: '',
  is_enterprise: false,
  error: '',
})

const deliveryForm = reactive({
  expected_delivery_at: '',
  milestones: [] as Array<{ id: string; label: string; weight: number; done: boolean }>,
  progress_percent: 0,
  saving: false,
  notifying: false,
  sendingSoftware: false,
  checkingPayment: false,
})

const paymentStatus = ref('')
const paymentOutTradeNo = ref('')
const paymentVerification = ref('')
const invoiceNo = ref('')

const crmQuoteSummary = ref('')
const crmQuoteStatus = ref('')
const crmSyncLoading = ref(false)
const crmRepairLoading = ref(false)

type ClientSummary = {
  stage: string
  last_message_preview: string
  intake_sent: boolean
  /** 表单联网检索 / ERP 关联后的完整公司名（非登录账号） */
  display_name: string
}
const clientSummaries = reactive<Record<number, ClientSummary>>({})

const demandIntake = reactive({
  brief: '',
  clientName: '',
  formUrl: 'https://xiu-ci.com/contact.html',
  signedFormUrl: '',
  messageText: '',
  loading: false,
  sendingWechat: false,
})

const contractForm = reactive({
  party_a_name: '',
  party_a_credit_code: '',
  total_amount_number: '',
  expected_out_trade_no: '',
  sign_date: '',
  main_function_list: '',
  loading: false,
  savingFields: false,
  filename: '',
  downloadUrl: '',
  wechatHint: '',
})

const wechatSend = reactive({
  message: '',
  loading: false,
  error: '',
})

const CS_BRIDGE = '/api/mod/xcagi-customer-service-bridge'

const financeLedgerItems = ref<UnifiedLedgerEntry[]>([])
const financeLedgerLoading = ref(false)

function financeTrackLabel(track: string) {
  if (track === 'contract') return '合同'
  if (track === 'token') return 'Token'
  return track || '—'
}

function formatLedgerYuan(cents: number) {
  return (Number(cents || 0) / 100).toFixed(2)
}

function formatLedgerTime(raw?: string) {
  if (!raw) return '—'
  const d = new Date(raw)
  return Number.isNaN(d.getTime()) ? raw : d.toLocaleString()
}

async function loadFinanceLedger() {
  if (!selectedUserId.value) {
    financeLedgerItems.value = []
    return
  }
  financeLedgerLoading.value = true
  try {
    const res = await getUnifiedLedger({
      market_user_id: selectedUserId.value,
      limit: 50,
    })
    financeLedgerItems.value = res.items || []
  } catch {
    financeLedgerItems.value = []
  } finally {
    financeLedgerLoading.value = false
  }
}

function stageLabel(stageId: string) {
  return pipelineStages.value.find((s) => s.id === stageId)?.label
    || DEFAULT_PIPELINE_STAGES.find((s) => s.id === stageId)?.label
    || stageId
}

function stageGuideFor(stageId: string) {
  return PHASE_GUIDES[stageId] || PHASE_GUIDES.idle
}

function checklistItemDoneFactual(key: PhaseCheckKey): boolean {
  switch (key) {
    case 'bind':
      return hasBinding.value
    case 'sync':
      return formattedFeed.value.length > 0
    case 'messages':
      return formattedFeed.value.length > 0
    case 'connected_welcome':
      return Boolean(customerPipeline.connected_welcome_sent)
    case 'intake_sent':
      return (
        customerPipeline.intake_form_notice_sent
        || customerPipeline.intake_sent
        || Boolean(demandIntake.messageText)
      )
    case 'form_done':
      return Boolean(customerPipeline.intake_submitted_at)
        || stageRank(currentStageId.value) >= stageRank('intake_done')
    case 'erp_linked':
      return Boolean(customerPipeline.erp_customer_id || customerPipeline.erp_customer_name)
    case 'crm_record':
      if (currentStageId.value === 'negotiating') {
        return Boolean(customerPipeline.crm_opportunity_id && customerPipeline.crm_quote_id)
          && (crmQuoteStatus.value === 'negotiating' || crmQuoteStatus.value === 'sent')
      }
      if (stageRank(currentStageId.value) >= stageRank('quoted')) {
        return Boolean(customerPipeline.crm_opportunity_id && customerPipeline.crm_quote_id)
      }
      return Boolean(customerPipeline.crm_opportunity_id)
    case 'delivery_plan':
      return Boolean(deliveryForm.expected_delivery_at) && deliveryForm.milestones.length > 0
    case 'delivery_progress':
      return deliveryForm.progress_percent >= 100
        || stageRank(currentStageId.value) >= stageRank('delivered')
    case 'payment_received':
      return ['detected', 'confirmed', 'paid'].includes(paymentStatus.value)
    case 'invoice_issued':
      return Boolean(customerPipeline.crm_invoice_id) || Boolean(invoiceNo.value)
    case 'contract_draft':
      return Boolean(contractForm.filename)
    default:
      return false
  }
}

function checklistItemDone(key: PhaseCheckKey): boolean {
  const viewing = viewingStageId.value
  const current = currentStageId.value

  // 调整阶段（预选）：目标阶段清单一律视为待办
  if (stageDraftDirty.value && stageDraft.value !== current) {
    return false
  }

  // 仍停留在会自动推进的阶段：清单项显示未完成（完成则应已进入下一阶段）
  if (!stageDraftDirty.value && viewing === current && AUTO_ADVANCE_CHECKLIST_STAGES.has(current)) {
    return false
  }

  // 已越过该阶段：该阶段清单视为已完成
  if (stageRank(current) > stageRank(viewing)) {
    return true
  }

  return checklistItemDoneFactual(key)
}

function getClientSummary(userId: number): ClientSummary {
  return (
    clientSummaries[userId] || {
      stage: 'idle',
      last_message_preview: '',
      intake_sent: false,
      display_name: '',
    }
  )
}

function displayNameFromPipeline(
  p: Record<string, unknown>,
  loginUsername: string,
): string {
  const form = p.intake_form as IntakeFormFields | null | undefined
  const company = String(form?.company || '').trim()
  if (company) return company
  const erp = String(p.erp_customer_name || '').trim()
  if (erp) return erp
  const login = String(loginUsername || '').trim()
  const pipeUser = String(p.username || '').trim()
  if (pipeUser && (!login || pipeUser.toLowerCase() !== login.toLowerCase())) return pipeUser
  return login
}

function matchedCompanyName(): string {
  const form = customerPipeline.intake_form
  return (
    String(form?.company || '').trim()
    || String(customerPipeline.erp_customer_name || '').trim()
  )
}

function intakePrefillGreetingName(): string {
  const manual = demandIntake.clientName.trim()
  const login = (selectedEnterpriseUser.value?.username || customerPipeline.username || '').trim()
  if (manual && (!login || manual.toLowerCase() !== login.toLowerCase())) {
    return manual
  }
  const company = matchedCompanyName()
  if (company) return company
  const contact = String(customerPipeline.intake_form?.name || '').trim()
  if (contact && (!login || contact.toLowerCase() !== login.toLowerCase())) return contact
  return login
}

function syncDemandIntakeClientNameFromPipeline() {
  const name = intakePrefillGreetingName()
  const login = (selectedEnterpriseUser.value?.username || '').trim()
  if (name && (!login || name.toLowerCase() !== login.toLowerCase())) {
    demandIntake.clientName = name
  }
}

function displayClientName(u: { id: number; username: string }) {
  if (expandedClientId.value === u.id) {
    const live = matchedCompanyName()
    if (live) return live
    const pipeName = customerPipeline.username.trim()
    if (pipeName && pipeName.toLowerCase() !== u.username.toLowerCase()) return pipeName
  }
  const cached = getClientSummary(u.id).display_name
  if (cached) return cached
  return u.username
}

function cardNameTitle(u: { id: number; username: string }) {
  const shown = displayClientName(u)
  const login = String(u.username || '').trim()
  if (shown && login && shown.toLowerCase() !== login.toLowerCase()) {
    return `登录账号：${login}`
  }
  return ''
}

function progressPercent(userId: number) {
  const stages = pipelineStages.value
  const stage = expandedClientId.value === userId ? customerPipeline.stage : getClientSummary(userId).stage
  const idx = stages.findIndex((s) => s.id === stage)
  if (idx <= 0) return 4
  return Math.round(((idx + 1) / stages.length) * 100)
}

function stageRank(stageId: string) {
  return pipelineStages.value.findIndex((s) => s.id === stageId)
}

function formatChatText(msg: Record<string, unknown>) {
  const text = String(msg.text || msg.content || '').trim()
  if (!text) return ''
  const lower = text.toLowerCase()
  if (
    text.startsWith('<?xml') ||
    text.startsWith('<msg') ||
    lower.includes('<appmsg') ||
    lower.includes('<sysmsg') ||
    (text.includes('拍了拍') && text.includes('<template>'))
  ) {
    const pat = text.match(/拍了拍[^<]+/)
    if (pat) return pat[0]
    return '[系统/卡片消息]'
  }
  return text
}

const wechatDrawer = reactive({
  visible: false,
  loading: false,
  title: '群聊记录',
  contactId: 0,
  messages: [] as Array<Record<string, unknown>>,
})

const formattedFeed = computed(() =>
  feed.value.map((item) => formatFeedItem(item)).filter((r) => r.contactId > 0),
)
const latestFeedSubtitle = computed(() => formattedFeed.value[0]?.subtitle || '')

const currentStageId = computed(() => customerPipeline.stage || 'idle')

const stageDraftDirty = computed(() => stageDraft.value !== currentStageId.value)

/** 阶段说明与清单：下拉预选时展示目标阶段，否则为当前阶段 */
const viewingStageId = computed(() =>
  stageDraftDirty.value ? stageDraft.value : currentStageId.value,
)

/** 清单全满足会自动进入下一阶段（与后端 auto_advance_pipeline 一致） */
const AUTO_ADVANCE_CHECKLIST_STAGES = new Set(['idle', 'connected', 'intake'])

const canSavePipelineStage = computed(
  () => Boolean(selectedUserId.value) && stageDraftDirty.value && !stageSaving.value,
)

const saveStageButtonTitle = computed(() => {
  if (!selectedUserId.value) return '请先展开客户卡片'
  if (stageSaving.value) return '正在保存'
  if (!stageDraftDirty.value) return '请先在进度条或下拉框选择不同于当前阶段的选项'
  return `保存为「${stageLabel(stageDraft.value)}」`
})

const intakeQuickFormUrl = ref('')
const intakeLinkLoading = ref(false)
const intakeAuditCode = ref('')
const auditCodeFetching = ref(false)
const auditCodeRedeeming = ref(false)
const auditCodeError = ref('')
const intakeAuditPreview = ref<Record<string, unknown> | null>(null)
const intakeAuditPreviewCode = ref('')
const intakeAuditPreviewAt = ref('')

const showIntakeStageShortcuts = computed(
  () => currentStageId.value === 'intake' || currentStageId.value === 'intake_done',
)

const showQuoteNegotiateActions = computed(() => {
  const id = currentStageId.value
  return id === 'intake_done' || id === 'quoted' || id === 'negotiating'
})

const showCrmLinkagePanel = computed(
  () => stageRank(currentStageId.value) >= stageRank('intake_done'),
)

const showCrmFinalizeActions = computed(() => {
  const id = currentStageId.value
  if (!['intake_done', 'quoted', 'negotiating'].includes(id)) return false
  return (
    !customerPipeline.crm_opportunity_id
    || !customerPipeline.crm_quote_id
    || !(customerPipeline.erp_customer_id || customerPipeline.erp_customer_name)
  )
})

const showIntakeFunnelWarn = computed(
  () =>
    Boolean(customerPipeline.intake_submitted_at)
    && !customerPipeline.crm_funnel_synced_at
    && stageRank(currentStageId.value) >= stageRank('intake_done'),
)

const externalCrmStatusLabel = computed(() => {
  const raw = (customerPipeline as { external_crm_last_result?: Record<string, unknown> })
    .external_crm_last_result
  if (!raw || typeof raw !== 'object') return ''
  if (raw.skipped) return String(raw.reason || '已跳过')
  if (raw.success) return String(raw.provider || '成功')
  return String(raw.error || raw.reason || '失败')
})

const externalCrmPullStatusLabel = computed(() => {
  const raw = (customerPipeline as { external_crm_last_pull_result?: Record<string, unknown> })
    .external_crm_last_pull_result
  if (!raw || typeof raw !== 'object') return ''
  if (raw.skipped) return String(raw.reason || '已跳过')
  if (raw.success) {
    if (raw.stage_changed) {
      return `已回写为「${stageLabel(String(raw.pipeline_stage || ''))}」`
    }
    return '阶段无变化'
  }
  return String(raw.error || raw.reason || '失败')
})

const filteredEnterpriseUsers = computed(() => {
  const filter = funnelStageFilter.value
  if (!filter) return enterpriseUsers.value
  return enterpriseUsers.value.filter((u) => getClientSummary(u.id).stage === filter)
})

const showEsignPanel = computed(
  () =>
    stageRank(currentStageId.value) >= stageRank('contract_pending')
    && stageRank(currentStageId.value) <= stageRank('signed'),
)

const groupScriptActionLabel = computed(() => {
  if (currentStageId.value === 'intake_done') return '需求确认'
  if (currentStageId.value === 'negotiating') return '议价'
  return '报价'
})

const currentStageGuide = computed(() => PHASE_GUIDES[viewingStageId.value] || PHASE_GUIDES.idle)

const nextPipelineStage = computed(() => {
  const stages = pipelineStages.value
  const idx = stageRank(currentStageId.value)
  if (idx < 0 || idx >= stages.length - 1) return null
  return stages[idx + 1]
})

const currentStageChecklistComplete = computed(() => {
  const items = currentStageGuide.value.checklist
  if (!items.length) return true
  return items.every((item) => checklistItemDoneFactual(item.key))
})

const intakeSubmittedAwaitingAdvance = computed(
  () =>
    currentStageId.value === 'intake'
    && Boolean(customerPipeline.intake_submitted_at)
    && checklistItemDoneFactual('form_done'),
)

const hasBinding = computed(() => {
  if (bindingsDirty.value) return selectedGroupIdStrings.value.length > 0
  return (selectedEnterpriseUser.value?.bindingCount || 0) > 0 || selectedGroupIdStrings.value.length > 0
})

const showIntakeBlock = computed(() => hasBinding.value || stageRank(currentStageId.value) >= stageRank('connected'))

const showWechatSendBlock = computed(() => hasBinding.value && stageRank(currentStageId.value) >= stageRank('connected'))

const wechatSendContactName = computed(() => {
  const g = filteredBindGroups.value.find((x) => selectedGroupIdStrings.value.includes(String(x.id)))
  const fromBinding = g?.contact_name || g?.remark || ''
  if (fromBinding) return fromBinding
  const fromFeed = formattedFeed.value[0]?.name
  if (fromFeed) return fromFeed
  return ''
})

const showContractBlock = computed(() => {
  const r = stageRank(currentStageId.value)
  return r >= stageRank('contract_pending')
})

const showDeliveryBlock = computed(() => stageRank(currentStageId.value) >= stageRank('signed'))

const paymentStatusLabel = computed(() => {
  const s = paymentStatus.value
  if (s === 'paid') return '已到款（已出账）'
  if (s === 'confirmed') return '已确认到款'
  if (s === 'detected') return '检测到款话术'
  return '待付款'
})

const paymentVerificationLabel = computed(() => {
  const v = paymentVerification.value
  if (v === 'gateway') return '市场订单已核实'
  if (v === 'chat_heuristic') return '群聊话术（未核实订单库）'
  if (v === 'manual') return '人工强制确认'
  return ''
})

function defaultMilestones() {
  return [
    { id: 'scope', label: '需求与范围确认', weight: 10, done: false },
    { id: 'design', label: '方案与原型设计', weight: 15, done: false },
    { id: 'dev', label: '定制开发实现', weight: 40, done: false },
    { id: 'qa', label: '联调与测试', weight: 20, done: false },
    { id: 'accept', label: '验收与交付上线', weight: 15, done: false },
  ]
}

function recomputeDeliveryProgress() {
  const ms = deliveryForm.milestones
  let total = 0
  let done = 0
  for (const m of ms) {
    total += Number(m.weight) || 0
    if (m.done) done += Number(m.weight) || 0
  }
  deliveryForm.progress_percent = total > 0 ? Math.min(100, Math.round((done * 100) / total)) : 0
}

function onMilestoneToggle() {
  recomputeDeliveryProgress()
}

function applyDeliveryFromDoc(p: Record<string, unknown>) {
  const d = p.delivery
  if (d && typeof d === 'object') {
    const block = d as Record<string, unknown>
    deliveryForm.expected_delivery_at = String(block.expected_delivery_at || '').slice(0, 10)
    const ms = block.milestones
    if (Array.isArray(ms) && ms.length) {
      deliveryForm.milestones = ms.map((m) => ({
        id: String((m as { id?: string }).id || ''),
        label: String((m as { label?: string }).label || ''),
        weight: Number((m as { weight?: number }).weight) || 0,
        done: Boolean((m as { done?: boolean }).done),
      }))
    } else if (!deliveryForm.milestones.length) {
      deliveryForm.milestones = defaultMilestones()
    }
    deliveryForm.progress_percent = Number(block.progress_percent) || 0
  } else if (!deliveryForm.milestones.length) {
    deliveryForm.milestones = defaultMilestones()
  }
  const pay = p.payment
  if (pay && typeof pay === 'object') {
    const pb = pay as Record<string, unknown>
    paymentStatus.value = String(pb.status || '')
    paymentOutTradeNo.value = String(pb.out_trade_no || pb.expected_out_trade_no || '')
    paymentVerification.value = String(pb.verification || '')
  }
  const inv = p.invoice
  if (inv && typeof inv === 'object') {
    invoiceNo.value = String((inv as { invoice_no?: string }).invoice_no || '')
    customerPipeline.crm_invoice_id = Number((inv as { id?: number }).id || p.crm_invoice_id || 0)
  } else {
    customerPipeline.crm_invoice_id = Number(p.crm_invoice_id || 0)
  }
}

async function saveDeliveryPlan(startDelivering: boolean) {
  if (!selectedUserId.value) return
  deliveryForm.saving = true
  recomputeDeliveryProgress()
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/delivery/plan`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      expected_delivery_at: deliveryForm.expected_delivery_at,
      milestones: deliveryForm.milestones,
      start_delivery: startDelivering,
      stage: startDelivering ? 'delivering' : undefined,
    })
    const payload = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown> } }
    if (!payload?.success) {
      await appAlert(payload?.error || '保存失败')
      return
    }
    const p = payload.data?.pipeline
    if (p) {
      applyPipelineFromDoc(p, { resetDraft: true })
      applyDeliveryFromDoc(p)
    }
    await appAlert(startDelivering ? '交付计划已保存，阶段已更新为「交付中」' : '交付进度已保存')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '保存交付计划失败')
  } finally {
    deliveryForm.saving = false
  }
}

async function notifyDeliveryProgress() {
  if (!selectedUserId.value) return
  deliveryForm.notifying = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/delivery/notify-progress`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const payload = res as { success?: boolean; error?: string }
    if (!payload?.success) {
      await appAlert(payload?.error || '发送失败')
      return
    }
    await appAlert('进度说明已发送到微信群')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '发送失败')
  } finally {
    deliveryForm.notifying = false
  }
}

const clientDesktopOs = computed(() => {
  const form = customerPipeline.intake_form
  const direct = String(form?.desktop_os || '').trim()
  if (direct === 'mac' || direct === 'win') return direct
  const msg = String(form?.message || '')
  const m = msg.match(/使用系统[：:]\s*(mac\s*os|macos|mac|windows|win)/i)
  if (!m) return ''
  const raw = m[1].toLowerCase()
  if (raw.startsWith('mac')) return 'mac'
  if (raw.startsWith('win')) return 'win'
  return ''
})

const clientNeedMobile = computed(() => {
  const form = customerPipeline.intake_form
  if (form && typeof form.need_mobile === 'boolean') return form.need_mobile
  const msg = String(form?.message || '')
  const m = msg.match(/手机端[：:]\s*(需要|不需要)/)
  if (m) return m[1] === '需要'
  return true
})

async function notifySoftwareDelivery(force: boolean) {
  if (!selectedUserId.value) return
  if (!clientDesktopOs.value) {
    await appAlert('客户尚未在需求表单中选择 Mac / Windows，请补发表单或手动录入后再发送安装包')
    return
  }
  let forceResend = force
  if (customerPipeline.software_delivery_sent_at && !forceResend) {
    const ok = window.confirm('安装包链接已发送过，确定重新发送到微信群？')
    if (!ok) return
    forceResend = true
  }
  deliveryForm.sendingSoftware = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/delivery/notify-software`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      force: forceResend,
    })
    const payload = res as {
      success?: boolean
      error?: string
      data?: { pipeline?: Record<string, unknown>; download_url?: string }
    }
    if (!payload?.success) {
      await appAlert(payload?.error || '发送失败')
      return
    }
    const p = payload.data?.pipeline
    if (p) applyPipelineFromDoc(p)
    await appAlert('安装包下载链接已发送到微信群')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '发送失败')
  } finally {
    deliveryForm.sendingSoftware = false
  }
}

async function checkPaymentAndInvoice(force: boolean) {
  if (!selectedUserId.value) return
  if (contractForm.expected_out_trade_no.trim()) {
    await saveContractFields({ silent: true })
  }
  deliveryForm.checkingPayment = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/delivery/check-payment`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      force_confirm: force,
    })
    const payload = res as {
      success?: boolean
      data?: {
        pipeline?: Record<string, unknown>
        payment_detected?: boolean
        invoice_created?: boolean
        invoice?: { invoice_no?: string }
        market_payment?: { ok?: boolean; source?: string; error?: string }
        error?: string
      }
    }
    const d = payload.data
    if (d?.pipeline) {
      applyPipelineFromDoc(d.pipeline)
      applyDeliveryFromDoc(d.pipeline)
    }
    const mp = d?.market_payment
    const mpHint = mp?.success
      ? (mp.source ? `（订单库：${mp.source}）` : '')
      : (mp?.error ? `（市场查询：${mp.error}）` : '')
    if (d?.invoice_created && d.invoice?.invoice_no) {
      await appAlert(`已生成账单：${d.invoice.invoice_no}${mpHint}`)
    } else if (d?.payment_detected) {
      await appAlert(`到款已确认，账单处理完成${mpHint}`)
    } else {
      await appAlert(
        d?.error
          || `未核实到款${mpHint}。请填写「关联市场订单号」并保存合同字段，或让客户在修茈市场完成支付后重试；线下转账可点「强制确认到款」。`,
      )
    }
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '检查到款失败')
  } finally {
    deliveryForm.checkingPayment = false
  }
}

const contractSamplePdfUrl = `${CS_BRIDGE}/user-cs/contract/sample-pdf`

function stepperItemClass(stageId: string, _idx: number) {
  const cur = stageRank(currentStageId.value)
  const si = stageRank(stageId)
  if (stageId === currentStageId.value) return 'is-current'
  if (si >= 0 && si < cur) return 'is-done'
  return ''
}

function syncSummaryFromPipeline(userId: number, loginUsername?: string) {
  const login = String(
    loginUsername || selectedEnterpriseUser.value?.username || '',
  ).trim()
  clientSummaries[userId] = {
    stage: customerPipeline.stage,
    last_message_preview: customerPipeline.last_message_preview,
    intake_sent: customerPipeline.intake_sent,
    display_name: displayNameFromPipeline(
      {
        intake_form: customerPipeline.intake_form,
        erp_customer_name: customerPipeline.erp_customer_name,
        username: customerPipeline.username,
      },
      login,
    ),
  }
}

async function loadClientSummary(userId: number, username?: string) {
  const login = String(username || '').trim()
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/pipeline`, { market_user_id: userId, username: login })
    const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline || {}
    clientSummaries[userId] = {
      stage: String(p.stage || 'idle'),
      last_message_preview: String(p.last_message_preview || ''),
      intake_sent: Boolean(p.intake_sent),
      display_name: displayNameFromPipeline(p, login),
    }
  } catch {
    clientSummaries[userId] = {
      stage: 'idle',
      last_message_preview: '',
      intake_sent: false,
      display_name: '',
    }
  }
}

async function loadAllClientSummaries() {
  await Promise.all(enterpriseUsers.value.map((u) => loadClientSummary(u.id, u.username)))
}

function formatAuditCodeFromLandingId(landingId: unknown) {
  const n = Number(landingId)
  if (!Number.isFinite(n) || n <= 0) return ''
  return `XC-${String(Math.floor(n)).padStart(6, '0')}`
}

function parseIntakeMessageSections(message: string): Array<{ label: string; value: string }> {
  const text = (message || '').trim()
  if (!text.includes('■')) return []
  const rows: Array<{ label: string; value: string }> = []
  const chunks = text.split(/\n(?=■\s*)/)
  for (const chunk of chunks) {
    const block = chunk.trim()
    if (!block.startsWith('■')) continue
    const lines = block.split('\n')
    const title = lines[0].replace(/^■\s*/, '').trim()
    const body = lines.slice(1).join('\n').trim()
    if (title) rows.push({ label: title, value: body || '—' })
  }
  return rows
}

function intakeFormPreviewRows(
  form: Record<string, unknown> | null | undefined,
  opts: { auditCode?: string; submittedAt?: string } = {},
) {
  if (!form) return null
  const rows: Array<{ label: string; value: string }> = []
  const code = (opts.auditCode || '').trim() || formatAuditCodeFromLandingId(form.landing_contact_id)
  if (code) rows.push({ label: '审核码', value: code })
  if (opts.submittedAt) rows.push({ label: '提交时间', value: formatPassivePollTime(opts.submittedAt) })
  const name = String(form.name || '').trim()
  const company = String(form.company || '').trim()
  const email = String(form.email || '').trim()
  const phone = String(form.phone || '').trim()
  const message = String(form.message || '').trim()
  if (name) rows.push({ label: '称呼', value: name })
  if (company) rows.push({ label: '公司', value: company })
  if (email) rows.push({ label: '邮箱', value: email })
  if (phone) rows.push({ label: '电话', value: phone })
  const os = String(form.desktop_os || '').trim()
  if (os === 'mac' || os === 'win') {
    rows.push({ label: '电脑系统', value: os === 'mac' ? 'macOS' : 'Windows' })
  }
  if (form.need_mobile === false) {
    rows.push({ label: '手机端', value: '不需要' })
  } else if (form.need_mobile === true || form.need_mobile === undefined) {
    const msgMobile = message.match(/手机端[：:]\s*(需要|不需要)/)
    if (msgMobile && msgMobile[1] === '不需要') {
      rows.push({ label: '手机端', value: '不需要' })
    } else {
      rows.push({ label: '手机端', value: '需要 Android' })
    }
  }
  const sections = parseIntakeMessageSections(message)
  if (sections.length) {
    rows.push(...sections)
  } else if (message) {
    rows.push({ label: '需求说明', value: message })
  }
  return rows.length ? rows : null
}

const intakeSubmissionSummary = computed(() => {
  if (!customerPipeline.intake_form || !customerPipeline.intake_submitted_at) return null
  return intakeFormPreviewRows(customerPipeline.intake_form as Record<string, unknown>, {
    auditCode: formatAuditCodeFromLandingId(customerPipeline.landing_contact_id),
    submittedAt: customerPipeline.intake_submitted_at,
  })
})

const intakeAuditPreviewRows = computed(() => {
  if (!intakeAuditPreview.value) return null
  const sub = intakeAuditPreview.value
  const form = {
    name: sub.name,
    company: sub.company,
    email: sub.email,
    phone: sub.phone,
    message: sub.message,
    landing_contact_id: sub.landing_contact_id,
  }
  return intakeFormPreviewRows(form, {
    auditCode: intakeAuditPreviewCode.value || String(sub.audit_code || ''),
    submittedAt: intakeAuditPreviewAt.value || String(sub.submitted_at || sub.created_at || ''),
  })
})

function applyPipelineFromDoc(p: Record<string, unknown>, opts: { resetDraft?: boolean } = {}) {
  const prevStage = customerPipeline.stage
  const newStage = String(p.stage || 'idle')
  customerPipeline.stage = newStage
  const pendingDraft = stageDraft.value !== prevStage && stageDraft.value !== newStage
  if (opts.resetDraft || !pendingDraft || stageDraft.value === newStage) {
    stageDraft.value = newStage
  }
  customerPipeline.last_message_preview = String(p.last_message_preview || '')
  customerPipeline.intake_sent = Boolean(p.intake_sent)
  customerPipeline.intake_form_notice_sent = Boolean(p.intake_form_notice_sent)
  customerPipeline.connected_welcome_sent = Boolean(p.connected_welcome_sent)
  customerPipeline.intake_submitted_at = String(p.intake_submitted_at || '')
  customerPipeline.landing_contact_id = Number(p.landing_contact_id || 0)
  const rawForm = p.intake_form
  customerPipeline.intake_form = rawForm && typeof rawForm === 'object'
    ? { ...(rawForm as IntakeFormFields) }
    : null
  customerPipeline.erp_customer_id = Number(p.erp_customer_id || 0)
  customerPipeline.erp_customer_name = String(p.erp_customer_name || '')
  customerPipeline.crm_funnel_synced_at = String(p.crm_funnel_synced_at || '')
  customerPipeline.intake_done_notice_sent = Boolean(p.intake_done_notice_sent)
  customerPipeline.crm_opportunity_id = Number(p.crm_opportunity_id || 0)
  customerPipeline.crm_quote_id = Number(p.crm_quote_id || 0)
  customerPipeline.crm_db_synced_at = String(p.crm_db_synced_at || '')
  customerPipeline.external_crm_deal_id = String(p.external_crm_deal_id || '')
  customerPipeline.external_crm_last_at = String(p.external_crm_last_at || '')
  customerPipeline.external_crm_last_error = String(p.external_crm_last_error || '')
  customerPipeline.external_crm_last_pull_at = String(p.external_crm_last_pull_at || '')
  customerPipeline.external_crm_last_pull_error = String(p.external_crm_last_pull_error || '')
  customerPipeline.username = String(p.username || customerPipeline.username || '')
  customerPipeline.enterprise_auto_provisioned_at = String(p.enterprise_auto_provisioned_at || '')
  customerPipeline.enterprise_login_username = String(
    p.enterprise_login_username || p.username || customerPipeline.enterprise_login_username || '',
  )
  customerPipeline.enterprise_login_password = String(
    p.enterprise_login_password || customerPipeline.enterprise_login_password || '',
  )
  customerPipeline.enterprise_credentials_issued_at = String(
    p.enterprise_credentials_issued_at || customerPipeline.enterprise_credentials_issued_at || '',
  )
  syncEnterpriseCredsFromPipeline()
  syncDemandIntakeClientNameFromPipeline()
  customerPipeline.software_delivery_sent_at = String(p.software_delivery_sent_at || '')
  customerPipeline.software_delivery_os = String(p.software_delivery_os || '')
  ;(customerPipeline as { external_crm_last_result?: unknown }).external_crm_last_result =
    p.external_crm_last_result
  ;(customerPipeline as { external_crm_last_pull_result?: unknown }).external_crm_last_pull_result =
    p.external_crm_last_pull_result
  const ds = p.delivery_signoff
  customerPipeline.delivery_signoff =
    ds && typeof ds === 'object' ? { ...(ds as { id?: number; status?: string }) } : null
  applyDeliveryFromDoc(p)
  const qd = p.quote_draft
  if (qd && typeof qd === 'object') {
    crmQuoteStatus.value = String((qd as { status?: string }).status || '')
    crmQuoteSummary.value = String((qd as { summary?: string }).summary || '')
  }
  const ps = p.passive_state
  if (ps && typeof ps === 'object') {
    passiveLoopEnabled.value = Boolean((ps as { poll_enabled?: boolean }).poll_enabled)
    const sec = Number((ps as { poll_interval_sec?: number }).poll_interval_sec)
    if (sec >= 10) passiveLoopIntervalSec.value = sec
    passiveLoopLastAt.value = formatPassivePollTime((ps as { last_poll_at?: string }).last_poll_at)
    passiveLoopSummary.value = String((ps as { last_poll_message?: string }).last_poll_message || '')
  } else {
    passiveLoopEnabled.value = false
    passiveLoopSummary.value = ''
  }
  if (passiveLoopEnabled.value && selectedUserId.value) {
    startPassiveLoopTimer()
  } else {
    stopPassiveLoopTimer()
  }
}

function applyCrmBundle(crm: { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> } | null | undefined) {
  const opp = crm?.opportunity
  const quote = crm?.quote
  if (opp && typeof opp === 'object') {
    customerPipeline.crm_opportunity_id = Number(opp.id || 0)
    if (!customerPipeline.landing_contact_id && opp.landing_contact_id) {
      customerPipeline.landing_contact_id = Number(opp.landing_contact_id)
    }
    if (!customerPipeline.erp_customer_name && opp.company) {
      customerPipeline.erp_customer_name = String(opp.company)
    }
  }
  if (quote && typeof quote === 'object') {
    customerPipeline.crm_quote_id = Number(quote.id || 0)
    crmQuoteStatus.value = String(quote.status || '')
    crmQuoteSummary.value = String(quote.summary || '')
  }
  const inv = crm?.invoice
  if (inv && typeof inv === 'object') {
    invoiceNo.value = String(inv.invoice_no || '')
    customerPipeline.crm_invoice_id = Number(inv.id || 0)
  }
  const del = crm?.delivery
  if (del && typeof del === 'object' && stageRank(currentStageId.value) >= stageRank('signed')) {
    let milestones: unknown[] = []
    try {
      milestones = JSON.parse(String(del.milestones_json || '[]'))
    } catch {
      milestones = []
    }
    applyDeliveryFromDoc({
      delivery: {
        expected_delivery_at: del.expected_delivery_at,
        milestones,
        progress_percent: del.progress_percent,
      },
    })
  }
}

async function requestDeliverySignoff() {
  if (!selectedUserId.value) return
  signoffLoading.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/delivery/signoff/request`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
    if (p) applyPipelineFromDoc(p, { resetDraft: true })
    await appAlert('已发起签收请求')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '发起签收失败')
  } finally {
    signoffLoading.value = false
  }
}

async function confirmDeliverySignoff() {
  if (!selectedUserId.value) return
  const sid = Number(customerPipeline.delivery_signoff?.id || 0)
  if (!sid) return
  signoffLoading.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/delivery/signoff/confirm`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      signoff_id: sid,
    })
    const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
    if (p) applyPipelineFromDoc(p, { resetDraft: true })
    await appAlert('签收已确认，阶段已更新为「已交付」')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '确认签收失败')
  } finally {
    signoffLoading.value = false
  }
}

async function syncCrmRecord() {
  if (!selectedUserId.value) return
  crmSyncLoading.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/crm/sync`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const data = (res as { data?: { pipeline?: Record<string, unknown>; crm?: Record<string, unknown> } })?.data
    if (data?.pipeline) applyPipelineFromDoc(data.pipeline)
    applyCrmBundle(data?.crm as { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> })
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : 'CRM 同步失败')
  } finally {
    crmSyncLoading.value = false
  }
}

async function repairCrmRecord() {
  if (!selectedUserId.value) return
  crmRepairLoading.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/pipeline/repair-crm`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const body = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown>; crm?: Record<string, unknown> } }
    if (body.success === false) {
      throw new Error(body.error || 'CRM/ERP 修复失败')
    }
    const data = body.data
    if (data?.pipeline) applyPipelineFromDoc(data.pipeline, { resetDraft: true })
    applyCrmBundle(data?.crm as { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> })
    await appAlert('CRM/ERP 已修复并写回 pipeline')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : 'CRM/ERP 修复失败')
  } finally {
    crmRepairLoading.value = false
  }
}

async function fetchPipelineFromServer(opts: { autoAdvance?: boolean } = {}): Promise<{
  pipeline: Record<string, unknown>
  stages: typeof DEFAULT_PIPELINE_STAGES
  advanced: boolean
  crm?: Record<string, unknown>
} | null> {
  if (!selectedUserId.value) return null
  const res = await get(`${CS_BRIDGE}/user-cs/pipeline`, {
    market_user_id: selectedUserId.value,
    username: selectedEnterpriseUser.value?.username || '',
    auto_advance: Boolean(opts.autoAdvance),
  })
  const data = (res as {
    data?: {
      pipeline?: Record<string, unknown>
      stages?: typeof DEFAULT_PIPELINE_STAGES
      advanced?: boolean
      crm?: Record<string, unknown>
    }
  })?.data
  if (!data?.pipeline) return null
  return {
    pipeline: data.pipeline,
    stages: data.stages?.length ? data.stages : DEFAULT_PIPELINE_STAGES,
    advanced: Boolean(data.advanced),
    crm: data.crm,
  }
}

/** 仅在你明确操作后调用（如审核码确认）；日常加载不会自动改阶段。 */
async function maybeAutoAdvancePipelineStage() {
  if (!selectedUserId.value || stageSaving.value || autoStageAdvancing.value) return
  autoStageAdvancing.value = true
  try {
    const data = await fetchPipelineFromServer({ autoAdvance: true })
    if (!data) return
    pipelineStages.value = data.stages
    applyPipelineFromDoc(data.pipeline)
    syncSummaryFromPipeline(selectedUserId.value)
    if (data.advanced) {
      await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
    }
  } catch (e) {
    console.warn('[cs] auto-advance pipeline failed', e)
  } finally {
    autoStageAdvancing.value = false
  }
}

async function loadIntakeFormLink() {
  if (!selectedUserId.value) return
  intakeLinkLoading.value = true
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/demand-form/link`, {
      market_user_id: selectedUserId.value,
      client_name: intakePrefillGreetingName(),
      brief: demandIntake.brief.trim(),
    })
    const url = String((res as { data?: { form_url?: string } })?.data?.form_url || '')
    if (url) {
      intakeQuickFormUrl.value = url
      if (!demandIntake.signedFormUrl) demandIntake.signedFormUrl = url
    }
  } catch {
    /* ignore */
  } finally {
    intakeLinkLoading.value = false
  }
}

async function ensureIntakeFormUrl(): Promise<string> {
  if (intakeQuickFormUrl.value) return intakeQuickFormUrl.value
  if (demandIntake.signedFormUrl) {
    intakeQuickFormUrl.value = demandIntake.signedFormUrl
    return intakeQuickFormUrl.value
  }
  await loadIntakeFormLink()
  return intakeQuickFormUrl.value || demandIntake.signedFormUrl || ''
}

async function openOfficialIntakeForm() {
  const url = await ensureIntakeFormUrl()
  if (!url) {
    await appAlert('请先填写业务背景并生成话术，或稍候链接生成完成')
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

async function copyIntakeFormUrl() {
  const url = await ensureIntakeFormUrl()
  if (!url) {
    await appAlert('暂无表单链接，请稍候重试')
    return
  }
  try {
    await navigator.clipboard.writeText(url)
    await appAlert('已复制官网表单链接')
  } catch {
    await appAlert('复制失败')
  }
}

async function loadIntakeNoticeMessage() {
  if (!selectedUserId.value) return
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/demand-form/notice-message`, {
      market_user_id: selectedUserId.value,
      client_name: intakePrefillGreetingName(),
      brief: demandIntake.brief.trim(),
    })
    const data = (res as { data?: { message?: string; form_url?: string } })?.data
    if (data?.message) demandIntake.messageText = data.message
    if (data?.form_url) {
      intakeQuickFormUrl.value = data.form_url
      demandIntake.signedFormUrl = data.form_url
    }
  } catch {
    /* ignore */
  }
}

async function sendIntakeFormNotice(force: boolean = false) {
  force = force === true
  if (!selectedUserId.value) return
  if (!(await ensureBindingsSaved())) return
  intakeNoticeSending.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/wechat/send-intake-notice`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      contact_name: wechatSendContactName.value || '',
      brief: demandIntake.brief.trim(),
      force,
    })
    const data = (res as { success?: boolean; data?: { sent?: boolean; error?: string; message?: string; form_url?: string } })?.data
    if ((res as { success?: boolean }).success && data?.sent) {
      customerPipeline.intake_form_notice_sent = true
      customerPipeline.intake_sent = true
      if (data.message) demandIntake.messageText = data.message
      if (data.form_url) {
        intakeQuickFormUrl.value = data.form_url
        demandIntake.signedFormUrl = data.form_url
      }
      await appAlert('需求表单链接与说明已发送到微信群')
      await handleSyncWechat()
      await loadPipelineForCustomer()
    } else {
      await appAlert(data?.error || '发送失败，请确认微信已登录并重试')
    }
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    intakeNoticeSending.value = false
  }
}

async function fetchIntakeFormByAuditCode() {
  if (!selectedUserId.value) return
  const code = intakeAuditCode.value.trim()
  if (!code) {
    auditCodeError.value = '请填写客户提交的审核码'
    return
  }
  auditCodeError.value = ''
  auditCodeFetching.value = true
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/demand-form/by-audit-code`, {
      audit_code: code,
      market_user_id: selectedUserId.value,
    })
    const ok = Boolean((res as { success?: boolean })?.success)
    if (!ok) {
      auditCodeError.value = String((res as { error?: string })?.error || '获取失败')
      intakeAuditPreview.value = null
      return
    }
    const sub = (res as { data?: { submission?: Record<string, unknown> } })?.data?.submission
    if (!sub || typeof sub !== 'object') {
      auditCodeError.value = '未返回表单内容'
      intakeAuditPreview.value = null
      return
    }
    intakeAuditPreview.value = sub
    intakeAuditPreviewCode.value = String(sub.audit_code || code).trim()
    intakeAuditPreviewAt.value = String(sub.submitted_at || sub.created_at || '').trim()
  } catch (e) {
    auditCodeError.value = e instanceof Error ? e.message : String(e)
    intakeAuditPreview.value = null
  } finally {
    auditCodeFetching.value = false
  }
}

async function redeemIntakeAuditCode() {
  if (!selectedUserId.value) return
  const code = intakeAuditCode.value.trim()
  if (!code) {
    auditCodeError.value = '请填写客户提交的审核码'
    return
  }
  if (!intakeAuditPreview.value) {
    await fetchIntakeFormByAuditCode()
    if (!intakeAuditPreview.value) return
  }
  auditCodeError.value = ''
  auditCodeRedeeming.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/demand-form/redeem-code`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      audit_code: code,
    })
    const ok = Boolean((res as { success?: boolean })?.success)
    if (!ok) {
      auditCodeError.value = String((res as { error?: string })?.error || '校验失败')
      return
    }
    const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
    if (p) {
      applyPipelineFromDoc(p)
      syncSummaryFromPipeline(selectedUserId.value)
    }
    await loadEnterpriseUsers()
    await maybeAutoAdvancePipelineStage()
    await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
    const nextLabel = stageLabel(customerPipeline.stage)
    const renamed = customerPipeline.username || selectedEnterpriseUser.value?.username || ''
    const entHint = renamed ? `；客户名已更新为「${renamed}」` : ''
    await appAlert(`已关联需求单，当前阶段：${nextLabel}${entHint}`)
    intakeAuditCode.value = ''
    intakeAuditPreview.value = null
    intakeAuditPreviewCode.value = ''
    intakeAuditPreviewAt.value = ''
  } catch (e) {
    auditCodeError.value = e instanceof Error ? e.message : String(e)
  } finally {
    auditCodeRedeeming.value = false
  }
}

async function syncDemandFormFromMarket() {
  if (!selectedUserId.value) return
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/demand-form/status`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const p = (res as { data?: { pipeline?: Record<string, unknown> } })?.data?.pipeline
    if (p) {
      applyPipelineFromDoc(p)
      if (p.enterprise_auto_provisioned_at) {
        await loadEnterpriseUsers()
        syncSummaryFromPipeline(selectedUserId.value)
      }
    }
  } catch {
    /* 轮询失败时仍用本地 pipeline */
  }
}

async function finalizeIntakeFromPipeline(opts: { silent?: boolean } = {}) {
  if (!selectedUserId.value) return
  intakeFinalizeLoading.value = true
  try {
    await syncDemandFormFromMarket()
    const res = await post(`${CS_BRIDGE}/user-cs/demand-form/finalize`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const payload = res as {
      success?: boolean
      error?: string
      data?: { pipeline?: Record<string, unknown>; finalize?: Record<string, unknown> }
    }
    if (!payload?.success) {
      if (!opts.silent) await appAlert(payload?.error || '同步失败')
      return
    }
    const p = payload.data?.pipeline
    if (p) {
      applyPipelineFromDoc(p, { resetDraft: true })
      syncSummaryFromPipeline(selectedUserId.value)
    }
    if (opts.silent) return
    const fin = payload.data?.finalize as { erp_linked?: boolean; wechat_notice?: { sent?: boolean } } | undefined
    const erpName = customerPipeline.erp_customer_name
    let msg = erpName ? `已关联 ERP 客户：${erpName}` : '已同步 CRM 漏斗'
    if (fin?.wechat_notice?.sent) msg += '；已向微信群发送需求确认'
    await appAlert(msg)
  } catch (e) {
    if (!opts.silent) await appAlert(e instanceof Error ? e.message : '同步 CRM 失败')
  } finally {
    intakeFinalizeLoading.value = false
  }
}

async function loadPipelineFunnel() {
  funnelLoading.value = true
  funnelError.value = ''
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/pipeline/funnel`, { max_clients_per_stage: 8 })
    const data = (res as { data?: { stages?: Array<{ id: string; label: string; count: number }>; total_clients?: number } })
      ?.data
    funnelStages.value = data?.stages || []
    funnelTotalClients.value = Number(data?.total_clients || 0)
  } catch (e) {
    funnelStages.value = DEFAULT_PIPELINE_STAGES.map((s) => ({ ...s, count: 0 }))
    funnelTotalClients.value = 0
    funnelError.value = `漏斗加载失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    funnelLoading.value = false
  }
}

function toggleFunnelStageFilter(stageId: string) {
  funnelStageFilter.value = funnelStageFilter.value === stageId ? '' : stageId
}

async function pushExternalCrm() {
  if (!selectedUserId.value) return
  externalCrmPushLoading.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/crm/push-external`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const payload = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown> } }
    if (!payload?.success) {
      await appAlert(payload?.error || '推送失败')
      return
    }
    if (payload.data?.pipeline) applyPipelineFromDoc(payload.data.pipeline)
    await appAlert(externalCrmStatusLabel.value || '已提交外部 CRM 推送')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '推送失败')
  } finally {
    externalCrmPushLoading.value = false
  }
}

async function pullExternalCrm() {
  if (!selectedUserId.value) return
  externalCrmPullLoading.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/crm/pull-external`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const payload = res as {
      success?: boolean
      error?: string
      data?: { pipeline?: Record<string, unknown> }
    }
    if (!payload?.success) {
      await appAlert(payload?.error || '拉取失败')
      return
    }
    if (payload.data?.pipeline) applyPipelineFromDoc(payload.data.pipeline, { resetDraft: true })
    await appAlert(externalCrmPullStatusLabel.value || '已从外部 CRM 拉取阶段')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '拉取失败')
  } finally {
    externalCrmPullLoading.value = false
  }
}

async function dispatchChangeRequestOps(cr: { id: string; ticket_no?: string }) {
  if (!selectedUserId.value) return
  changeRequestOpsDispatchingId.value = cr.id
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/change-requests/${cr.id}/ops-dispatch`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      contact_name: selectedEnterpriseUser.value?.username || wechatSendContactName.value,
    })
    const payload = res as {
      success?: boolean
      error?: string
      data?: { job_id?: string; request?: Record<string, unknown> }
    }
    if (!payload?.success) {
      await appAlert(payload?.error || '派发失败')
      await loadChangeRequestsForCustomer()
      return
    }
    await loadChangeRequestsForCustomer()
    const jobId = payload.data?.job_id || ''
    await appAlert(jobId ? `已派发运维任务 job_id=${jobId}` : '已派发运维任务')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '派发失败')
  } finally {
    changeRequestOpsDispatchingId.value = ''
  }
}

async function loadChangeRequestsForCustomer() {
  if (!selectedUserId.value) return
  changeRequestsLoading.value = true
  try {
    const res = await get<{
      success?: boolean
      data?: { requests?: typeof changeRequests.value }
    }>(`${CS_BRIDGE}/user-cs/change-requests`, { market_user_id: selectedUserId.value })
    changeRequests.value = res?.success ? (res.data?.requests || []) : []
  } catch {
    changeRequests.value = []
  } finally {
    changeRequestsLoading.value = false
  }
}

async function onChangeRequestStatus(
  cr: { id: string },
  status: string,
) {
  if (!selectedUserId.value || !cr.id) return
  try {
    const res = await put<{ success?: boolean; error?: string }>(
      `${CS_BRIDGE}/user-cs/change-requests/${encodeURIComponent(cr.id)}/status`,
      {
        market_user_id: selectedUserId.value,
        status,
      },
    )
    if (!res?.success) {
      await appAlert(res?.error || '更新失败')
      return
    }
    await loadChangeRequestsForCustomer()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '更新失败')
  }
}

async function notifyChangeRequestWechat(cr: { id: string }) {
  if (!selectedUserId.value || !cr.id) return
  changeRequestNotifyingId.value = cr.id
  try {
    const res = await post<{ success?: boolean; error?: string }>(
      `${CS_BRIDGE}/user-cs/change-requests/${encodeURIComponent(cr.id)}/notify-wechat`,
      {
        market_user_id: selectedUserId.value,
        contact_name: wechatSendContactName.value,
      },
    )
    if (!res?.success) {
      await appAlert(res?.error || '发送失败')
      return
    }
    await appAlert('已同步变更工单至微信群')
    await loadChangeRequestsForCustomer()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '发送失败')
  } finally {
    changeRequestNotifyingId.value = ''
  }
}

async function maybeAutoFinalizeIntakeOnOpen() {
  if (!selectedUserId.value) return
  if (!customerPipeline.intake_submitted_at || customerPipeline.crm_funnel_synced_at) return
  if (intakeAutoFinalizeAttempted.value === selectedUserId.value) return
  intakeAutoFinalizeAttempted.value = selectedUserId.value
  await finalizeIntakeFromPipeline({ silent: true })
}

async function loadPipelineForCustomer() {
  if (!selectedUserId.value) return
  try {
    await syncDemandFormFromMarket()
    const data = await fetchPipelineFromServer({ autoAdvance: true })
    if (!data) return
    pipelineStages.value = data.stages
    applyPipelineFromDoc(data.pipeline)
    applyCrmBundle(data.crm as { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> })
    syncSummaryFromPipeline(selectedUserId.value)
    if (data.advanced) {
      await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
    } else if (
      String(data.pipeline.stage || '') === 'intake'
      && data.pipeline.intake_submitted_at
    ) {
      await maybeAutoAdvancePipelineStage()
    }
    await maybeAutoFinalizeIntakeOnOpen()
    await loadChangeRequestsForCustomer()
    await loadFinanceLedger()
  } catch {
    pipelineStages.value = DEFAULT_PIPELINE_STAGES
    stopPassiveLoopTimer()
    changeRequests.value = []
  }
}

function pickPipelineStageDraft(stageId: string) {
  if (stageSaving.value) return
  stageDraft.value = stageId
}

async function savePipelineStage(
  targetStage?: string,
  opts: { silent?: boolean; confirmMessage?: string; auto?: boolean } = {},
) {
  if (!selectedUserId.value) return
  const stage = (targetStage ?? stageDraft.value).trim()
  if (stage === currentStageId.value) return
  if (!opts.silent) {
    const label = stageLabel(stage)
    const ok = window.confirm(
      opts.confirmMessage
        ?? `将当前客户阶段改为「${label}」？\n可前进或回退，不影响已保存的群绑定与消息。`,
    )
    if (!ok) {
      stageDraft.value = currentStageId.value
      return
    }
  }
  stageDraft.value = stage
  const shouldOfferIntakeNotice = stage === 'intake' && !customerPipeline.intake_form_notice_sent
  stageSaving.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/pipeline/stage`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      stage,
      manual: !opts.auto,
      note: opts.auto ? 'checklist_complete' : '',
    })
    const payload = res as { success?: boolean; error?: string; data?: { pipeline?: Record<string, unknown> } }
    if (!payload?.success) {
      await appAlert(payload?.error || '保存失败')
      return
    }
    const p = payload.data?.pipeline
    if (p) {
      applyPipelineFromDoc(p, { resetDraft: true })
      applyDeliveryFromDoc(p)
      syncSummaryFromPipeline(selectedUserId.value)
    } else {
      await loadPipelineForCustomer()
    }
    if (
      stageRank(stage) >= stageRank('intake_done')
      && (!customerPipeline.crm_opportunity_id || !customerPipeline.crm_quote_id)
    ) {
      await syncCrmRecord()
    }
    await loadClientSummary(selectedUserId.value, selectedEnterpriseUser.value?.username)
    if (shouldOfferIntakeNotice && stage === currentStageId.value) {
      const sendNow = window.confirm(
        '阶段已保存为「需求采集」。是否现在向微信群发送官网表单链接与填写说明？\n（不会自动发送，点「取消」可稍后再发）',
      )
      if (sendNow) await sendIntakeFormNotice()
    }
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '保存阶段失败')
  } finally {
    stageSaving.value = false
  }
}

async function analyzeCustomerProgress(options: { skipSync?: boolean } = {}) {
  if (!selectedUserId.value) return
  pipelineAnalyzing.value = true
  try {
    if (bindingsDirty.value || !selectedEnterpriseUser.value?.bindingCount) {
      await appAlert('请先保存群聊绑定')
      return
    }
    if (!options.skipSync) {
      await syncGroups(selectedUserId.value)
      await loadWechatSummary()
    }
    const res = await post(`${CS_BRIDGE}/user-cs/analyze`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      has_binding: (selectedEnterpriseUser.value?.bindingCount || 0) > 0,
      intake_sent: customerPipeline.intake_sent || Boolean(demandIntake.messageText),
    })
    const data = (res as {
      data?: {
        pipeline?: Record<string, unknown>
        connected_welcome?: Record<string, unknown>
        crm?: { opportunity?: Record<string, unknown>; quote?: Record<string, unknown> }
      }
    })?.data
    const p = data?.pipeline
    if (p) {
      applyPipelineFromDoc(p, { resetDraft: false })
      applyDeliveryFromDoc(p)
      applyCrmBundle(data?.crm)
      syncSummaryFromPipeline(selectedUserId.value)
    }
    const welcome = data?.connected_welcome as { sent?: boolean; skipped?: boolean; error?: string } | undefined
    if (welcome?.sent) {
      customerPipeline.connected_welcome_sent = true
      await appAlert('已向微信群发送建联欢迎语')
      await handleSyncWechat()
    } else if (welcome?.attempted && !welcome?.sent && welcome?.error) {
      await appAlert(`建联欢迎语发送失败：${welcome.error}`)
    }
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    pipelineAnalyzing.value = false
  }
}

async function copyLatestReplyHint() {
  const name = selectedEnterpriseUser.value?.username || '客户'
  const text = `您好，关于您刚才在群里的问题，我们已收到。${name} 这边会继续跟进，如需提交正式需求也可填写：${demandIntake.formUrl}`
  try {
    await navigator.clipboard.writeText(text)
    await appAlert('已复制')
  } catch {
    await appAlert('复制失败')
  }
}

function groupClientDisplayName() {
  const n = intakePrefillGreetingName().trim()
  return n || '您好'
}

function groupScriptForStage(): string {
  const name = groupClientDisplayName()
  if (currentStageId.value === 'intake_done') {
    return (
      `${name}，您好！\n\n` +
      '我们已收到并核对您提交的需求信息。请确认目前理解的范围是否准确：\n' +
      '· 实施范围：（请按档案补充）\n' +
      '· 期望交付时间：（请补充）\n' +
      '· 需对接的系统：（请补充）\n\n' +
      '若无补充，我们将在 1 个工作日内于本群发送正式报价方案；有变更请直接在本群回复即可。'
    )
  }
  if (currentStageId.value === 'negotiating') {
    return (
      `${name}，感谢您的反馈。\n\n` +
      '关于价格与交付条件，我们可以在以下范围内协调（请按实际情况修改后发送）：\n' +
      '· 可调整项：范围精简 / 分期交付 / 付款方式等\n' +
      '· 当前方案报价：（请填写金额与说明）\n\n' +
      '您看这样是否可行？确认后我们更新方案并进入合同签署流程。'
    )
  }
  return (
    `${name}，您好！\n\n` +
    '根据目前确认的需求范围，我方初步报价如下（请按实际情况填写后发送）：\n' +
    '· 实施范围：\n' +
    '· 费用：    元（含税/不含税请说明）\n' +
    '· 周期：约    周\n\n' +
    '详细说明见上文/附件。如需调整范围或预算，请在本群直接回复，我们再议。'
  )
}

async function copyGroupScript(text: string) {
  if (!text.trim()) return
  try {
    await navigator.clipboard.writeText(text)
    await appAlert('已复制话术，可粘贴到微信群发送')
  } catch {
    await appAlert('复制失败')
  }
}

function fillWechatDraft(text: string) {
  wechatSend.message = text
  wechatSend.error = ''
  nextTick(() => {
    const el = document.querySelector('.cs-send-compose textarea') as HTMLTextAreaElement | null
    el?.focus()
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

async function sendGroupScript(text: string) {
  if (!(await ensureBindingsSaved())) return
  fillWechatDraft(text)
  await sendWechatToGroup()
}

async function sendConnectedWelcome(force: boolean = false) {
  force = force === true
  if (!selectedUserId.value) return
  if (!(await ensureBindingsSaved())) return
  connectedWelcomeSending.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/wechat/send-connected-welcome`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      contact_name: wechatSendContactName.value || '',
      force,
    })
    const data = (res as { success?: boolean; data?: { sent?: boolean; error?: string; message?: string; send_result?: { error?: string } } })?.data
    if ((res as { success?: boolean }).success && data?.sent) {
      customerPipeline.connected_welcome_sent = true
      if (data.message) wechatSend.message = data.message
      await appAlert('建联欢迎语已发送到微信群')
      await handleSyncWechat()
      await loadPipelineForCustomer()
    } else {
      await appAlert(data?.error || data?.send_result?.error || '建联欢迎语发送失败，请确认微信已登录并重试')
    }
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    connectedWelcomeSending.value = false
  }
}

async function ensureBindingsSaved(): Promise<boolean> {
  if (!selectedUserId.value) return false
  if (!bindingsDirty.value && (selectedEnterpriseUser.value?.bindingCount || 0) > 0) return true
  if (!selectedGroupIdStrings.value.length) {
    await appAlert('请先在左侧勾选群聊并点击「保存绑定」')
    return false
  }
  try {
    await saveBindings()
    return true
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : '保存绑定失败')
    return false
  }
}

type PassivePollPayload = {
  message?: string
  replied_count?: number
  detected_count?: number
  feed?: Array<Record<string, unknown>>
  llm_probe?: { ready?: boolean; message?: string }
  snapshot?: {
    success?: boolean
    rebuilt?: boolean
    skipped?: boolean
    message?: string
  }
  messages_pulled_this_round?: number
  sync?: {
    success?: boolean
    message?: string
    synced?: number
    stale?: boolean
    stale_reason?: string
    messages_pulled?: number
    messages_pulled_this_round?: number
    latest_message_label?: string
    message_db_ready?: boolean
  }
  replies?: Array<{
    reply_source?: string
    reply?: string
    llm_error?: string
    incoming?: string
    blocked?: boolean
    block_reason?: string
  }>
  blocked_count?: number
}

/** 轮询后刷新列表：勿用 passive_poll 内旧 feed 覆盖刚 refresh 的结果 */
async function reloadFeedAfterRefresh(marketUserId: number) {
  await loadFeed(marketUserId, 20, { sync: false })
}

function formatPassivePollSummary(data: PassivePollPayload | undefined) {
  const chunks: string[] = []
  if (data?.message) chunks.push(data.message)
  if (typeof data?.detected_count === 'number' && data.detected_count > 0) {
    chunks.push(`识别新消息 ${data.detected_count} 条`)
  }
  const snap = data?.snapshot
  const sync = data?.sync
  if (sync?.stale) {
    chunks.push(`⚠ 库过期：${sync.stale_reason || sync.message || '解密库落后'}`)
  } else if (sync?.message_db_ready === false) {
    chunks.push('⚠ 未连接微信消息库，请到数据来源执行「扫密钥并同步聊天」')
  } else if (sync?.message) {
    chunks.push(sync.message)
  } else if (sync?.latest_message_label) {
    chunks.push(`库内最新 ${sync.latest_message_label}`)
  }
  if (snap?.success) {
    if (snap.rebuilt) {
      chunks.push('本机微信库已复制并解密')
    } else if (snap.skipped) {
      chunks.push('本机库指纹未变，沿用上次快照')
    } else if (snap.message && !String(sync?.message || '').includes(String(snap.message))) {
      chunks.push(String(snap.message))
    }
  } else if (snap?.message) {
    chunks.push(`快照失败：${snap.message}`)
  }
  const probe = data?.llm_probe
  if (probe) {
    chunks.push(probe.ready ? 'LLM 已就绪' : `LLM 未就绪：${probe.message || ''}`)
  }
  const replied = data?.replied_count ?? 0
  const blockedN = data?.blocked_count ?? 0
  if (blockedN > 0 && replied === 0 && !data?.dry_run) {
    const firstBlocked = data?.replies?.find((r) => r.blocked || r.reply_source === 'blocked')
    const reason =
      firstBlocked?.block_reason ||
      firstBlocked?.llm_error ||
      'LLM 或质量检查未通过，已拦截未发送'
    chunks.push(`未发送（质量/LLM）：${reason}`)
  }
  if (typeof data?.detected_count === 'number' && data.detected_count > 0 && replied === 0 && !data?.dry_run) {
    const first = data?.replies?.[0] as {
      send_error?: string
      send_result?: { error?: string }
      reply?: string
      blocked?: boolean
      reply_source?: string
    } | undefined
    if (first?.blocked || first?.reply_source === 'blocked') {
      // 已在 blocked 分支说明
    } else {
    const sendErr =
      first?.send_error ||
      first?.send_result?.error ||
      '请确认 Mac 微信已打开、群名与绑定完全一致、已授权辅助功能'
    chunks.push(`⚠ 未发送到微信：${sendErr}`)
    }
  } else if (
    typeof data?.detected_count === 'number' &&
    data.detected_count === 0 &&
    !data?.dry_run
  ) {
    chunks.push('无待回复新消息（重新监听后只回复此后他人新消息；或点「被动回复」补答最新一条）')
  }
  const first = data?.replies?.[0]
  if (first?.reply_source) {
    if (first.reply_source === 'template') {
      chunks.push('⚠ 回复=template（不应出现，请检查 LLM 配置）')
    } else {
      chunks.push(`回复=${first.reply_source}`)
    }
    if (replied > 0) chunks.push(`已发送 ${replied} 条`)
    if (first.llm_error && first.reply_source !== 'llm') chunks.push(`原因：${first.llm_error}`)
    if (first.reply) {
      const preview = String(first.reply)
      chunks.push(`预览：${preview.length > 60 ? `${preview.slice(0, 60)}…` : preview}`)
    }
  }
  return chunks.filter(Boolean).join(' · ')
}

async function loadPassiveLlmStatus() {
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/wechat/llm-status`)
    const probe = (res as { data?: { ready?: boolean; message?: string } })?.data
    passiveLlmStatus.value = probe?.ready
      ? `LLM：${probe?.message || '已配置（与智能对话同源）'}`
      : `LLM 未就绪：${probe?.message || '请检查平台/直连配置'}`
  } catch {
    passiveLlmStatus.value = ''
  }
}

function formatPassivePollTime(iso?: string) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

function stopPassiveLoopTimer() {
  if (passiveLoopTimer) {
    clearInterval(passiveLoopTimer)
    passiveLoopTimer = null
  }
}

function startPassiveLoopTimer() {
  stopPassiveLoopTimer()
  if (!passiveLoopEnabled.value || !selectedUserId.value) return
  const ms = Math.max(10, passiveLoopIntervalSec.value) * 1000
  passiveLoopTimer = setInterval(() => {
    void runPassiveLoopTick()
  }, ms)
}

async function persistPassiveLoopConfig() {
  if (!selectedUserId.value) return
  try {
    await post(`${CS_BRIDGE}/user-cs/wechat/passive-loop`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      poll_enabled: passiveLoopEnabled.value,
      poll_interval_sec: passiveLoopIntervalSec.value,
    })
  } catch (e) {
    console.warn('保存轮询客服配置失败', e)
  }
}

async function onPassiveLoopToggle() {
  await persistPassiveLoopConfig()
  if (passiveLoopEnabled.value) {
    startPassiveLoopTimer()
    void refreshPassiveLoopStatus()
  } else {
    stopPassiveLoopTimer()
  }
}

async function onPassiveLoopIntervalChange() {
  await persistPassiveLoopConfig()
  if (passiveLoopEnabled.value) {
    startPassiveLoopTimer()
    void runPassiveLoopTick()
  }
}

async function resetPassiveWatch() {
  if (!selectedUserId.value) return
  if (!(await ensureBindingsSaved())) return
  passiveLoopBusy.value = true
  try {
    await post(`${CS_BRIDGE}/user-cs/wechat/passive-reset-watch`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      poll_enabled: passiveLoopEnabled.value,
      poll_interval_sec: passiveLoopIntervalSec.value,
    })
    const refreshRes = await refreshBoundGroupsLikeDataSources(selectedUserId.value)
    await loadPipelineForCustomer()
    passiveLoopSummary.value = [
      '已重新对齐群聊进度，请在群里发新消息后等待轮询',
      refreshRes.message || '',
    ]
      .filter(Boolean)
      .join(' · ')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    passiveLoopBusy.value = false
  }
}

/** 仅刷新轮询状态（实际探测/回复由服务端后台执行）。 */
async function refreshPassiveLoopStatus() {
  if (!selectedUserId.value || !passiveLoopEnabled.value) return
  const uid = selectedUserId.value
  const uname = encodeURIComponent(selectedEnterpriseUser.value?.username || '')
  try {
    const res = await get(
      `${CS_BRIDGE}/user-cs/wechat/passive-loop?market_user_id=${uid}&username=${uname}`,
    )
    const data = (res as { data?: { last_poll_at?: string; last_poll_message?: string } })?.data
    passiveLoopLastAt.value = formatPassivePollTime(data?.last_poll_at)
    if (data?.last_poll_message) {
      passiveLoopSummary.value = String(data.last_poll_message)
    }
    void reloadFeedAfterRefresh(uid)
    if (wechatDrawer.visible && wechatDrawer.contactId > 0) {
      await openWechatDrawer(wechatDrawer.contactId)
    }
  } catch (e) {
    console.warn('刷新轮询状态失败', e)
  }
}

async function runPassiveLoopTick() {
  if (!selectedUserId.value || !passiveLoopEnabled.value || passiveLoopBusy.value || passivePolling.value) {
    return
  }
  if (!hasBinding.value) {
    return
  }
  passiveLoopBusy.value = true
  try {
    await refreshPassiveLoopStatus()
  } finally {
    passiveLoopLastAt.value = new Date().toLocaleString(undefined, {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
    passiveLoopBusy.value = false
  }
}

async function runPassivePoll(dryRun: boolean) {
  if (!selectedUserId.value) return
  if (!(await ensureBindingsSaved())) return
  passivePolling.value = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/wechat/passive-poll`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      dry_run: dryRun,
      auto_reply: !dryRun,
      max_replies: 1,
      use_llm: true,
      skip_sync: false,
      catch_up_latest: !dryRun,
    })
    const data = (res as { data?: PassivePollPayload })?.data
    await reloadFeedAfterRefresh(selectedUserId.value)
    const summary = formatPassivePollSummary(data)
    await appAlert(summary || data?.message || (dryRun ? '探测完成' : '被动回复完成'))
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    passivePolling.value = false
  }
}

async function sendWechatToGroup() {
  if (!selectedUserId.value || !wechatSend.message.trim()) return
  if (!(await ensureBindingsSaved())) return
  const contact = wechatSendContactName.value
  if (!contact) {
    await appAlert('请先绑定群聊并同步，或确认群名称')
    return
  }
  wechatSend.loading = true
  wechatSend.error = ''
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/wechat/send`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      contact_name: contact,
      message: wechatSend.message.trim(),
    })
    const ok = (res as { success?: boolean; data?: { success?: boolean; error?: string } })?.success
      && (res as { data?: { success?: boolean } })?.data?.success !== false
    if (!ok) {
      const err = (res as { error?: string; data?: { error?: string } })?.error
        || (res as { data?: { error?: string } })?.data?.error
        || '发送失败'
      wechatSend.error = err
      await appAlert(err)
      return
    }
    wechatSend.message = ''
    await appAlert('已发送到微信群')
    await handleSyncWechat()
    await analyzeCustomerProgress({ skipSync: true })
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    wechatSend.error = msg
    await appAlert(msg)
  } finally {
    wechatSend.loading = false
  }
}

async function generateDemandIntake() {
  if (!demandIntake.brief.trim()) return
  demandIntake.loading = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/demand-intake`, {
      brief: demandIntake.brief.trim(),
      client_name: intakePrefillGreetingName(),
      form_url: demandIntake.formUrl.trim(),
      channel: 'wechat',
      market_user_id: selectedUserId.value ?? undefined,
    })
    const payload = (res as { data?: { success?: boolean; items?: Array<Record<string, string>>; error?: string } })?.data
    if (!payload?.success) {
      await appAlert(payload?.error || '生成失败')
      return
    }
    demandIntake.messageText = String(payload.items?.[0]?.message_text || '')
    const signed = String(
      (payload as { form_url?: string }).form_url
        || payload.items?.[0]?.form_url
        || '',
    )
    if (signed) {
      demandIntake.signedFormUrl = signed
      intakeQuickFormUrl.value = signed
    }
    customerPipeline.intake_sent = true
    customerPipeline.stage = 'intake'
    if (selectedUserId.value) syncSummaryFromPipeline(selectedUserId.value)
    await loadPipelineForCustomer()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    demandIntake.loading = false
  }
}

async function loadContractFields() {
  if (!selectedUserId.value) return
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/contract/fields`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const values = (res as { data?: { values?: Record<string, string> } })?.data?.values || {}
    contractForm.party_a_name = values.party_a_name || selectedEnterpriseUser.value?.username || ''
    contractForm.party_a_credit_code = values.party_a_credit_code || ''
    contractForm.total_amount_number = values.total_amount_number || ''
    contractForm.expected_out_trade_no =
      values.expected_out_trade_no || values.out_trade_no || ''
    contractForm.sign_date = values.sign_date?.slice(0, 10) || ''
    contractForm.main_function_list = values.main_function_list || ''
  } catch {
    /* ignore */
  }
}

function contractFieldValues() {
  return {
    party_a_name: contractForm.party_a_name.trim(),
    party_a_credit_code: contractForm.party_a_credit_code.trim(),
    total_amount_number: contractForm.total_amount_number.trim(),
    expected_out_trade_no: contractForm.expected_out_trade_no.trim(),
    sign_date: contractForm.sign_date,
    main_function_list: contractForm.main_function_list.trim(),
  }
}

async function saveContractFields(opts?: { silent?: boolean }) {
  if (!selectedUserId.value) return
  contractForm.savingFields = true
  try {
    const res = await put(`${CS_BRIDGE}/user-cs/contract/fields`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      values: contractFieldValues(),
    })
    const payload = res as { success?: boolean; error?: string; data?: Record<string, string> }
    if (!payload?.success) {
      if (!opts?.silent) await appAlert(payload?.error || '保存失败')
      return
    }
    await loadPipelineForCustomer()
    if (!opts?.silent) await appAlert('合同字段已保存（含关联订单号，将用于到款核对）')
  } catch (e) {
    if (!opts?.silent) await appAlert(e instanceof Error ? e.message : '保存合同字段失败')
  } finally {
    contractForm.savingFields = false
  }
}

async function generateContract() {
  if (!selectedUserId.value) return
  if (!contractForm.party_a_name.trim() || !contractForm.total_amount_number.trim()) {
    await appAlert('请填写甲方名称和合同金额')
    return
  }
  contractForm.loading = true
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/contract/generate`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      values: contractFieldValues(),
    })
    const data = (res as { data?: Record<string, string> })?.data
    if (!data?.filename) {
      await appAlert('生成失败')
      return
    }
    contractForm.filename = String(data.filename)
    contractForm.downloadUrl = String(data.download_url || '')
    contractForm.wechatHint = String(data.wechat_hint || '')
    await loadPipelineForCustomer()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    contractForm.loading = false
  }
}

async function copyContractHint() {
  if (!contractForm.wechatHint) return
  try {
    await navigator.clipboard.writeText(contractForm.wechatHint)
    await appAlert('已复制发送话术')
  } catch {
    await appAlert('复制失败')
  }
}

async function sendDemandIntakeToWechat() {
  if (!demandIntake.messageText.trim() || !selectedUserId.value) return
  demandIntake.sendingWechat = true
  wechatSend.error = ''
  try {
    const contact = wechatSendContactName.value
    if (!contact) {
      await appAlert('请先保存群聊绑定')
      return
    }
    const res = await post(`${CS_BRIDGE}/user-cs/wechat/send`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
      contact_name: contact,
      message: demandIntake.messageText.trim(),
    })
    const ok = (res as { success?: boolean; data?: { success?: boolean } })?.success
      && (res as { data?: { success?: boolean } })?.data?.success !== false
    if (!ok) {
      const err = (res as { error?: string; data?: { error?: string } })?.error
        || (res as { data?: { error?: string } })?.data?.error
        || '发送失败'
      await appAlert(err)
      return
    }
    customerPipeline.intake_sent = true
    await appAlert('需求采集话术已发送到微信群')
    await loadPipelineForCustomer()
    await handleSyncWechat()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    demandIntake.sendingWechat = false
  }
}

async function copyDemandMessage() {
  if (!demandIntake.messageText) return
  try {
    await navigator.clipboard.writeText(demandIntake.messageText)
    await appAlert('已复制')
  } catch {
    await appAlert('复制失败')
  }
}

function parseMarketUserIdFromRoute(): number | null {
  const raw = route.query.market_user_id
  const n = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(n) && n > 0 ? n : null
}

function syncEnterpriseCredsFromPipeline() {
  enterpriseCreds.username = String(
    customerPipeline.enterprise_login_username
      || customerPipeline.username
      || selectedEnterpriseUser.value?.username
      || '',
  ).trim()
  enterpriseCreds.password = String(customerPipeline.enterprise_login_password || '').trim()
  enterpriseCreds.password_recorded = Boolean(enterpriseCreds.password)
  enterpriseCreds.issued_at = String(customerPipeline.enterprise_credentials_issued_at || '').trim()
  enterpriseCreds.is_enterprise = Boolean(
    customerPipeline.enterprise_auto_provisioned_at
      || selectedEnterpriseUser.value?.is_enterprise,
  )
}

function applyEnterpriseCredsPayload(data: Record<string, unknown> | null | undefined) {
  if (!data) return
  const username = String(data.username || '').trim()
  const password = String(data.password || '').trim()
  const issuedAt = String(data.issued_at || '').trim()
  if (username) {
    customerPipeline.enterprise_login_username = username
    customerPipeline.username = username
  }
  if (password) {
    customerPipeline.enterprise_login_password = password
  }
  if (issuedAt) {
    customerPipeline.enterprise_credentials_issued_at = issuedAt
  }
  if (data.is_enterprise) {
    customerPipeline.enterprise_auto_provisioned_at = String(
      customerPipeline.enterprise_auto_provisioned_at || issuedAt || new Date().toISOString(),
    )
  }
  enterpriseCreds.email = String(data.email || '').trim()
  enterpriseCreds.password_recorded = Boolean(data.password_recorded ?? password)
  enterpriseCreds.is_enterprise = Boolean(data.is_enterprise ?? enterpriseCreds.is_enterprise)
  enterpriseCreds.error = String(data.market_fetch_error || '').trim()
  syncEnterpriseCredsFromPipeline()
}

async function loadEnterpriseCredentials() {
  if (!selectedUserId.value) return
  enterpriseCreds.loading = true
  enterpriseCreds.error = ''
  try {
    const res = await get(`${CS_BRIDGE}/user-cs/enterprise-credentials`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const body = res as { success?: boolean; error?: string; data?: Record<string, unknown> }
    if (body.success === false) {
      throw new Error(body.error || '加载企业账号失败')
    }
    applyEnterpriseCredsPayload(body.data)
  } catch (e) {
    enterpriseCreds.error = e instanceof Error ? e.message : String(e)
  } finally {
    enterpriseCreds.loading = false
  }
}

async function issueEnterpriseCredentials() {
  if (!selectedUserId.value) return
  if (
    enterpriseCreds.password_recorded
    && !window.confirm('将生成新密码并覆盖修茈市场 / 企业版登录密码，是否继续？')
  ) {
    return
  }
  enterpriseCreds.issuing = true
  enterpriseCreds.error = ''
  try {
    const res = await post(`${CS_BRIDGE}/user-cs/enterprise-credentials/issue`, {
      market_user_id: selectedUserId.value,
      username: selectedEnterpriseUser.value?.username || '',
    })
    const body = res as { success?: boolean; error?: string; data?: Record<string, unknown> }
    if (body.success === false) {
      throw new Error(body.error || '生成密码失败')
    }
    applyEnterpriseCredsPayload(body.data)
    await appAlert('已生成临时密码，请复制后发给客户（仅在此处与档案中保留明文）')
  } catch (e) {
    enterpriseCreds.error = e instanceof Error ? e.message : String(e)
    await appAlert(enterpriseCreds.error)
  } finally {
    enterpriseCreds.issuing = false
  }
}

async function copyEnterpriseCredential(kind: 'username' | 'password') {
  const text = kind === 'username' ? enterpriseCreds.username : enterpriseCreds.password
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    await appAlert(kind === 'username' ? '登录账号已复制' : '登录密码已复制')
  } catch {
    await appAlert('复制失败，请手动选择复制')
  }
}

async function loadWechatSummary(options: { syncFirst?: boolean } = {}): Promise<string> {
  if (!selectedUserId.value) return ''
  try {
    await loadFeed(selectedUserId.value, 20, { sync: Boolean(options.syncFirst) })
    return ''
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    console.warn('加载群聊摘要失败', e)
    return msg
  }
}

async function toggleClient(userId: number) {
  if (expandedClientId.value === userId) {
    expandedClientId.value = null
    selectedUserId.value = null
    stopPassiveLoopTimer()
    passiveLoopEnabled.value = false
    return
  }
  expandedClientId.value = userId
  await selectEnterprise(userId)
  demandIntake.messageText = ''
  demandIntake.signedFormUrl = ''
  intakeQuickFormUrl.value = ''
  intakeAuditCode.value = ''
  auditCodeError.value = ''
  intakeAuditPreview.value = null
  intakeAuditPreviewCode.value = ''
  intakeAuditPreviewAt.value = ''
  await loadWechatSummary({ syncFirst: true })
  await loadPassiveLlmStatus()
  await loadPipelineForCustomer()
  syncDemandIntakeClientNameFromPipeline()
  syncEnterpriseCredsFromPipeline()
  void loadEnterpriseCredentials()
  if (customerPipeline.stage === 'intake' || customerPipeline.stage === 'intake_done') {
    void loadIntakeFormLink()
  }
  await loadContractFields()
}

async function handleSaveBindings(options: { syncAfter?: boolean } = {}) {
  if (!selectedUserId.value || !selectedGroupIdStrings.value.length) {
    await appAlert('请至少勾选一个群')
    return false
  }
  try {
    await saveBindings()
    if ((selectedEnterpriseUser.value?.bindingCount || 0) > 0) {
      passiveLoopSummary.value = ''
    }
    if (options.syncAfter) {
      await handleSyncWechat(true)
      await appAlert('群聊绑定已保存并同步')
    } else {
      await appAlert('群聊绑定已保存')
    }
    return true
  } catch (e) {
    await appAlert(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    return false
  }
}

/**
 * 与数据来源「扫密钥并同步聊天」同链路：复制本机微信库 → 解密 → 刷新绑定群 context。
 * 禁止仅读旧 WECHAT_MSG_DB_PATH（会导致轮询假刷新）。
 */
async function refreshBoundGroupsLikeDataSources(marketUserId: number) {
  const groupRes = await wechatGroupBridgeApi.syncGroups({
    market_user_id: marketUserId,
    force_refresh: true,
    message_limit: 80,
  })
  await loadFeed(marketUserId, 20, { sync: false })
  const synced = Number(groupRes?.synced ?? 0)
  const failed = Number(groupRes?.failed ?? 0)
  const pulledNew = Number(
    groupRes?.messages_pulled_this_round ?? groupRes?.messages_pulled ?? 0,
  )
  const latest =
    String(groupRes?.latest_message_label || '').trim() ||
    (() => {
      let label = ''
      let latestTs = 0
      for (const item of feed.value) {
        const row = formatFeedItem(item)
        const tsRaw = item.last_message_time ?? item.timestamp
        const tsNum =
          typeof tsRaw === 'number'
            ? tsRaw < 1e12
              ? tsRaw * 1000
              : tsRaw
            : Date.parse(String(tsRaw || ''))
        if (!Number.isNaN(tsNum) && tsNum >= latestTs) {
          latestTs = tsNum
          label = row.timeLabel || ''
        }
      }
      return label
    })()
  const snap = groupRes?.snapshot as { rebuilt?: boolean; skipped?: boolean; message?: string } | undefined
  const snapNote = snap?.rebuilt
    ? '已复制解密本机微信库'
    : snap?.skipped
      ? '本机库未变，已复用快照'
      : snap?.message
        ? String(snap.message)
        : ''
  let message =
    groupRes?.message ||
    `已刷新 ${synced} 个群${failed ? `（${failed} 个失败）` : ''}，新增 ${pulledNew} 条${latest ? `，库内最新 ${latest}` : ''}`
  if (snapNote && !message.includes(snapNote)) {
    message = `${message}（${snapNote}）`
  }
  return {
    success: Boolean(groupRes?.success) && synced > 0,
    synced,
    failed,
    message,
    latest_message_label: latest,
    messages_pulled_this_round: pulledNew,
    snapshot: snap,
    details: Array.isArray(groupRes?.details) ? groupRes.details : [],
  }
}

async function handleSyncWechat(skipAlert = false) {
  if (!selectedUserId.value) {
    if (!skipAlert) await appAlert('请先选择企业客户')
    return
  }
  if (bindingsDirty.value) {
    if (!skipAlert) await appAlert('将先保存群绑定，再从本机微信库刷新聊天记录（与数据来源相同）')
    await handleSaveBindings({ syncAfter: true })
    return
  }
  if (!(selectedEnterpriseUser.value?.bindingCount || 0)) {
    if (!skipAlert) await appAlert('请先在左侧勾选群聊并点击「保存绑定」，再同步群聊')
    return
  }
  syncing.value = true
  try {
    const res = await refreshBoundGroupsLikeDataSources(selectedUserId.value)
    if (!res.success && res.synced === 0) {
      if (!skipAlert) {
        await appAlert(
          res.message ||
            '刷新失败。请到「数据来源」对绑定群点击「刷新聊天记录」，或检查微信目录与密钥',
        )
      }
      return
    }
    await loadFeed(selectedUserId.value, 20, { sync: false })
    if (!skipAlert) {
      await appAlert(res.message || `已刷新 ${res.synced} 个群`)
    }
  } catch (e) {
    await appAlert(`同步失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    syncing.value = false
  }
}

async function openWechatDrawer(contactId: number) {
  const hit = formattedFeed.value.find((r) => r.contactId === contactId)
  wechatDrawer.contactId = contactId
  wechatDrawer.title = hit?.name || '群聊记录'
  wechatDrawer.visible = true
  wechatDrawer.loading = true
  wechatDrawer.messages = []
  try {
    const res = await wechatGroupBridgeApi.getContactContext(contactId, { refresh: true })
    const raw = res?.messages ?? res?.data
    wechatDrawer.messages = Array.isArray(raw) ? raw : []
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    wechatDrawer.loading = false
  }
}

async function refresh() {
  await Promise.all([loadStats(), loadEnterpriseUsers(), loadWechatGroups(), loadPipelineFunnel()])
  await loadAllClientSummaries()
  if (expandedClientId.value) {
    await loadWechatSummary()
    await loadPipelineForCustomer()
  }
}

function goDataSources() {
  router.push({ name: 'data-sources', query: { source: 'wechat_local_db' } })
}

function goAdminEntitlements() {
  router.push({ name: 'admin-entitlements', query: { focus: 'wechat' } })
}

type MarketUserPickerRow = {
  id: number
  username: string
  email?: string
  is_enterprise?: boolean
  has_pipeline?: boolean
}

const addCustomerModal = reactive({
  visible: false,
  loading: false,
  filter: '',
  savingId: 0,
  marketUsers: [] as MarketUserPickerRow[],
  pipelineIds: new Set<number>(),
})

const addCustomerPickerRows = computed(() => {
  const q = addCustomerModal.filter.trim().toLowerCase()
  let rows = addCustomerModal.marketUsers
  if (q) {
    rows = rows.filter(
      (u) =>
        u.username.toLowerCase().includes(q) ||
        String(u.email || '')
          .toLowerCase()
          .includes(q) ||
        String(u.id).includes(q),
    )
  }
  return rows.slice(0, 80)
})

function isCustomerListed(userId: number) {
  return enterpriseUsers.value.some((u) => u.id === userId)
}

async function openAddCustomerModal() {
  addCustomerModal.visible = true
  addCustomerModal.loading = true
  addCustomerModal.filter = ''
  try {
    const [adminRes, clientsRes] = await Promise.all([
      xcmaxAdminApi.listUsers(),
      get<{ data?: { clients?: Array<{ market_user_id: number }> } }>(`${CS_BRIDGE}/user-cs/clients`),
    ])
    const data = adminRes as {
      users?: MarketUserPickerRow[]
      data?: { users?: MarketUserPickerRow[] }
    }
    const users = data.users || data.data?.users || []
    const pipelineIds = new Set(
      (clientsRes?.data?.clients || [])
        .map((c) => Number(c.market_user_id))
        .filter((id) => id > 0),
    )
    addCustomerModal.pipelineIds = pipelineIds
    addCustomerModal.marketUsers = users
      .map((u) => ({
        ...u,
        has_pipeline: pipelineIds.has(u.id),
      }))
      .sort((a, b) => {
        const aListed = isCustomerListed(a.id) ? 0 : 1
        const bListed = isCustomerListed(b.id) ? 0 : 1
        if (aListed !== bListed) return aListed - bListed
        return a.username.localeCompare(b.username, 'zh-CN')
      })
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
    addCustomerModal.visible = false
  } finally {
    addCustomerModal.loading = false
  }
}

async function markUserEnterprise(u: MarketUserPickerRow) {
  addCustomerModal.savingId = u.id
  try {
    await xcmaxAdminApi.setUserEnterprise(u.id, true)
    u.is_enterprise = true
    await loadEnterpriseUsers()
    await loadAllClientSummaries()
    expandedClientId.value = u.id
    await selectEnterprise(u.id)
    await loadPipelineForCustomer()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    addCustomerModal.savingId = 0
  }
}

function focusListedCustomer(userId: number) {
  addCustomerModal.visible = false
  expandedClientId.value = userId
  void selectEnterprise(userId)
  void loadPipelineForCustomer()
}

watch(currentStageId, (stage) => {
  if (stageRank(stage) >= stageRank('contract_pending')) void loadContractFields()
})

watch(
  () => currentStageId.value,
  (stage) => {
    if ((stage === 'intake' || stage === 'intake_done') && selectedUserId.value) {
      void loadIntakeFormLink()
      if (stage === 'intake') void loadIntakeNoticeMessage()
    }
  },
)

watch(intakeAuditCode, () => {
  auditCodeError.value = ''
  intakeAuditPreview.value = null
  intakeAuditPreviewCode.value = ''
  intakeAuditPreviewAt.value = ''
})

watch(
  () => route.query.market_user_id,
  () => {
    const id = parseMarketUserIdFromRoute()
    if (id != null) void toggleClient(id)
  },
)

onMounted(async () => {
  await refresh()
  const fromRoute = parseMarketUserIdFromRoute()
  if (fromRoute != null) await toggleClient(fromRoute)
})

onBeforeRouteLeave(async () => {
  if (stageDraftDirty.value) {
    const ok = await appConfirm('您有未保存的阶段变更，确定要离开吗？')
    if (!ok) return false
  }
  return true
})

onUnmounted(() => {
  stopPassiveLoopTimer()
})
</script>

<style scoped>
.cs-page { --cs-accent: #4a6cf7; --cs-border: #e8ecf2; --cs-bg: #f6f8fb; }
.page-content { max-width: 960px; margin: 0 auto; padding: 0 4px; }

.cs-topbar {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 0 20px; border-bottom: 1px solid var(--cs-border); margin-bottom: 20px;
}
.cs-topbar-left { display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; min-width: 0; }
.cs-topbar h2 { margin: 0; font-size: 18px; font-weight: 600; color: #1a1a2e; white-space: nowrap; }
.cs-metrics { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 13px; color: #64748b; }
.cs-metric em { font-style: normal; font-weight: 700; color: var(--cs-accent); font-size: 15px; margin-right: 2px; }
.cs-metric.muted em { color: #94a3b8; font-weight: 600; }
.cs-metric-sep { color: #cbd5e1; user-select: none; }
.cs-topbar-actions { display: flex; gap: 6px; flex-shrink: 0; }
.btn-ghost { background: transparent; border: 1px solid var(--cs-border); color: #64748b; }
.btn-ghost:hover { border-color: var(--cs-accent); color: var(--cs-accent); }

.cs-clients {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
  align-items: start;
}
.cs-card {
  background: #fff; border: 1px solid var(--cs-border); border-radius: 10px;
  overflow: hidden; transition: border-color 0.15s, box-shadow 0.15s;
}
.cs-card.is-open {
  grid-column: 1 / -1;
  border-color: #b8c9ff;
  box-shadow: 0 2px 16px rgba(74, 108, 247, 0.08);
}

.cs-card-head {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  width: 100%; min-height: 44px; padding: 10px 14px;
  border: none; background: none; cursor: pointer; text-align: center;
}
.cs-card-head:hover { background: #f8fafc; }
.cs-card.is-open .cs-card-head {
  justify-content: flex-start;
  border-bottom: 1px solid #f1f5f9;
}
.cs-card-name { font-size: 14px; font-weight: 600; color: #1e293b; }
.cs-card-stage { font-size: 12px; color: var(--cs-accent); font-weight: 400; margin-left: auto; }

.cs-card-body { padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 12px; }

.cs-progress-panel {
  background: linear-gradient(180deg, #f8faff 0%, #fff 100%);
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cs-progress-panel.has-unsaved-changes {
  border-color: #f59e0b;
  background: linear-gradient(180deg, #fffaf0 0%, #fff 100%);
  box-shadow: 0 0 0 1px #f59e0b inset;
}

.cs-progress-bar { margin-bottom: 2px; }
.cs-progress-track { height: 8px; background: #eef2f7; border-radius: 4px; overflow: hidden; margin-bottom: 10px; }
.cs-progress-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #4a6cf7); border-radius: 4px; transition: width 0.3s; }
.cs-progress-steps {
  display: flex; gap: 2px; list-style: none; margin: 0; padding: 0;
  overflow-x: auto; scrollbar-width: thin;
}
.cs-progress-step {
  flex: 1; min-width: 52px; display: flex; flex-direction: column; align-items: center; gap: 4px;
  text-align: center;
}
.cs-progress-dot {
  width: 22px; height: 22px; border-radius: 50%; font-size: 10px; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  background: #e2e8f0; color: #64748b; flex-shrink: 0;
}
.cs-progress-label { font-size: 10px; color: #94a3b8; line-height: 1.2; white-space: nowrap; }
.cs-progress-step.is-done .cs-progress-dot { background: #dcfce7; color: #16a34a; }
.cs-progress-step.is-done .cs-progress-label { color: #64748b; }
.cs-progress-step.is-current .cs-progress-dot {
  background: var(--cs-accent); color: #fff; box-shadow: 0 0 0 3px rgba(74,108,247,0.18);
}
.cs-progress-step.is-current .cs-progress-label { color: var(--cs-accent); font-weight: 600; }
.cs-progress-step.is-pick:not(.is-current) .cs-progress-dot {
  box-shadow: 0 0 0 2px rgba(74, 108, 247, 0.35);
}
.cs-progress-step[role='button'] { cursor: pointer; }
.cs-progress-step[role='button']:hover .cs-progress-label { color: #475569; }

.cs-stage-intro {
  background: #fff; border: 1px solid #e8ecf2; border-radius: 10px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.cs-stage-intro-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap;
}
.cs-enterprise-creds {
  padding: 12px 14px;
  border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.08));
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cs-enterprise-creds__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cs-enterprise-creds__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
}
.cs-enterprise-creds__dl {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 6px 12px;
  margin: 0;
  font-size: 13px;
}
.cs-enterprise-creds__dl dt {
  margin: 0;
  color: var(--text-muted, #8b949e);
}
.cs-enterprise-creds__dl dd {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cs-enterprise-creds__code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.25);
}
.cs-enterprise-creds__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.cs-audit-code-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 8px 12px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed rgba(148, 163, 184, 0.45);
}
.cs-audit-code-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1 1 160px;
  min-width: 140px;
}
.cs-audit-code-input {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 0.04em;
}
.cs-audit-code-error {
  margin: 4px 0 0;
  width: 100%;
}
.cs-audit-preview {
  margin-top: 10px;
}
.cs-audit-preview-hint {
  margin: 8px 0 0;
  font-size: 12px;
}
.cs-stage-intake-quick {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.cs-stage-intro-actions {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.cs-stage-edit {
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
}
.cs-stage-select {
  font-size: 12px; padding: 4px 8px; border-radius: 6px; border: 1px solid #e2e8f0;
  max-width: 120px;
}
.cs-stage-edit-hint { margin: 0; font-size: 11px; line-height: 1.45; }
.cs-auto-advance-hint { margin: 8px 0 0; font-size: 12px; color: var(--cs-accent); }
.cs-stage-intro-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cs-stage-intro-title strong { font-size: 15px; color: #1e293b; }
.cs-stage-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  background: #eff6ff; color: var(--cs-accent); font-weight: 500;
}
.cs-stage-viewing-from { font-size: 12px; font-weight: 400; }
.cs-stage-lead { margin: 0; font-size: 13px; font-weight: 500; color: #334155; }
.cs-stage-desc { margin: 0; font-size: 12px; color: #64748b; line-height: 1.55; }
.cs-stage-hint { margin: 0; font-size: 12px; color: #475569; line-height: 1.5; }
.cs-stage-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.cs-stage-done-hint { margin: 0; font-size: 12px; color: #16a34a; }
.cs-stage-warn-hint { color: #b45309; }
.cs-intake-done-actions { flex-wrap: wrap; gap: 6px; }
.cs-crm-panel {
  margin: 10px 0 0; padding: 10px 12px; border-radius: 8px;
  background: #f8fafc; border: 1px solid #e2e8f0;
}
.cs-crm-panel__title { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: #334155; }
.cs-crm-panel__dl {
  margin: 0 0 8px; display: grid; grid-template-columns: 5.5em 1fr; gap: 4px 10px; font-size: 12px;
}
.cs-crm-panel__dl dt { color: #64748b; margin: 0; }
.cs-crm-panel__dl dd { margin: 0; color: #1e293b; }
.cs-finance-panel { margin-top: 10px; }
.cs-funnel-bar {
  margin: 0 0 12px; padding: 10px 12px; background: #fff; border: 1px solid #e8ecf2; border-radius: 10px;
}
.cs-funnel-toggle {
  display: flex; align-items: center; gap: 8px; width: 100%; border: none; background: transparent;
  font-size: 14px; font-weight: 600; color: #1e293b; cursor: pointer; padding: 0;
}
.cs-funnel-stages {
  display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px;
}
.cs-funnel-stage {
  display: flex; flex-direction: column; align-items: center; min-width: 72px; padding: 6px 8px;
  border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; cursor: pointer; font-size: 11px;
}
.cs-funnel-stage.active { border-color: var(--cs-accent); background: #eff6ff; }
.cs-funnel-stage__count { font-size: 15px; font-weight: 700; color: #334155; }
.cs-funnel-stage__label { color: #64748b; margin-top: 2px; text-align: center; line-height: 1.2; }
.cs-funnel-filter-hint { margin: 8px 0 0; font-size: 12px; }
.cs-external-crm { margin-top: 10px; padding-top: 10px; border-top: 1px dashed #e2e8f0; }
.cs-external-crm__title { margin: 0 0 4px; font-size: 11px; }
.cs-external-crm__hint { margin: 0 0 8px; font-size: 12px; line-height: 1.45; }
.cs-external-crm__meta { margin: 0 0 6px; font-size: 12px; }
.cs-external-crm__meta code { font-size: 11px; }
.cs-external-crm__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.cs-esign-panel-wrap {
  margin-top: 12px;
}
.cs-esign-panel {
  margin-top: 12px; padding-top: 12px; border-top: 1px dashed #e2e8f0;
}
.cs-ops-job { font-size: 11px; margin-left: 6px; }
.cs-finance-table {
  width: 100%;
  font-size: 11px;
  border-collapse: collapse;
  margin-top: 6px;
}
.cs-finance-table th,
.cs-finance-table td {
  border: 1px solid #e2e8f0;
  padding: 4px 6px;
  text-align: left;
}
.cs-crm-quote-sum { display: block; margin-top: 2px; color: #475569; }
.cs-delivery-grid {
  display: grid; grid-template-columns: 1fr auto; gap: 8px 12px; margin-bottom: 8px;
}
.cs-delivery-pct { font-weight: 600; color: var(--cs-accent, #4a6cf7); }
.cs-delivery-progress-track {
  height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; margin-bottom: 10px;
}
.cs-delivery-progress-fill {
  height: 100%; background: linear-gradient(90deg, #22c55e, #4a6cf7); transition: width 0.25s;
}
.cs-milestone-list { list-style: none; margin: 0 0 10px; padding: 0; }
.cs-milestone-item { font-size: 12px; padding: 4px 0; }
.cs-milestone-item label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.cs-stage-checklist {
  list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px;
}
.cs-stage-checklist li {
  display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: #64748b; line-height: 1.45;
}
.cs-stage-checklist li.is-done { color: #16a34a; }
.cs-check-mark { width: 14px; flex-shrink: 0; text-align: center; font-size: 11px; }
.cs-analyze-btn { flex-shrink: 0; }

.cs-stage-roadmap { font-size: 12px; }
.cs-stage-roadmap summary {
  cursor: pointer; color: var(--cs-accent); font-weight: 500; padding: 4px 0;
  list-style: none;
}
.cs-stage-roadmap summary::-webkit-details-marker { display: none; }
.cs-stage-roadmap summary::before { content: '▸ '; }
.cs-stage-roadmap[open] summary::before { content: '▾ '; }
.cs-roadmap-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px;
}
@media (max-width: 900px) { .cs-roadmap-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 560px) { .cs-roadmap-grid { grid-template-columns: 1fr; } }
.cs-roadmap-item {
  background: #fff; border: 1px solid #e8ecf2; border-radius: 8px; padding: 10px;
}
.cs-roadmap-item.is-current { border-color: #93c5fd; background: #f8fbff; }
.cs-roadmap-item.is-done { border-color: #bbf7d0; }
.cs-roadmap-title { margin: 0 0 4px; font-size: 12px; font-weight: 600; color: #334155; }
.cs-roadmap-headline { margin: 0 0 6px; font-size: 11px; color: #64748b; line-height: 1.4; }
.cs-roadmap-todos {
  margin: 0; padding-left: 16px; color: #94a3b8; font-size: 11px; line-height: 1.45;
}
.cs-roadmap-todos li { margin-bottom: 2px; }
.cs-coming-soon-inline {
  background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 8px 10px;
}
.cs-stage-group-tip {
  margin: 8px 0 0;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.45;
  color: #1e40af;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
}
.cs-stage-actions--quote {
  margin-top: 8px;
}
.cs-stage-pending-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: #b45309;
}
.btn.btn-xs.btn-accent.is-pending {
  box-shadow: 0 0 0 2px rgba(74, 108, 247, 0.35);
}

.cs-wechat-split {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
}
@media (max-width: 720px) { .cs-wechat-split { grid-template-columns: 1fr; } }

.cs-block {
  background: #f8fafc; border: 1px solid #e8ecf2; border-radius: 10px; padding: 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.cs-block-biz { background: #fff; }
.cs-block-hint { background: #fffbeb; border-color: #fde68a; }
.cs-block-title { margin: 0; font-size: 13px; font-weight: 600; color: #334155; }
.cs-block-desc { margin: 0; font-size: 12px; color: #64748b; line-height: 1.5; }
.cs-block-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.cs-passive-loop-row {
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
  margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--cs-border);
}
.cs-passive-loop-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; cursor: pointer; }
.cs-passive-loop-interval { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.cs-passive-loop-interval select { font-size: 12px; padding: 2px 6px; }
.cs-passive-loop-last { font-size: 11px; }
.cs-passive-loop-summary { font-size: 11px; color: var(--cs-accent); }
.cs-passive-llm-status { font-size: 11px; display: block; margin-top: 4px; }
.cs-passive-loop-hint { font-size: 11px; margin: 6px 0 0; line-height: 1.45; }
.cs-block-empty { text-align: center; padding: 8px 0; }

.cs-send-compose { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; padding-top: 8px; border-top: 1px dashed #e2e8f0; }
.cs-send-target { margin: 0; font-size: 11px; color: #64748b; }
.cs-send-error { margin: 0; font-size: 11px; color: #dc2626; }

.cs-coming-soon {
  font-size: 12px; color: #b45309; margin: 0;
}
.cs-contract-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px;
}
@media (max-width: 640px) { .cs-contract-grid { grid-template-columns: 1fr; } }
.cs-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #64748b; }
.cs-field-wide { grid-column: 1 / -1; }
.cs-contract-file { font-size: 12px; color: #16a34a; margin: 0; }

.btn-xs { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid var(--cs-border); background: #fff; cursor: pointer; }
.btn-xs:hover { border-color: #cbd5e1; }
.btn-accent { background: var(--cs-accent); border-color: var(--cs-accent); color: #fff; }
.btn-accent:hover { opacity: 0.92; }
.btn-accent:disabled { opacity: 0.5; cursor: not-allowed; }

.cs-input {
  width: 100%; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px;
  font-size: 13px; box-sizing: border-box; background: #fff;
}
.cs-group-list-hint { font-size: 11px; margin: 6px 0 4px; }
.cs-group-list { max-height: 220px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.cs-group-item { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; padding: 4px 0; }
.cs-feed { list-style: none; margin: 0; padding: 0; }
.cs-feed.compact .cs-feed-item { grid-template-columns: 1fr auto; }
.cs-feed-item {
  display: grid; grid-template-columns: 1fr 2fr auto; gap: 8px; padding: 8px 10px;
  border-radius: 8px; font-size: 12px; cursor: pointer; background: #fff; margin-bottom: 4px;
}
.cs-feed-item:hover { background: #eff6ff; }
.cs-feed-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cs-feed-text { color: #64748b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cs-feed-time { color: #94a3b8; font-size: 11px; white-space: nowrap; }
.cs-preview {
  font-size: 12px; line-height: 1.55; padding: 10px; background: #fff; border-radius: 8px;
  border: 1px solid #e2e8f0; white-space: pre-wrap; max-height: 160px; overflow: auto; margin: 0;
}
.cs-intake-summary {
  margin-top: 10px; padding: 10px 12px; border-radius: 8px;
  background: #f0fdf4; border: 1px solid #bbf7d0;
}
.cs-intake-summary__title { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: #166534; }
.cs-intake-summary__time { font-weight: 400; color: #64748b; margin-left: 6px; }
.cs-intake-summary__dl {
  margin: 0; display: grid; grid-template-columns: 4.5em 1fr; gap: 4px 10px; font-size: 12px;
}
.cs-intake-summary__dl dt { color: #64748b; margin: 0; }
.cs-intake-summary__dl dd { margin: 0; color: #1e293b; white-space: pre-wrap; }
.cs-change-requests { margin-top: 12px; border-top: 1px dashed #e2e8f0; padding-top: 12px; }
.cs-change-request-list { list-style: none; margin: 0; padding: 0; }
.cs-change-request-item {
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
}
.cs-change-request-item:last-child { border-bottom: none; }
.cs-change-request-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 4px; }
.cs-change-request-title { margin: 0 0 4px; font-size: 13px; font-weight: 500; }
.cs-change-request-desc { margin: 0 0 8px; font-size: 12px; }
.input-xs { font-size: 12px; padding: 4px 6px; border-radius: 4px; border: 1px solid #ddd; }
.cs-empty { text-align: center; padding: 48px 16px; color: #94a3b8; }
.loading-hint, .empty-hint { font-size: 12px; color: #94a3b8; margin: 0; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal-content { background: #fff; border-radius: 12px; width: 560px; max-width: 92vw; box-shadow: 0 8px 32px rgba(0,0,0,0.12); }
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #eee; }
.modal-header h3 { margin: 0; font-size: 15px; }
.modal-close { background: none; border: none; font-size: 20px; cursor: pointer; color: #999; }
.modal-body { padding: 16px 18px; }
.cs-drawer-body { max-height: 60vh; overflow-y: auto; }
.cs-add-customer-modal { width: 480px; }
.cs-add-customer-hint { font-size: 12px; line-height: 1.5; margin: 0 0 12px; }
.cs-add-customer-list { list-style: none; margin: 12px 0 0; padding: 0; max-height: 50vh; overflow-y: auto; }
.cs-add-customer-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.cs-add-customer-row__main { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; min-width: 0; }
.cs-add-customer-row.is-listed { background: #f8fbff; margin: 0 -8px; padding-left: 8px; padding-right: 8px; }
.cs-card-badge { font-size: 10px; color: #b45309; background: #fff7ed; padding: 1px 6px; border-radius: 4px; margin-left: 6px; }
.cs-tag { font-size: 10px; padding: 1px 6px; border-radius: 4px; background: #f3f4f6; color: #6b7280; }
.cs-tag--ok { background: #ecfdf5; color: #047857; }
.btn-link { background: none; border: none; color: var(--color-primary, #2563eb); cursor: pointer; padding: 0; font-size: inherit; text-decoration: underline; }
.cs-chat-msg { margin-bottom: 8px; padding: 8px; background: #f8fafc; border-radius: 8px; }
.cs-chat-role { font-size: 11px; color: #94a3b8; margin-bottom: 2px; }
.cs-chat-sender-id { margin-left: 6px; font-size: 10px; color: #cbd5e1; }
.cs-chat-text { font-size: 13px; word-break: break-word; white-space: pre-wrap; }
</style>
