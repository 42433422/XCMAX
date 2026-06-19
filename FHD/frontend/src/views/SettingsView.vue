<template>
  <div class="page-view settings-page" id="view-settings">
    <div class="page-content settings-page__scroll">
      <div class="settings-layout">
        <aside class="settings-profile" :aria-label="$t('settings.profileAria')">
          <button
            type="button"
            class="settings-profile__avatar"
            :class="{ 'is-guest': !isLoggedIn, 'is-loading': accountLoading || avatarUploading }"
            :disabled="!isLoggedIn || accountLoading || avatarUploading"
            :title="isLoggedIn ? $t('settings.changeAvatar') : $t('settings.avatarAfterLogin')"
            @click="onAvatarClick"
          >
            <img
              v-if="profileAvatarUrl"
              :src="profileAvatarUrl"
              alt=""
              class="settings-profile__avatar-img"
            >
            <span v-else-if="avatarInitial" class="settings-profile__avatar-letter">{{ avatarInitial }}</span>
            <i v-else class="fa fa-user" aria-hidden="true"></i>
            <span v-if="isLoggedIn" class="settings-profile__avatar-hint">{{ $t('settings.changeAvatarShort') }}</span>
          </button>
          <input
            ref="avatarInputRef"
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            class="settings-profile__avatar-input"
            tabindex="-1"
            aria-hidden="true"
            @change="onAvatarFileChange"
          >
          <p class="settings-profile__name settings-profile__brand">{{ profileBrandTitle }}</p>
          <p class="settings-profile__sub">{{ profileSubline }}</p>
          <div class="settings-profile__actions">
            <button
              v-if="isLoggedIn"
              type="button"
              class="settings-profile__btn settings-profile__btn--ghost"
              :disabled="logoutLoading"
              @click="onLogout"
            >
              {{ logoutLoading ? $t('settings.loggingOut') : $t('settings.logout') }}
            </button>
            <router-link
              v-else
              class="settings-profile__btn settings-profile__btn--primary"
              :to="loginRoute"
            >
              {{ $t('settings.login') }}
            </router-link>
          </div>
        </aside>

        <div class="settings-layout__main">
        <header class="settings-page__hero">
          <h1 class="settings-page__title">{{ $t('settings.pageTitle') }}</h1>
        </header>

        <div class="settings-list">
        <details
          v-if="isLoggedIn"
          id="settings-profile-home"
          class="settings-card"
          data-tutorial-id="settings-profile-home"
          open
        >
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--indigo" aria-hidden="true">
              <i class="fa fa-id-card"></i>
            </span>
            <span class="settings-row__label">{{ $t('settings.profileHome') }}</span>
            <span class="settings-row__meta">{{ profileHomeSummary }}</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>
          <div class="settings-card__body settings-card__body--list">
            <div class="settings-profile-form">
              <div class="settings-profile-form__editable">
                <label class="settings-profile-form__field">
                  <span class="settings-profile-form__label">{{ $t('settings.displayName') }}</span>
                  <input
                    v-model="profileDisplayNameDraft"
                    class="settings-profile-form__input"
                    type="text"
                    maxlength="64"
                    :placeholder="$t('settings.displayNamePlaceholder')"
                    autocomplete="name"
                  >
                </label>
                <label class="settings-profile-form__field">
                  <span class="settings-profile-form__label">{{ $t('settings.email') }}</span>
                  <input
                    v-model="profileEmailDraft"
                    class="settings-profile-form__input"
                    type="email"
                    maxlength="128"
                    :placeholder="$t('settings.emailPlaceholder')"
                    autocomplete="email"
                  >
                </label>
              </div>
              <div class="settings-profile-form__readonly" aria-readonly="true">
                <span class="settings-profile-form__label">{{ $t('settings.loginName') }}</span>
                <span class="settings-profile-form__readonly-value">{{
                  localUser?.username || '—'
                }}</span>
                <p class="settings-profile-form__hint muted">
                  {{ $t('settings.loginNameHint') }}
                </p>
              </div>
              <div class="settings-profile-form__actions">
                <button
                  type="button"
                  class="settings-profile-form__submit"
                  :disabled="!profileFormDirty || profileSaving"
                  @click="saveProfile"
                >
                  {{ profileSaving ? $t('settings.saving') : $t('settings.saveProfile') }}
                </button>
              </div>
            </div>
          </div>
        </details>

        <details
          id="settings-model-payment"
          class="settings-card"
          data-tutorial-id="settings-model-payment"
          open
        >
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--blue" aria-hidden="true">
              <i class="fa fa-credit-card"></i>
            </span>
            <span class="settings-row__label">{{ $t('settings.modelService') }}</span>
            <span class="settings-row__meta">{{ $t('settings.modelServiceMeta') }}</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>
          <div class="settings-card__body settings-card__body--flush">
            <HostModBridgeView
              v-if="isAdminConsole || modelPaymentBridgeInstalled"
              embedded
              mod-id="xcagi-model-payment-bridge"
              view="ModelPaymentView"
              title="模型服务"
            />
            <div v-else class="settings-model-service-empty">
              <p class="settings-model-service-empty__title">{{ $t('settings.modelServiceMissingTitle') }}</p>
              <p class="muted settings-model-service-empty__lead">{{ $t('settings.modelServiceMissingLead') }}</p>
              <ul class="settings-model-service-empty__list muted">
                <li>{{ $t('settings.modelServiceMissingWhy') }}</li>
                <li>{{ $t('settings.modelServiceMissingHow') }}</li>
                <li>{{ $t('settings.modelServiceMissingNote') }}</li>
              </ul>
              <div class="settings-model-service-empty__actions">
                <router-link class="btn btn-sm btn-primary" :to="{ name: 'mod-store' }">
                  {{ $t('settings.modelServiceOpenModStore') }}
                </router-link>
                <button type="button" class="btn btn-sm btn-secondary" @click="openSettingsExtensions">
                  {{ $t('settings.modelServiceOpenExtensions') }}
                </button>
              </div>
            </div>
          </div>
        </details>

        <details
          v-if="isLoggedIn && isLocalAdmin"
          class="settings-card"
          data-tutorial-id="settings-audit-logs"
        >
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--amber" aria-hidden="true">
              <i class="fa fa-shield"></i>
            </span>
            <span class="settings-row__label">安全审计</span>
            <span class="settings-row__meta">{{ auditLogsTotal }} 条</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>
          <div class="settings-card__body settings-card__body--list">
            <p v-if="auditLogsLoading" class="muted" style="padding: 12px 16px; margin: 0;">加载中…</p>
            <p v-else-if="auditLogsError" class="settings-profile-form__hint" role="alert" style="padding: 12px 16px;">
              {{ auditLogsError }}
            </p>
            <ul v-else-if="auditLogs.length" class="settings-audit-list">
              <li v-for="(row, idx) in auditLogs" :key="idx" class="settings-audit-list__item">
                <span class="settings-audit-list__action">{{ row.action || '—' }}</span>
                <span class="settings-audit-list__meta">
                  {{ row.timestamp || row.ts || '' }}
                  · {{ row.user_id ?? '—' }}
                  · {{ row.success === false ? '失败' : '成功' }}
                </span>
              </li>
            </ul>
            <p v-else class="muted" style="padding: 12px 16px; margin: 0;">暂无审计记录（可配置 AUDIT_LOG_PATH）</p>
            <div class="settings-profile-form__actions" style="padding: 0 16px 16px;">
              <button type="button" class="settings-profile-form__submit" @click="loadAuditLogs">
                刷新
              </button>
              <button type="button" class="settings-profile-form__submit settings-profile-form__submit--ghost" @click="downloadAuditCsv">
                导出 CSV
              </button>
            </div>
          </div>
        </details>

        <details
          class="settings-card"
          data-tutorial-id="settings-intent"
          open
        >
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--purple" aria-hidden="true">
              <i class="fa fa-magic"></i>
            </span>
            <span class="settings-row__label">AI 意图能力</span>
            <span v-if="currentIntentIndustryLabel" class="settings-row__pill" @click.stop>
              {{ currentIntentIndustryLabel }}
              <template v-if="currentIndustryUnit"> · {{ currentIndustryUnit }}</template>
            </span>
            <span v-else class="settings-row__meta">只读展示</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>

          <div class="settings-card__body">
        <div v-if="!currentIndustryConfig" class="intent-showcase-state muted">当前行业未加载，请刷新或检查后端行业配置</div>
        <div v-else class="intent-showcase-grid">
          <article
            v-for="entry in intentPackageEntries"
            :key="entry.key"
            class="intent-showcase-tile"
            :class="{ 'is-enabled': entry.enabled, 'is-disabled': !entry.enabled }"
          >
            <div class="intent-tile-top">
              <span class="intent-tile-icon" aria-hidden="true">
                <i class="fa" :class="entry.iconClass"></i>
              </span>
              <div class="intent-tile-title-wrap">
                <h3 class="intent-tile-title">{{ entry.name }}</h3>
                <span
                  class="intent-tile-status"
                  :class="entry.enabled ? 'intent-tile-status--on' : 'intent-tile-status--off'"
                >
                  {{ entry.enabled ? '已接入' : '未接入' }}
                </span>
              </div>
            </div>
            <p class="intent-tile-desc">{{ entry.description }}</p>
            <div class="intent-tile-keywords">
              <span
                v-for="kw in entry.keywords"
                :key="`${entry.key}-${kw}`"
                class="intent-chip"
              >{{ kw }}</span>
              <span v-if="!entry.keywords.length" class="intent-chip intent-chip--empty">暂无示例词</span>
            </div>
          </article>
        </div>
          </div>
        </details>

        <details
          class="settings-card"
          data-tutorial-id="settings-memory-v2"
          open
        >
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--blue" aria-hidden="true">
              <i class="fa fa-bookmark"></i>
            </span>
            <span class="settings-row__label">Memory v2</span>
            <span class="settings-row__meta">{{ memoryV2FoldMeta }}</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>

          <div class="settings-card__body settings-card__body--compact">
            <div class="memory-v2-toolbar">
              <select
                v-model="memoryV2StatusFilter"
                class="settings-item__control settings-item__control--select memory-v2-select"
                :disabled="memoryV2Loading"
                @change="loadMemoryV2"
              >
                <option
                  v-for="item in MEMORY_V2_STATUS_FILTERS"
                  :key="item.value"
                  :value="item.value"
                >
                  {{ item.label }}
                </option>
              </select>
              <select
                v-model="memoryV2TypeFilter"
                class="settings-item__control settings-item__control--select memory-v2-select"
                :disabled="memoryV2Loading"
                @change="loadMemoryV2"
              >
                <option value="all">全部类型</option>
                <option
                  v-for="item in MEMORY_V2_TYPE_OPTIONS"
                  :key="item.value"
                  :value="item.value"
                >
                  {{ item.label }}
                </option>
              </select>
              <button
                type="button"
                class="btn btn-sm btn-secondary"
                :disabled="memoryV2Loading"
                @click="loadMemoryV2"
              >
                刷新
              </button>
            </div>

            <p v-if="memoryV2Error" class="memory-v2-error" role="alert">{{ memoryV2Error }}</p>

            <form class="memory-v2-form" @submit.prevent="createMemoryV2Candidate">
              <select
                v-model="memoryV2Draft.memoryType"
                class="settings-item__control settings-item__control--select memory-v2-form__type"
                :disabled="memoryV2Creating"
              >
                <option
                  v-for="item in MEMORY_V2_TYPE_OPTIONS"
                  :key="item.value"
                  :value="item.value"
                >
                  {{ item.label }}
                </option>
              </select>
              <input
                v-model="memoryV2Draft.key"
                class="settings-item__control settings-item__control--text memory-v2-form__input"
                type="text"
                maxlength="64"
                placeholder="key"
                :disabled="memoryV2Creating"
              >
              <input
                v-model="memoryV2Draft.value"
                class="settings-item__control settings-item__control--text memory-v2-form__input"
                type="text"
                maxlength="240"
                placeholder="value"
                :disabled="memoryV2Creating"
              >
              <input
                v-model.number="memoryV2Draft.confidence"
                class="settings-item__control settings-item__control--text memory-v2-form__confidence"
                type="number"
                min="0"
                max="1"
                step="0.05"
                :disabled="memoryV2Creating"
              >
              <button
                type="submit"
                class="btn btn-sm btn-primary"
                :disabled="memoryV2Creating"
              >
                {{ memoryV2Creating ? '写入中…' : '写入候选' }}
              </button>
            </form>

            <pre v-if="memoryV2PlannerContext" class="memory-v2-context">{{ memoryV2PlannerContext }}</pre>

            <p v-if="memoryV2Loading" class="memory-v2-state muted">加载中…</p>
            <ul v-else-if="memoryV2Records.length" class="memory-v2-list">
              <li
                v-for="record in memoryV2Records"
                :key="record.memory_id"
                class="memory-v2-item"
              >
                <div class="memory-v2-item__head">
                  <span class="memory-v2-chip">{{ memoryV2TypeLabel(record.memory_type) }}</span>
                  <span class="memory-v2-chip" :class="`memory-v2-chip--${record.status}`">
                    {{ memoryV2StatusLabel(record.status) }}
                  </span>
                  <span class="memory-v2-item__time">{{ memoryV2Time(record.updated_at || record.created_at) }}</span>
                </div>

                <div v-if="memoryV2Edit.memoryId === record.memory_id" class="memory-v2-edit">
                  <input
                    v-model="memoryV2Edit.key"
                    class="settings-item__control settings-item__control--text memory-v2-edit__input"
                    type="text"
                    maxlength="64"
                    :disabled="memoryV2BusyId === record.memory_id"
                  >
                  <textarea
                    v-model="memoryV2Edit.value"
                    class="memory-v2-edit__textarea"
                    rows="3"
                    :disabled="memoryV2BusyId === record.memory_id"
                  ></textarea>
                </div>
                <div v-else class="memory-v2-item__body">
                  <strong class="memory-v2-item__key">{{ record.key }}</strong>
                  <span class="memory-v2-item__value">{{ memoryV2DisplayValue(record.value) }}</span>
                </div>

                <div class="memory-v2-item__meta">
                  <span>{{ record.source || 'unknown' }}</span>
                  <span>confidence {{ Number(record.confidence || 0).toFixed(2) }}</span>
                </div>

                <div class="memory-v2-actions">
                  <template v-if="memoryV2Edit.memoryId === record.memory_id">
                    <button
                      type="button"
                      class="btn btn-sm btn-primary"
                      :disabled="memoryV2BusyId === record.memory_id"
                      @click="saveMemoryV2Edit(record)"
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-secondary"
                      :disabled="memoryV2BusyId === record.memory_id"
                      @click="cancelMemoryV2Edit"
                    >
                      取消
                    </button>
                  </template>
                  <template v-else>
                    <button
                      v-if="record.status === 'pending'"
                      type="button"
                      class="btn btn-sm btn-primary"
                      :disabled="memoryV2BusyId === record.memory_id"
                      @click="confirmMemoryV2(record)"
                    >
                      确认
                    </button>
                    <button
                      v-if="record.status === 'pending'"
                      type="button"
                      class="btn btn-sm btn-secondary"
                      :disabled="memoryV2BusyId === record.memory_id"
                      @click="rejectMemoryV2(record)"
                    >
                      拒绝
                    </button>
                    <button
                      v-if="canEditMemoryV2(record)"
                      type="button"
                      class="btn btn-sm btn-secondary"
                      :disabled="memoryV2BusyId === record.memory_id"
                      @click="startMemoryV2Edit(record)"
                    >
                      修正
                    </button>
                    <button
                      v-if="record.status !== 'deleted'"
                      type="button"
                      class="btn btn-sm btn-danger"
                      :disabled="memoryV2BusyId === record.memory_id"
                      @click="deleteMemoryV2(record)"
                    >
                      删除
                    </button>
                  </template>
                </div>
              </li>
            </ul>
            <p v-else class="memory-v2-state muted">暂无记忆</p>
          </div>
        </details>

        <details
          class="settings-card"
          data-tutorial-id="settings-basic"
          open
        >
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--green" aria-hidden="true">
              <i class="fa fa-sliders"></i>
            </span>
            <span class="settings-row__label">{{ $t('settings.basicSettings') }}</span>
            <span class="settings-row__meta">{{ basicSettingsSummary }}</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>

          <div class="settings-card__body settings-card__body--list">
        <div class="settings-item-list">
          <div class="settings-item">
            <span class="settings-item__icon settings-row__icon--cyan" aria-hidden="true">
              <i class="fa fa-columns"></i>
            </span>
            <label class="settings-item__label" for="settings-sidebar-theme">{{ $t('settings.sidebarTheme') }}</label>
            <select
              id="settings-sidebar-theme"
              v-model="sidebarThemePreset"
              class="settings-item__control settings-item__control--select"
              @change="onSidebarThemeChange"
            >
              <option v-for="theme in SIDEBAR_THEME_OPTIONS" :key="theme.value" :value="theme.value">
                {{ theme.label }}
              </option>
            </select>
          </div>

          <div v-if="showCompanyBrandEditor" class="settings-item">
            <span class="settings-item__icon settings-row__icon--amber" aria-hidden="true">
              <i class="fa fa-building"></i>
            </span>
            <label class="settings-item__label" for="settings-company-brand">企业品牌名</label>
            <div class="settings-item__control-group">
              <input
                id="settings-company-brand"
                v-model="companyBrandDraft"
                class="settings-item__control settings-item__control--text"
                type="text"
                maxlength="64"
                placeholder="对外展示的企业名称"
              >
              <button
                type="button"
                class="settings-item__save-btn"
                :disabled="companyBrandSaving || !companyBrandDirty"
                @click="saveCompanyBrand"
              >
                {{ companyBrandSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>

          <div class="settings-item">
            <span class="settings-item__icon settings-row__icon--indigo" aria-hidden="true">
              <i class="fa fa-user-circle"></i>
            </span>
            <label class="settings-item__label" for="settings-assistant-name">{{ $t('settings.assistantName') }}</label>
            <input
              id="settings-assistant-name"
              v-model="assistantName"
              class="settings-item__control settings-item__control--text"
              type="text"
              maxlength="24"
              :placeholder="$t('settings.assistantNamePlaceholder')"
            >
          </div>

          <div class="settings-item">
            <span class="settings-item__icon settings-row__icon--indigo" aria-hidden="true">
              <i class="fa fa-language"></i>
            </span>
            <label class="settings-item__label" for="settings-locale">{{ $t('settings.language') }}</label>
            <select
              id="settings-locale"
              v-model="appLocale"
              class="settings-item__control settings-item__control--select"
              @change="onLocaleChange"
            >
              <option value="zh-CN">{{ $t('settings.localeZhCN') }}</option>
              <option value="en-US">{{ $t('settings.localeEnUS') }}</option>
            </select>
          </div>

          <div class="settings-item settings-item--readonly">
            <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
              <i class="fa fa-desktop"></i>
            </span>
            <span class="settings-item__label">{{ $t('settings.systemName') }}</span>
            <span class="settings-item__value">{{ systemDisplayName }}</span>
          </div>

          <div v-if="desktopDatabaseVisible" class="settings-item settings-item--readonly">
            <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
              <i class="fa fa-database"></i>
            </span>
            <span class="settings-item__label">数据存储</span>
            <span class="settings-item__value">{{ databaseStorageLabel }}</span>
          </div>

          <div v-if="desktopDatabaseVisible" class="settings-item settings-item--readonly">
            <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
              <i class="fa fa-folder-open-o"></i>
            </span>
            <span class="settings-item__label">数据库路径</span>
            <span class="settings-item__value settings-item__value--mono" :title="currentDbPath">{{ currentDbPath }}</span>
          </div>

          <div class="settings-item">
            <span class="settings-item__icon settings-row__icon--violet" aria-hidden="true">
              <i class="fa fa-cloud"></i>
            </span>
            <label class="settings-item__label" for="settings-ai-mode">{{ $t('settings.aiMode') }}</label>
            <select
              id="settings-ai-mode"
              v-model="aiMode"
              class="settings-item__control settings-item__control--select"
            >
              <option value="online">{{ $t('settings.aiModeOnline') }}</option>
              <option value="offline">{{ $t('settings.aiModeOffline') }}</option>
            </select>
          </div>
        </div>

        <details
          class="settings-card settings-card--nested"
          data-tutorial-id="settings-mobile-pairing"
          open
        >
          <summary class="settings-row settings-row--nested">
            <span class="settings-row__icon settings-row__icon--cyan" aria-hidden="true">
              <i class="fa fa-qrcode"></i>
            </span>
            <span class="settings-row__label">移动端连接</span>
            <span class="settings-row__meta">App 扫码配对</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>
          <div class="settings-card__body settings-card__body--nested">
            <MobilePairingQrCard />
          </div>
        </details>

        <details
          v-if="!clientModsUiOff"
          class="settings-card settings-card--nested"
          data-tutorial-id="settings-extensions"
        >
          <summary class="settings-row settings-row--nested">
            <span class="settings-row__icon settings-row__icon--orange" aria-hidden="true">
              <i class="fa fa-puzzle-piece"></i>
            </span>
            <span class="settings-row__label">扩展与 Mod</span>
            <span class="settings-row__meta">{{ modSettingsFoldMeta }}</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>
          <div class="settings-card__body settings-card__body--nested">
            <p v-if="modRoutesStatusText" class="muted mod-routes-status text-warning">
              {{ modRoutesStatusText }}
            </p>
            <button
              v-if="showModRoutesRetry"
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="modRoutesRetrying"
              @click="retryModRoutesLoad"
            >
              {{ modRoutesRetrying ? '重试中…' : '重试加载 Mod 与路由' }}
            </button>

            <section v-if="hostBridgeMods.length" class="mod-fold-section">
              <div class="mod-fold-section-head">
                <span class="mod-ui-off-label">宿主基础能力包</span>
                <span class="mod-host-pack-stat">
                  {{ hostBridgeInstalledCount }}/{{ hostBridgeExpectedCount }} 已就绪
                </span>
              </div>
              <div class="mod-host-pack-bar">
                <button type="button" class="btn btn-secondary btn-sm" @click="hostPackExpanded = !hostPackExpanded">
                  {{ hostPackExpanded ? '收起' : '清单' }}
                </button>
                <button type="button" class="btn btn-link btn-sm" @click="goHostPackOnboarding">一键装齐</button>
              </div>
              <ul v-if="hostPackExpanded" class="mod-host-pack-list">
                <li v-for="mod in hostBridgeMods" :key="mod.id" class="mod-host-pack-row">
                  <span class="mod-host-pack-name">{{ mod.name || mod.id }}</span>
                  <button
                    type="button"
                    class="btn btn-danger btn-sm mod-single-uninstall"
                    :disabled="uninstallingModId === mod.id || isProtectedClientModId(mod.id)"
                    @click="onUninstallMod(mod.id)"
                  >
                    {{ uninstallingModId === mod.id ? '卸载中…' : '卸载' }}
                  </button>
                </li>
              </ul>
            </section>

            <section v-if="workflowEmployeeMods.length" class="mod-fold-section mod-fold-section--inline">
              <span class="mod-ui-off-label">工作流员工</span>
              <span class="muted">共 {{ workflowEmployeeMods.length }} 个 ·</span>
              <button type="button" class="btn btn-link btn-sm" @click="goModStore">扩展市场</button>
            </section>

            <section class="mod-fold-section">
              <div class="mod-fold-section-head">
                <span class="mod-ui-off-label">行业扩展包</span>
                <button type="button" class="btn btn-link btn-sm" @click="goModStore">扩展市场</button>
              </div>
              <div v-if="selectableExtensionMods.length" class="mod-single-list">
                <div
                  v-for="mod in selectableExtensionMods"
                  :key="mod.id"
                  class="mod-single-item"
                  :class="{ active: activeModId === mod.id }"
                >
                  <label class="mod-single-main">
                    <input
                      type="radio"
                      name="active-mod-id"
                      :value="mod.id"
                      :checked="activeModId === mod.id"
                      @change="onActiveModChange(mod.id)"
                    >
                    <span class="mod-single-text">{{ mod.name || mod.id }}</span>
                  </label>
                  <button
                    type="button"
                    class="btn btn-danger btn-sm mod-single-uninstall"
                    :disabled="uninstallingModId === mod.id || isProtectedClientModId(mod.id)"
                    @click="onUninstallMod(mod.id)"
                  >
                    {{ uninstallingModId === mod.id ? '卸载中…' : '卸载' }}
                  </button>
                </div>
              </div>
              <p v-else class="muted mod-single-empty">
                <template v-if="loadError">加载失败，请重试 Mod 与路由。</template>
                <template v-else>暂无行业扩展包。</template>
              </p>
            </section>
          </div>
        </details>

        <div class="settings-card__footer">
          <button class="settings-primary-btn" type="button" @click="saveSettings" :disabled="loading">
            {{ loading ? $t('settings.saving') : $t('settings.saveSettings') }}
          </button>
        </div>
          </div>
        </details>

        <details class="settings-card">
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--amber" aria-hidden="true">
              <i class="fa fa-flask"></i>
            </span>
            <span class="settings-row__label">蒸馏模型版本</span>
            <span class="settings-row__meta">训练产物</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>
          <div class="settings-card__body settings-card__body--compact">
            <p v-if="loadingVersions" class="muted">加载中...</p>
            <p v-else-if="versionsError" class="muted">{{ versionsError }}</p>
            <p v-else-if="versions.length === 0" class="muted">暂无训练产物</p>
            <div v-else class="settings-table-wrap">
              <table class="data-table settings-table">
                <thead>
                  <tr><th>文件</th><th>说明</th><th>修改时间</th><th>大小</th></tr>
                </thead>
                <tbody>
                  <tr v-for="v in versions" :key="v.name">
                    <td>{{ v.name }}</td>
                    <td>{{ v.label }}</td>
                    <td>{{ v.modified || '-' }}</td>
                    <td>{{ v.size_kb != null ? `${v.size_kb} KB` : '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="muted settings-meta-line">已积累蒸馏样本数：{{ sampleCount }}</p>
            <p v-if="sampleCountWarning" class="muted settings-meta-line">{{ sampleCountWarning }}</p>
          </div>
        </details>

        <details class="settings-card settings-card--about">
          <summary class="settings-row">
            <span class="settings-row__icon settings-row__icon--slate" aria-hidden="true">
              <i class="fa fa-info-circle"></i>
            </span>
            <span class="settings-row__label">{{ $t('settings.about') }}</span>
            <span class="settings-row__meta">{{ appVersionLabel }}</span>
            <span class="settings-row__arrow" aria-hidden="true"></span>
          </summary>
          <div class="settings-card__body settings-card__body--compact">
            <p class="settings-about-line">{{ aboutDisplayLine }}</p>
            <p class="muted settings-about-version">
              {{ $t('settings.currentVersion', { version: appVersionLabel }) }}
            </p>
            <div class="settings-about-actions">
              <button
                v-if="isDesktopShell"
                type="button"
                class="btn btn-sm btn-secondary"
                :disabled="aboutUpdateBusy"
                @click="onCheckForUpdates"
              >
                {{ aboutUpdateBusy ? $t('settings.checkingUpdates') : $t('settings.checkForUpdates') }}
              </button>
              <p v-else class="muted settings-about-web-hint">{{ $t('settings.updateWebHint') }}</p>
            </div>
            <p
              v-if="aboutUpdateMessage"
              class="settings-about-update-msg"
              :class="{ 'is-error': aboutUpdateError }"
            >
              {{ aboutUpdateMessage }}
            </p>
          </div>
        </details>
        </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onActivated, ref, computed, watch, nextTick, reactive } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';
import { authApi, type User } from '../api/auth';
import { LS_MARKET_USER_JSON } from '../api/marketAccount';
import { storeToRefs } from 'pinia';
import api, { ApiError } from '../api';
import { buildFullApiUrl } from '@/api/core';
import { systemApi, type Industry as ApiIndustry } from '../api/system';
import { intentPackagesApi, type IntentPackage as ApiIntentPackage } from '../api/intentPackages';
import { memoryV2Api, type MemoryV2Record, type MemoryV2Status, type MemoryV2Summary, type MemoryV2Type } from '@/api/memoryV2';
import { useIndustryStore } from '../stores/industry';
import {
  SIDEBAR_THEME_OPTIONS,
  readStoredSidebarTheme,
  persistSidebarTheme,
  applySidebarTheme,
} from '@/utils/sidebarTheme';
import { useModsStore } from '@/stores/mods';
import { useAccountProfileStore } from '@/stores/accountProfile';
import packageJson from '../../package.json';
import { appAlert, appConfirm } from '@/utils/appDialog';
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults';
import { getIndustryPreset } from '@/constants/industryPresets';
import { isProtectedClientModId } from '@/constants/protectedMods';
import {
  ACCOUNT_CUSTOM_MOD_IDS,
  expectedHostBridgeModIds,
  isHostBridgeModId,
  isSelectableExtensionModId,
  isWorkflowEmployeeModId,
} from '@/constants/genericModPack';
import HostModBridgeView from '@/components/HostModBridgeView.vue';
import MobilePairingQrCard from '@/components/settings/MobilePairingQrCard.vue';
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';
import adminAuditApi, { type AuditLogEntry } from '@/api/adminAudit';
import { setAppLocale } from '@/i18n';
import { asRecord, asArray, asString, asBoolean, asDisposable } from '@/utils/typeGuards';

const { t, locale } = useI18n();
const appLocale = ref<'zh-CN' | 'en-US'>((locale.value === 'en-US' ? 'en-US' : 'zh-CN'));

function onLocaleChange() {
  setAppLocale(appLocale.value);
}

const isAdminConsole = isAdminConsoleSpa();
const industryStore = useIndustryStore();
const accountProfileStore = useAccountProfileStore();
const router = useRouter();
const route = useRoute();

type ManifestIndustry = {
  id?: string | number
  name?: string
  units?: { primary?: string }
  intent_keywords?: IntentKeywordMap
  [key: string]: unknown
}

type IntentKeywordMap = {
  create_order?: string | string[]
  quantity_unit?: string | string[]
  print_label?: string | string[]
  [key: string]: unknown
}

type IntentPackageKey = 'base' | 'industry' | 'product' | 'quantity' | 'customer'

type IntentPackageState = {
  name: string
  iconClass: string
  description: string
  enabled: boolean
  keywords: string[]
}

type DistillationVersion = {
  name: string
  label?: string
  modified?: string
  size_kb?: number
}

type ApiMessageResult = {
  success?: boolean
  message?: string
  error?: string
}

function errorMessage(error: unknown, fallback = '未知错误'): string {
  return error instanceof Error ? error.message : String(error || fallback)
}

const localUser = ref<User | null>(null);
const sessionValid = ref(false);
const accountLoading = ref(true);
const logoutLoading = ref(false);
const companyBrandDraft = ref('');
const companyBrandSaving = ref(false);
const avatarInputRef = ref<HTMLInputElement | null>(null);
const avatarUploading = ref(false);
const avatarCacheBust = ref(0);
const profileDisplayNameDraft = ref('');
const profileEmailDraft = ref('');
const profileSaving = ref(false);
const MEMORY_V2_TYPE_OPTIONS: Array<{ value: MemoryV2Type; label: string }> = [
  { value: 'preference', label: '偏好' },
  { value: 'entity', label: '实体' },
  { value: 'episodic', label: '任务' },
];
const MEMORY_V2_STATUS_FILTERS: Array<{ value: 'all' | MemoryV2Status; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待确认' },
  { value: 'active', label: '已确认' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'deleted', label: '已删除' },
];
const memoryV2Records = ref<MemoryV2Record[]>([]);
const memoryV2Summary = ref<MemoryV2Summary>({ total: 0, by_status: {}, by_type: {} });
const memoryV2PlannerContext = ref('');
const memoryV2Loading = ref(false);
const memoryV2Creating = ref(false);
const memoryV2BusyId = ref('');
const memoryV2Error = ref('');
const memoryV2StatusFilter = ref<'all' | MemoryV2Status>('all');
const memoryV2TypeFilter = ref<'all' | MemoryV2Type>('all');
const memoryV2Draft = reactive({
  memoryType: 'preference' as MemoryV2Type,
  key: '',
  value: '',
  confidence: 0.7,
});
const memoryV2Edit = reactive({
  memoryId: '',
  key: '',
  value: '',
});

const memoryV2UserId = computed(() => {
  const raw = localUser.value?.username || localUser.value?.id || 'default';
  return String(raw || 'default').trim() || 'default';
});

const memoryV2FoldMeta = computed(() => {
  const pending = Number(memoryV2Summary.value.by_status.pending || 0);
  const active = Number(memoryV2Summary.value.by_status.active || 0);
  return `待确认 ${pending} · 已确认 ${active}`;
});

function memoryV2TypeLabel(type: unknown): string {
  return MEMORY_V2_TYPE_OPTIONS.find((item) => item.value === type)?.label || String(type || '未知');
}

function memoryV2StatusLabel(status: unknown): string {
  return MEMORY_V2_STATUS_FILTERS.find((item) => item.value === status)?.label || String(status || '未知');
}

function memoryV2EditableValue(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? '');
  }
}

function memoryV2DisplayValue(value: unknown): string {
  const text = memoryV2EditableValue(value);
  return text.length > 160 ? `${text.slice(0, 160)}…` : text;
}

function parseMemoryV2InputValue(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (/^(\{|\[|"|-?\d+(\.\d+)?$|true$|false$|null$)/i.test(trimmed)) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
  }
  return value;
}

function memoryV2Time(value: unknown): string {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const parsed = Date.parse(raw);
  if (Number.isNaN(parsed)) return raw;
  return new Date(parsed).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function canEditMemoryV2(record: MemoryV2Record): boolean {
  return record.status === 'pending' || record.status === 'active';
}

async function loadMemoryV2() {
  memoryV2Loading.value = true;
  memoryV2Error.value = '';
  try {
    const [listResult, summaryResult] = await Promise.all([
      memoryV2Api.list({
        userId: memoryV2UserId.value,
        status: memoryV2StatusFilter.value === 'all' ? undefined : memoryV2StatusFilter.value,
        memoryType: memoryV2TypeFilter.value === 'all' ? undefined : memoryV2TypeFilter.value,
      }),
      memoryV2Api.summary(memoryV2UserId.value),
    ]);
    if (listResult.success === false) throw new Error(listResult.message || '记忆加载失败');
    if (summaryResult.success === false) throw new Error(summaryResult.message || '记忆摘要加载失败');
    memoryV2Records.value = Array.isArray(listResult.memories) ? listResult.memories : [];
    memoryV2Summary.value = summaryResult.summary || listResult.summary || { total: 0, by_status: {}, by_type: {} };
    memoryV2PlannerContext.value = String(summaryResult.planner_context || '');
  } catch (e: unknown) {
    memoryV2Records.value = [];
    memoryV2PlannerContext.value = '';
    memoryV2Error.value = errorMessage(e, '记忆加载失败');
  } finally {
    memoryV2Loading.value = false;
  }
}

async function createMemoryV2Candidate() {
  const key = memoryV2Draft.key.trim();
  const value = memoryV2Draft.value.trim();
  if (!key || !value) {
    await appAlert('请填写记忆键和值');
    return;
  }
  memoryV2Creating.value = true;
  memoryV2Error.value = '';
  try {
    const result = await memoryV2Api.createCandidate({
      userId: memoryV2UserId.value,
      memoryType: memoryV2Draft.memoryType,
      key,
      value: parseMemoryV2InputValue(memoryV2Draft.value),
      confidence: Number(memoryV2Draft.confidence),
      source: 'settings_ui',
    });
    if (result.success === false) throw new Error(result.message || '候选记忆创建失败');
    memoryV2Draft.key = '';
    memoryV2Draft.value = '';
    await loadMemoryV2();
  } catch (e: unknown) {
    memoryV2Error.value = errorMessage(e, '候选记忆创建失败');
  } finally {
    memoryV2Creating.value = false;
  }
}

async function confirmMemoryV2(record: MemoryV2Record) {
  memoryV2BusyId.value = record.memory_id;
  memoryV2Error.value = '';
  try {
    const result = await memoryV2Api.confirm(record.memory_id, memoryV2UserId.value);
    if (result.success === false) throw new Error(result.message || '确认失败');
    await loadMemoryV2();
  } catch (e: unknown) {
    memoryV2Error.value = errorMessage(e, '确认失败');
  } finally {
    memoryV2BusyId.value = '';
  }
}

async function rejectMemoryV2(record: MemoryV2Record) {
  if (!(await appConfirm(`拒绝记忆「${record.key}」？`, { danger: true }))) return;
  memoryV2BusyId.value = record.memory_id;
  memoryV2Error.value = '';
  try {
    const result = await memoryV2Api.reject(record.memory_id, memoryV2UserId.value, 'settings_ui_rejected');
    if (result.success === false) throw new Error(result.message || '拒绝失败');
    await loadMemoryV2();
  } catch (e: unknown) {
    memoryV2Error.value = errorMessage(e, '拒绝失败');
  } finally {
    memoryV2BusyId.value = '';
  }
}

function startMemoryV2Edit(record: MemoryV2Record) {
  memoryV2Edit.memoryId = record.memory_id;
  memoryV2Edit.key = String(record.key || '');
  memoryV2Edit.value = memoryV2EditableValue(record.value);
}

function cancelMemoryV2Edit() {
  memoryV2Edit.memoryId = '';
  memoryV2Edit.key = '';
  memoryV2Edit.value = '';
}

async function saveMemoryV2Edit(record: MemoryV2Record) {
  const key = memoryV2Edit.key.trim();
  if (!key) {
    await appAlert('请填写记忆键');
    return;
  }
  memoryV2BusyId.value = record.memory_id;
  memoryV2Error.value = '';
  try {
    const result = await memoryV2Api.correct(record.memory_id, {
      userId: memoryV2UserId.value,
      key,
      value: parseMemoryV2InputValue(memoryV2Edit.value),
      reason: 'settings_ui_correction',
    });
    if (result.success === false) throw new Error(result.message || '修正失败');
    cancelMemoryV2Edit();
    await loadMemoryV2();
  } catch (e: unknown) {
    memoryV2Error.value = errorMessage(e, '修正失败');
  } finally {
    memoryV2BusyId.value = '';
  }
}

async function deleteMemoryV2(record: MemoryV2Record) {
  if (!(await appConfirm(`删除记忆「${record.key}」？`, { danger: true }))) return;
  memoryV2BusyId.value = record.memory_id;
  memoryV2Error.value = '';
  try {
    const result = await memoryV2Api.remove(record.memory_id, memoryV2UserId.value, 'settings_ui_deleted');
    if (result.success === false) throw new Error(result.message || '删除失败');
    if (memoryV2Edit.memoryId === record.memory_id) cancelMemoryV2Edit();
    await loadMemoryV2();
  } catch (e: unknown) {
    memoryV2Error.value = errorMessage(e, '删除失败');
  } finally {
    memoryV2BusyId.value = '';
  }
}

function unwrapUserFromMe(res: unknown): User | null {
  if (!res || typeof res !== 'object') return null;
  const o = res as Record<string, unknown>;
  const data = o.data as Record<string, unknown> | undefined;
  const u = (data?.user ?? o.user) as User | undefined;
  if (!u || typeof u !== 'object') return null;
  const username = String(u.username || '').trim();
  return username ? u : null;
}

function readMarketUserFromStorage(): User | null {
  try {
    const raw = window.localStorage.getItem(LS_MARKET_USER_JSON);
    if (!raw) return null;
    const u = JSON.parse(raw) as Record<string, unknown>;
    const username = String(u.username || '').trim();
    if (!username) return null;
    return {
      id: Number(u.id) || 0,
      username,
      display_name: String(u.display_name || username).trim() || username,
      email: String(u.email || '').trim(),
      role: 'user',
      is_active: true,
    };
  } catch {
    return null;
  }
}

function userFromSessionValidatePayload(res: unknown): User | null {
  if (!res || typeof res !== 'object') return null;
  const o = res as Record<string, unknown>;
  const ok = o.success === true || o.valid === true;
  if (!ok) return null;
  const data = o.data as Record<string, unknown> | undefined;
  const username = String(data?.username || '').trim();
  if (!username) return readMarketUserFromStorage();
  const uid = data?.user_id;
  return {
    id: uid != null ? Number(uid) : 0,
    username,
    display_name: username,
    email: '',
    role: 'user',
    is_active: true,
  };
}

function applyAccountMetaFromAuthPayload(res: unknown) {
  if (!res || typeof res !== 'object') return;
  const o = res as Record<string, unknown>;
  const base =
    o.data && typeof o.data === 'object' && !Array.isArray(o.data)
      ? (o.data as Record<string, unknown>)
      : {};
  accountProfileStore.applyFromMeData({
    ...base,
    account_kind: o.account_kind ?? base.account_kind,
    company_brand: o.company_brand ?? base.company_brand,
    market_is_admin: o.market_is_admin ?? base.market_is_admin,
    market_is_enterprise: o.market_is_enterprise ?? base.market_is_enterprise,
    impersonating_market_user_id:
      o.impersonating_market_user_id ?? base.impersonating_market_user_id,
    impersonating_username: o.impersonating_username ?? base.impersonating_username,
  });
}

async function hydrateUserFromSessionValidate(): Promise<boolean> {
  try {
    const res = await authApi.validateSession();
    const user = userFromSessionValidatePayload(res);
    if (!user) {
      sessionValid.value = false;
      return false;
    }
    sessionValid.value = true;
    localUser.value = user;
    applyAccountMetaFromAuthPayload(res);
    companyBrandDraft.value = accountProfileStore.companyBrand || '';
    return true;
  } catch {
    sessionValid.value = false;
    return false;
  }
}

const isLoggedIn = computed(() => Boolean(localUser.value) || sessionValid.value);

const isLocalAdmin = computed(() => {
  const role = String(localUser.value?.role || '').toLowerCase();
  return role === 'admin' || role === 'superadmin';
});

const auditLogsLoading = ref(false);
const auditLogs = ref<AuditLogEntry[]>([]);
const auditLogsTotal = ref(0);
const auditLogsError = ref('');

async function loadAuditLogs() {
  if (!isLocalAdmin.value) return;
  auditLogsLoading.value = true;
  auditLogsError.value = '';
  try {
    const res = await adminAuditApi.list(30, 0);
    auditLogs.value = res?.data?.items || [];
    auditLogsTotal.value = res?.data?.total || 0;
  } catch (e: unknown) {
    auditLogsError.value = errorMessage(e, '加载审计日志失败');
  } finally {
    auditLogsLoading.value = false;
  }
}

function downloadAuditCsv() {
  window.open(adminAuditApi.csvDownloadUrl(500), '_blank', 'noopener,noreferrer');
}

function syncProfileDraftsFromUser(u: User | null) {
  if (!u) {
    profileDisplayNameDraft.value = '';
    profileEmailDraft.value = '';
    return;
  }
  profileDisplayNameDraft.value = String(u.display_name || u.username || '').trim();
  profileEmailDraft.value = String(u.email || '').trim();
}

async function loadLocalUser() {
  accountLoading.value = true;
  sessionValid.value = false;
  try {
    const res = await authApi.getCurrentUser();
    localUser.value = unwrapUserFromMe(res);
    if (res?.success && res.data && typeof res.data === 'object') {
      applyAccountMetaFromAuthPayload(res);
      companyBrandDraft.value = accountProfileStore.companyBrand || '';
    }
    if (localUser.value) {
      sessionValid.value = true;
      syncProfileDraftsFromUser(localUser.value);
    } else {
      await hydrateUserFromSessionValidate();
      syncProfileDraftsFromUser(localUser.value);
    }
  } catch {
    localUser.value = null;
    await hydrateUserFromSessionValidate();
    syncProfileDraftsFromUser(localUser.value);
  } finally {
    accountLoading.value = false;
  }
}

const profileBrandTitle = computed(() => {
  const brand = String(accountProfileStore.displayBrand || '').trim();
  if (brand) return brand;
  const u = localUser.value;
  if (!u) return t('settings.notLoggedIn');
  const name = String(u.display_name || u.username || '').trim();
  return name || t('settings.user');
});

const profileSubline = computed(() => {
  const u = localUser.value;
  if (!u) return t('settings.loginSyncHint');
  const username = String(u.username || '').trim();
  const brand = String(accountProfileStore.displayBrand || '').trim();
  if (brand) {
    const display = String(u.display_name || '').trim();
    if (display && display !== brand) return `${username} · ${display}`;
    return username || '修茈市场账号';
  }
  const display = String(u.display_name || '').trim();
  if (display && username && display !== username) return username;
  if (u.id != null) return `ID ${u.id}`;
  return username;
});

const showCompanyBrandEditor = computed(() => accountProfileStore.accountKind === 'enterprise');

const companyBrandDirty = computed(() => {
  const draft = companyBrandDraft.value.trim();
  const current = String(accountProfileStore.companyBrand || '').trim();
  return draft !== current;
});

async function saveCompanyBrand() {
  companyBrandSaving.value = true;
  try {
    const brand = companyBrandDraft.value.trim();
    const res = await authApi.updateCompanyBrand(brand);
    const raw = res as Record<string, unknown>;
    if (raw?.success === false) {
      throw new Error(String(raw.message || '保存失败'));
    }
    accountProfileStore.companyBrand = brand;
    await accountProfileStore.refreshFromServer();
    companyBrandDraft.value = accountProfileStore.companyBrand || brand;
    await appAlert('企业品牌名已保存');
  } catch (e) {
    await appAlert(`保存失败：${e instanceof Error ? e.message : String(e)}`);
  } finally {
    companyBrandSaving.value = false;
  }
}

const avatarInitial = computed(() => {
  if (!localUser.value) return '';
  const name = profileBrandTitle.value;
  const ch = name.charAt(0);
  return ch ? ch.toUpperCase() : '';
});

const profileAvatarUrl = computed(() => {
  const u = localUser.value;
  const local = String(u?.avatar_url || '').trim();
  if (local) {
    const base = local.startsWith('http') ? local : buildFullApiUrl(local);
    const sep = base.includes('?') ? '&' : '?';
    return `${base}${sep}v=${avatarCacheBust.value}`;
  }
  try {
    const raw = window.localStorage.getItem(LS_MARKET_USER_JSON);
    if (!raw) return '';
    const market = JSON.parse(raw) as Record<string, unknown>;
    const url = String(market.avatar_url || market.avatar || '').trim();
    return url.startsWith('http') ? url : '';
  } catch {
    return '';
  }
});

const profileHomeSummary = computed(() => {
  const name = profileDisplayNameDraft.value.trim() || localUser.value?.username || '';
  return name ? `${name} · ${t('settings.profileHomeSummary')}` : t('settings.profileHomeSummary');
});

const profileFormDirty = computed(() => {
  const u = localUser.value;
  if (!u) return false;
  const dn = profileDisplayNameDraft.value.trim();
  const em = profileEmailDraft.value.trim();
  const curDn = String(u.display_name || u.username || '').trim();
  const curEm = String(u.email || '').trim();
  return dn !== curDn || em !== curEm;
});

function onAvatarClick() {
  if (!isLoggedIn.value || avatarUploading.value) return;
  avatarInputRef.value?.click();
}

async function onAvatarFileChange(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file || !isLoggedIn.value) return;
  if (file.size > 4 * 1024 * 1024) {
    await appAlert('头像图片不能超过 4MB');
    return;
  }
  avatarUploading.value = true;
  try {
    const res = await authApi.uploadAvatar(file);
    const url = String(res?.data?.avatar_url || '/api/auth/avatar').trim();
    if (localUser.value) {
      localUser.value = { ...localUser.value, avatar_url: url || '/api/auth/avatar' };
    }
    avatarCacheBust.value = Date.now();
    await appAlert('头像已更新');
  } catch (e) {
    await appAlert(`头像上传失败：${e instanceof Error ? e.message : String(e)}`);
  } finally {
    avatarUploading.value = false;
  }
}

async function saveProfile() {
  if (!localUser.value || !profileFormDirty.value) return;
  profileSaving.value = true;
  try {
    const res = await authApi.updateProfile({
      display_name: profileDisplayNameDraft.value.trim(),
      email: profileEmailDraft.value.trim(),
    });
    const updated = res?.data?.user;
    if (updated && localUser.value) {
      localUser.value = { ...localUser.value, ...updated };
      syncProfileDraftsFromUser(localUser.value);
    }
    await appAlert('个人资料已保存');
  } catch (e) {
    await appAlert(`保存失败：${e instanceof Error ? e.message : String(e)}`);
  } finally {
    profileSaving.value = false;
  }
}

const loginRoute = computed(() => ({
  name: 'login' as const,
  query: { redirect: route.fullPath },
}));

async function onLogout() {
  if (!(await appConfirm('确定退出本机账号？', { danger: true }))) return;
  logoutLoading.value = true;
  try {
    await authApi.logout();
    accountProfileStore.clear();
    localUser.value = null;
    sessionValid.value = false;
    await router.replace({ name: 'login', query: { redirect: '/' } });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    await appAlert(`退出失败：${msg}`);
  } finally {
    logoutLoading.value = false;
  }
}

const modsStore = useModsStore();
const { clientModsUiOff, loadError, isLoaded, mods, modRoutes, activeModId } = storeToRefs(modsStore);

const MODEL_PAYMENT_BRIDGE_ID = 'xcagi-model-payment-bridge';

const modelPaymentBridgeInstalled = computed(() =>
  mods.value.some((m) => String(m.id || '').trim() === MODEL_PAYMENT_BRIDGE_ID),
);

function openSettingsExtensions() {
  const el = document.querySelector('[data-tutorial-id="settings-extensions"]');
  if (el instanceof HTMLDetailsElement) {
    el.open = true;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  void router.push({ name: 'mod-store' });
}

const uninstallingModId = ref('');
const hostPackExpanded = ref(false);

const hostBridgeMods = computed(() => {
  const expected = new Set(expectedHostBridgeModIds());
  return mods.value
    .filter((m) => isHostBridgeModId(String(m.id || '')))
    .sort((a, b) => {
      const aid = String(a.id || '');
      const bid = String(b.id || '');
      const tier = (id: string) => (expected.has(id) ? 0 : 1);
      const t = tier(aid) - tier(bid);
      if (t !== 0) return t;
      return String(a.name || aid).localeCompare(String(b.name || bid), 'zh-CN');
    });
});

const hostBridgeInstalledCount = computed(() => {
  const ids = new Set(mods.value.map((m) => String(m.id || '').trim()));
  return expectedHostBridgeModIds().filter((id) => ids.has(id)).length;
});

const hostBridgeExpectedCount = computed(() => expectedHostBridgeModIds().length);

const selectableExtensionMods = computed(() =>
  mods.value.filter((m) => isSelectableExtensionModId(String(m.id || ''))),
);

const workflowEmployeeMods = computed(() =>
  mods.value.filter((m) => isWorkflowEmployeeModId(String(m.id || ''))),
);

function goHostPackOnboarding() {
  router.push({ path: '/onboarding', query: { step: 'host-pack' } });
}

function goModStore() {
  router.push({ name: 'mod-store' });
}

const activeModMeta = computed(() => {
  const mid = String(activeModId.value || '').trim();
  if (!mid) return null;
  return mods.value.find((m) => String(m.id || '').trim() === mid) || null;
});

/** 取 active mod 的 manifest.industry，不存在返回 null。供主单位/意图关键词读取 */
const activeModIndustry = computed<ManifestIndustry | null>(() => {
  const meta = activeModMeta.value;
  const ind = meta && typeof meta === 'object' ? (meta as { industry?: unknown }).industry : null;
  return ind && typeof ind === 'object' ? (ind as ManifestIndustry) : null;
});

const modRoutesRetrying = ref(false);

const modRoutesStatusText = computed(() => {
  if (clientModsUiOff.value) return '';
  if (loadError.value) return loadError.value;
  if (
    isLoaded.value &&
    mods.value.length > 0 &&
    modRoutes.value.length === 0
  ) {
    return 'Mod 路由未加载，请重试或刷新。';
  }
  return '';
});

const showModRoutesRetry = computed(() => Boolean(modRoutesStatusText.value));

const modSettingsFoldMeta = computed(() => {
  const host = hostBridgeMods.value.length
    ? `核心 ${hostBridgeInstalledCount.value}/${hostBridgeExpectedCount.value}`
    : '';
  const ext = `${selectableExtensionMods.value.length} 个行业包`;
  const wf = workflowEmployeeMods.value.length
    ? `${workflowEmployeeMods.value.length} 个工作流`
    : '';
  return [host, ext, wf].filter(Boolean).join(' · ') || '管理扩展';
});

const basicSettingsSummary = computed(() => {
  const mode = aiMode.value === 'offline' ? t('settings.offline') : t('settings.aiModeOnline');
  return `${normalizedAssistantName.value} · ${mode}`;
});

async function retryModRoutesLoad() {
  modRoutesRetrying.value = true;
  try {
    await modsStore.refresh();
    if (loadError.value) {
      await appAlert(loadError.value);
    } else if (mods.value.length > 0 && modRoutes.value.length === 0) {
      await appAlert('仍未获取到路由表，请确认后端已完全启动或查看控制台 / 后端日志。');
    } else {
      await appAlert('Mod 与路由已重新加载。');
    }
  } finally {
    modRoutesRetrying.value = false;
  }
}

async function onActiveModChange(modId: string) {
  const next = String(modId || '').trim();
  if (!next || activeModId.value === next) return;
  const nextMod = mods.value.find((m) => String(m.id || '').trim() === next);
  const nextIndustryId = String(nextMod?.industry?.id || '').trim();

  // 先把前端 activeModId 切到目标 mod；这样侧栏副标题、主单位、意图包等
  // 由 useIndustryUiText / activeModIndustry 派生的 UI 立刻反映新选择，
  // 不依赖后端 industry 切换是否被接受。
  modsStore.setActiveModId(next);

  if (nextIndustryId && nextIndustryId !== String(industryStore.currentIndustryId || '').trim()) {
    const success = await industryStore.switchIndustry(nextIndustryId);
    if (!success) {
      // 后端拒绝（旧版后端、或 Mod backend init 失败）：不再硬性回滚 active mod，
      // 仅给一条提示并让前端 UI 沿用 manifest.industry 兜底（已由 industry.ts
      // loadCurrentIndustry 失败分支与 useIndustryUiText effectiveIndustryId 处理）。
      console.warn(
        '[settings] 切换行业到',
        nextIndustryId,
        '失败：',
        industryStore.error || '未知',
        '；前端将沿用 mod manifest.industry 渲染',
      );
    }
  }
  // 切换 Mod 会改变侧栏菜单、工作流员工与 X-XCAGI-Active-Mod-Id 请求头，
  // 同时同步当前行业，避免侧栏副标题和业务字段仍停留在旧行业。
  window.location.reload();
}

async function onUninstallMod(modId: string) {
  const mid = String(modId || '').trim();
  if (!mid) return;
  if (isProtectedClientModId(mid)) {
    await appAlert('该扩展包为受保护的交付 Mod，不能从本机卸载。');
    return;
  }
  const meta = mods.value.find((m) => String(m.id || '').trim() === mid) || null;
  const label = (meta && String(meta.name || '').trim()) || mid;
  let question = `确定从本机卸载「${label}」（${mid}）吗？\n将删除磁盘上的包目录并解除加载，不可撤销。`;
  if (meta && meta.primary) {
    question += '\n\n该包在 manifest 中标记为主扩展（primary），请确认宿主与其它 Mod 不再依赖此 id。';
  }
  if (activeModId.value === mid) {
    question += '\n\n这是当前启用的扩展包，卸载后页面将刷新。';
  }
  if (!(await appConfirm(question, { danger: true }))) return;
  uninstallingModId.value = mid;
  try {
    const data = await api.delete<ApiMessageResult>(`/api/mods/${encodeURIComponent(mid)}`);
    if (!data || !data.success) {
      await appAlert(`卸载失败：${(data && (data.message || data.error)) || '未知错误'}`);
      return;
    }
    await appAlert(typeof data.message === 'string' ? data.message : `已卸载 ${mid}`);
    window.location.reload();
  } catch (err) {
    const msg =
      err instanceof ApiError
        ? err.message
        : err instanceof Error
          ? err.message
          : String(err);
    await appAlert(`卸载请求失败：${msg}`);
  } finally {
    uninstallingModId.value = '';
  }
}

const loading = ref(false);
const loadingVersions = ref(false);
const aiMode = ref('online');
const assistantName = ref('修茈');
const versions = ref<DistillationVersion[]>([]);
const sampleCount = ref(0);
const versionsError = ref('');
const sampleCountWarning = ref('');
const aboutUpdateBusy = ref(false);
const aboutUpdateMessage = ref('');
const aboutUpdateError = ref(false);
const currentDbPath = ref('');
const databaseStorageLabel = ref('');
const desktopDatabaseVisible = ref(false);

async function loadDesktopDatabaseStatus() {
  try {
    const res = await api.get<{ data?: Record<string, unknown>; desktopMode?: boolean; storageMode?: string }>('/api/desktop/status');
    const data = (res?.data ?? res) as Record<string, unknown>;
    if (!data || data.desktopMode === false) {
      desktopDatabaseVisible.value = false;
      databaseStorageLabel.value = '';
      currentDbPath.value = '';
      return;
    }
    desktopDatabaseVisible.value = true;
    const mode = String(data.storageMode || '');
    databaseStorageLabel.value =
      mode === 'local_sqlite'
        ? '本地数据库（SQLite）'
        : mode === 'remote_postgresql'
          ? '远程 PostgreSQL'
          : '本地数据库';
    if (data.database) {
      currentDbPath.value = String(data.database);
    }
  } catch {
    desktopDatabaseVisible.value = false;
    databaseStorageLabel.value = '';
    currentDbPath.value = '';
  }
}
const ASSISTANT_NAME_KEY = 'assistantName';
const DEFAULT_ASSISTANT_NAME = '修茈';
const industries = ref<ApiIndustry[]>([]);
const currentIndustry = ref(DEFAULT_INDUSTRY_ID);
const currentIndustryUnit = ref('天');
const sidebarThemePreset = ref('office-default');

const appVersionLabel = computed(() => String(packageJson.version || '10.0.0'));
const isDesktopShell = computed(() => Boolean(window.xcagiDesktop));

const accountCustomModIds = new Set<string>(ACCOUNT_CUSTOM_MOD_IDS);

const installedAccountCustomMod = computed(() =>
  mods.value.find((m) => accountCustomModIds.has(String(m.id || '').trim())) || null,
);

const deliveryBrandName = computed(() => {
  const customName = String(installedAccountCustomMod.value?.name || '').trim();
  if (customName) return customName;
  const brand = String(accountProfileStore.displayBrand || '').trim();
  return brand;
});

const currentIndustryLabel = computed(() => {
  const fromMod = String(activeModIndustry.value?.name || '').trim();
  if (fromMod) return fromMod;
  const id = String(currentIndustry.value || DEFAULT_INDUSTRY_ID).trim() || DEFAULT_INDUSTRY_ID;
  return String(getIndustryPreset(id).name || id || '通用').trim();
});

const systemDisplayName = computed(() => {
  const brand = deliveryBrandName.value;
  if (brand) return `${brand} 交付工作台`;
  return 'XCAGI 通用宿主';
});

const aboutDisplayLine = computed(() => {
  const brand = deliveryBrandName.value;
  const industry = currentIndustryLabel.value;
  if (brand) {
    const industryPart = industry ? `${industry}基础线` : '账号定制基础线';
    return `XCAGI 通用宿主 · ${brand} 交付 · ${industryPart}`;
  }
  return 'XCAGI 通用宿主 · 能力由 Mod 提供';
});

const selectedSidebarAccent = computed(() => {
  const selected = SIDEBAR_THEME_OPTIONS.find((item) => item.value === sidebarThemePreset.value);
  return selected?.accent || '#0f6cbd';
});

const intentPackages = ref<Record<IntentPackageKey, IntentPackageState>>({
  base: {
    name: '基础意图',
    iconClass: 'fa-file-text-o',
    description: '考勤与单据通用意图：创建、查询、修改、导出、审批',
    enabled: true,
    keywords: ['考勤', '查询', '导出', '请假', '加班', '修改', '创建', '统计']
  },
  industry: {
    name: '行业特定',
    iconClass: 'fa-industry',
    description: '当前组织的考勤制度用语与业务词汇',
    enabled: true,
    keywords: []
  },
  product: {
    name: '员工识别',
    iconClass: 'fa-cubes',
    description: '工号、姓名、部门等员工信息的识别与解析',
    enabled: true,
    keywords: ['工号', '姓名', '部门', '岗位', '职级']
  },
  quantity: {
    name: '工时解析',
    iconClass: 'fa-sort-numeric-asc',
    description: '出勤天数、工时小时数及中文数字的智能解析',
    enabled: true,
    keywords: ['天', '小时', '半天', '次', '二十三', '一十']
  },
  customer: {
    name: '组织识别',
    iconClass: 'fa-users',
    description: '部门名称、上下级关系与办公地点等信息的识别',
    enabled: true,
    keywords: ['部门', '科室', '班组', '分公司', '联系人']
  }
});

const currentIndustryConfig = computed(() => {
  return industryStore.industries.find(i => i.id === currentIndustry.value);
});

const INTENT_PACKAGE_ORDER: IntentPackageKey[] = ['base', 'industry', 'product', 'quantity', 'customer'];

const intentPackageEntries = computed(() => {
  const pkgs = intentPackages.value;
  return INTENT_PACKAGE_ORDER.filter((key) => pkgs[key]).map((key) => ({
    key,
    ...pkgs[key],
    keywords: Array.isArray(pkgs[key].keywords)
      ? pkgs[key].keywords.filter((kw) => String(kw || '').trim()).slice(0, 12)
      : [],
  }));
});

const currentIntentIndustryLabel = computed(() => {
  const cfg = currentIndustryConfig.value;
  if (cfg?.name) return String(cfg.name);
  const preset = getIndustryPreset(String(currentIndustry.value || DEFAULT_INDUSTRY_ID));
  return preset?.name || String(currentIndustry.value || '').trim() || '';
});

const normalizedAssistantName = computed(() => {
  const normalized = assistantName.value?.trim();
  return normalized || DEFAULT_ASSISTANT_NAME;
});

async function loadIndustries() {
  try {
    const response = await systemApi.getIndustries();
    if (response.success) {
      const payload = response.data as ApiIndustry[] | { industries?: ApiIndustry[]; current?: string | number } | undefined;
      industries.value = Array.isArray(payload) ? payload : payload?.industries || [];
      const cur =
        (!Array.isArray(payload) ? payload?.current : undefined) ??
        industryStore.currentIndustry?.id ??
        DEFAULT_INDUSTRY_ID;
      currentIndustry.value = String(cur).trim() || DEFAULT_INDUSTRY_ID;
    }
  } catch (e) {
    console.error('加载行业列表失败:', e);
  }
}

async function loadCurrentIndustryDetail() {
  try {
    const response = await systemApi.getCurrentIndustry();
    if (response.success) {
      // 主单位优先采用 active mod 的 manifest.industry.units.primary —— 让"切 mod"
      // 在后端尚未对齐前也能立刻把主单位切对。
      const fromMod = activeModIndustry.value?.units?.primary;
      const units = asRecord(response.data).units as Record<string, unknown> | undefined
      currentIndustryUnit.value =
        (typeof fromMod === 'string' && fromMod.trim()) ||
        asString(units?.primary) ||
        '天';
      updateIndustryKeywords();
    }
  } catch (e) {
    console.error('加载行业详情失败:', e);
    // server 失败时也用 mod manifest 兜底，避免主单位卡在默认「天」之前的状态
    const fromMod = activeModIndustry.value?.units?.primary;
    if (typeof fromMod === 'string' && fromMod.trim()) {
      currentIndustryUnit.value = fromMod.trim();
    }
    updateIndustryKeywords();
  }
}

function updateIndustryKeywords() {
  // 优先读 active mod 的 manifest.intent_keywords，让"行业特定"芯片立即跟随 mod 切换；
  // 没有 mod 或 mod 未声明 intent_keywords 时回到 industryStore.currentConfig。
  const modKw = activeModIndustry.value?.intent_keywords;
  const config = industryStore.currentConfig;
  const kw = (modKw && typeof modKw === 'object' ? modKw : asRecord(config).intent_keywords) as IntentKeywordMap | undefined;
  if (!kw || typeof kw !== 'object') return;
  const keywords: string[] = [];
  if (kw.create_order) {
    keywords.push(...(Array.isArray(kw.create_order) ? kw.create_order : [kw.create_order]));
  }
  if (kw.quantity_unit) {
    keywords.push(...(Array.isArray(kw.quantity_unit) ? kw.quantity_unit : [kw.quantity_unit]));
  }
  if (kw.print_label) {
    keywords.push(...(Array.isArray(kw.print_label) ? kw.print_label : [kw.print_label]));
  }
  intentPackages.value.industry.keywords = [...new Set(keywords.map((kw) => String(kw || '').trim()).filter(Boolean))].slice(0, 12);
}

async function loadIntentPackages() {
  try {
    const response = await intentPackagesApi.getPackages();
    const payload = response.data as ApiIntentPackage[] | { packages?: Record<string, Partial<IntentPackageState>> } | undefined;
    const packages = !Array.isArray(payload) ? payload?.packages : undefined;
    if (response.success && packages) {
      for (const key of Object.keys(packages) as IntentPackageKey[]) {
        const target = intentPackages.value[key];
        const source = packages[key];
        if (target && source) {
          if (typeof source.enabled === 'boolean') target.enabled = source.enabled;
          if (Array.isArray(source.keywords)) target.keywords = source.keywords;
        }
      }
    }
  } catch (e) {
    console.error('加载意图包失败:', e);
  }
}

async function loadPreferences() {
  try {
    const data = await api.get<{ success?: boolean; preferences?: Record<string, unknown> }>('/api/preferences', { user_id: 'default' });
    if (!data?.success || !data?.preferences) return;
    const prefs = data.preferences;

    // 与 aiMode 无关的偏好先行读取，避免被 early return 跳过
    const preferredAssistantName = prefs.assistantName;
    if (typeof preferredAssistantName === 'string') {
      assistantName.value = preferredAssistantName;
    } else {
      assistantName.value = window.localStorage.getItem(ASSISTANT_NAME_KEY) || DEFAULT_ASSISTANT_NAME;
    }
    window.localStorage.setItem(ASSISTANT_NAME_KEY, normalizedAssistantName.value);

    const preferredMode = prefs.aiMode;
    if (preferredMode === 'online' || preferredMode === 'offline') {
      aiMode.value = preferredMode;
      return;
    }
    const legacyModel = String(prefs.aiModel || '').toLowerCase();
    aiMode.value = legacyModel === 'local' ? 'offline' : 'online';
    if (legacyModel) {
      // 兼容历史键：读取后自动迁移为新键，避免后续逻辑分叉。
      await api.post('/api/preferences', {
        user_id: 'default',
        key: 'aiMode',
        value: aiMode.value,
      });
    }
  } catch (e) {
    console.error('加载设置失败:', e);
    assistantName.value = window.localStorage.getItem(ASSISTANT_NAME_KEY) || DEFAULT_ASSISTANT_NAME;
  }
}

async function saveSettings() {
  loading.value = true;
  try {
    const saveResults = await Promise.all([
      api.post<ApiMessageResult>('/api/preferences', {
        user_id: 'default',
        key: 'aiMode',
        value: aiMode.value
      }),
      api.post<ApiMessageResult>('/api/preferences', {
        user_id: 'default',
        key: ASSISTANT_NAME_KEY,
        value: normalizedAssistantName.value
      })
    ]);
    const failed = saveResults.find(item => !item?.success);
    if (failed) throw new Error(failed?.message || '保存失败');
    assistantName.value = normalizedAssistantName.value;
    window.localStorage.setItem(ASSISTANT_NAME_KEY, normalizedAssistantName.value);
    window.dispatchEvent(new CustomEvent('assistant-name-updated', {
      detail: {
        name: normalizedAssistantName.value
      }
    }));
    await appAlert('设置已保存');
  } catch (e: unknown) {
    console.error('保存设置失败:', e);
    await appAlert(`保存失败: ${errorMessage(e)}`);
  } finally {
    loading.value = false;
  }
}

function onSidebarThemeChange() {
  persistSidebarTheme(sidebarThemePreset.value);
}

async function loadDistillationVersions() {
  loadingVersions.value = true;
  versionsError.value = '';
  sampleCountWarning.value = '';
  try {
    const data = await api.get<{
      success?: boolean
      message?: string
      versions?: DistillationVersion[]
      distillation_samples?: number
      sample_count_error?: string
    }>('/api/distillation/versions');
    if (!data?.success) throw new Error(data?.message || '加载失败');
    versions.value = Array.isArray(data.versions) ? data.versions : [];
    sampleCount.value = Number(data.distillation_samples || 0);
    if (data?.sample_count_error) {
      sampleCountWarning.value = `样本数读取异常：${data.sample_count_error}`;
    }
  } catch (e: unknown) {
    console.error('加载蒸馏版本失败:', e);
    versions.value = [];
    sampleCount.value = 0;
    versionsError.value = `蒸馏信息加载失败：${errorMessage(e, '网络或服务异常')}`;
  } finally {
    loadingVersions.value = false;
  }
}

async function onCheckForUpdates() {
  if (!window.xcagiDesktop?.checkForUpdates) {
    aboutUpdateMessage.value = t('settings.updateUnavailable');
    aboutUpdateError.value = true;
    return;
  }
  aboutUpdateBusy.value = true;
  aboutUpdateMessage.value = '';
  aboutUpdateError.value = false;
  try {
    await window.xcagiDesktop.checkForUpdates();
    aboutUpdateMessage.value = t('settings.updateCheckStarted');
  } catch (e: unknown) {
    aboutUpdateMessage.value = `${t('settings.updateCheckFailed')}：${errorMessage(e)}`;
    aboutUpdateError.value = true;
  } finally {
    aboutUpdateBusy.value = false;
  }
}

function scrollToSettingsSection() {
  const section = String(route.query.section || '').trim();
  if (!section) return;
  nextTick(() => {
    const el =
      document.getElementById(`settings-${section}`) ||
      document.querySelector(`[data-tutorial-id="settings-${section}"]`);
    if (el instanceof HTMLDetailsElement) {
      el.open = true;
    } else if (el) {
      const parentDetails = el.closest('details.settings-card');
      if (parentDetails instanceof HTMLDetailsElement) parentDetails.open = true;
    }
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

watch(() => route.query.section, scrollToSettingsSection);

onMounted(async () => {
  scrollToSettingsSection();
  await loadLocalUser();
  void loadAuditLogs();
  void loadDesktopDatabaseStatus();
  const uname = String(localUser.value?.username || '').trim();
  if (!modsStore.isLoaded) {
    await modsStore.initialize(true, {
      accountUsername: uname,
    });
  }
  sidebarThemePreset.value = readStoredSidebarTheme();
  applySidebarTheme(sidebarThemePreset.value);
  await industryStore.initialize();
  await loadIndustries();
  const piniaIndustryId = industryStore.currentIndustry?.id;
  if (piniaIndustryId !== undefined && piniaIndustryId !== null && String(piniaIndustryId).trim() !== '') {
    currentIndustry.value = String(piniaIndustryId).trim();
  }
  await loadCurrentIndustryDetail();
  await loadIntentPackages();
  loadPreferences();
  void loadMemoryV2();
  loadDistillationVersions();
});

onActivated(() => {
  void loadLocalUser().then(() => loadMemoryV2());
});

watch(memoryV2UserId, () => {
  void loadMemoryV2();
});

watch(
  activeModIndustry,
  () => {
    updateIndustryKeywords();
  },
  { deep: true },
);

</script>

<style scoped>
/* 豆包式分组列表：浅灰底 + 白卡片 + 左图标右箭头 */
.settings-page {
  --settings-bg: #f3f4f6;
  --settings-card-bg: #ffffff;
  --settings-card-border: rgba(0, 0, 0, 0.06);
  --settings-divider: rgba(0, 0, 0, 0.06);
  --settings-accent: #2d6df6;
  --settings-accent-soft: #eff6ff;
  --settings-radius: 14px;
  --settings-main-max: 640px;
  --settings-profile-width: 168px;
  --settings-row-pad-x: 16px;
  --settings-icon-size: 36px;
}

.settings-page__scroll {
  padding: 0;
  background: var(--settings-bg);
}

.settings-layout {
  display: grid;
  grid-template-columns: var(--settings-profile-width) minmax(0, var(--settings-main-max));
  gap: 32px;
  align-items: start;
  max-width: calc(var(--settings-profile-width) + var(--settings-main-max) + 32px);
  margin: 0 auto;
  padding: 24px 20px 48px;
}

.settings-layout__main {
  min-width: 0;
}

.settings-profile {
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 8px 4px;
}

.settings-profile__avatar-input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}

.settings-profile__avatar {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 88px;
  height: 88px;
  padding: 0;
  border: none;
  cursor: pointer;
  font: inherit;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(145deg, #60a5fa, #2563eb);
  color: #fff;
  font-size: 32px;
  font-weight: 700;
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.22);
  margin-bottom: 14px;
}

.settings-profile__avatar.is-guest {
  background: linear-gradient(145deg, #e5e7eb, #9ca3af);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  font-size: 28px;
}

.settings-profile__avatar.is-loading {
  opacity: 0.65;
}

.settings-profile__avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.settings-profile__avatar-letter {
  line-height: 1;
}

.settings-profile__avatar:disabled {
  cursor: default;
}

.settings-profile__avatar:not(:disabled):hover .settings-profile__avatar-hint,
.settings-profile__avatar:not(:disabled):focus-visible .settings-profile__avatar-hint {
  opacity: 1;
}

.settings-profile__avatar-hint {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  background: rgba(15, 23, 42, 0.48);
  opacity: 0;
  transition: opacity 0.15s ease;
  pointer-events: none;
}

.settings-profile-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  max-width: 520px;
  padding: 16px var(--settings-row-pad-x, 16px) 18px;
  box-sizing: border-box;
}

.settings-profile-form__editable {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

@media (min-width: 520px) {
  .settings-profile-form__editable {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px 16px;
  }
}

.settings-profile-form__field {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  margin: 0;
}

.settings-profile-form__label {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  line-height: 1.35;
}

.settings-profile-form__input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  min-height: 40px;
  padding: 9px 12px;
  font-size: 14px;
  line-height: 1.4;
  color: #111827;
  text-align: left;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  appearance: none;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    background-color 0.15s ease;
}

.settings-profile-form__input::placeholder {
  color: #9ca3af;
}

.settings-profile-form__input:hover {
  border-color: #d1d5db;
}

.settings-profile-form__input:focus {
  outline: none;
  border-color: #93c5fd;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(45, 109, 246, 0.15);
}

.settings-profile-form__readonly {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid #f3f4f6;
  background: #f9fafb;
}

.settings-profile-form__readonly-value {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
  letter-spacing: 0.02em;
}

.settings-profile-form__hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #9ca3af;
}

.settings-profile-form__actions {
  display: flex;
  justify-content: flex-start;
  padding-top: 2px;
}

.settings-profile-form__submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 128px;
  min-height: 40px;
  padding: 0 20px;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: var(--settings-accent, #2d6df6);
  box-shadow: 0 4px 12px rgba(45, 109, 246, 0.22);
  cursor: pointer;
  transition:
    filter 0.15s ease,
    box-shadow 0.15s ease,
    opacity 0.15s ease;
}

.settings-profile-form__submit:hover:not(:disabled) {
  filter: brightness(1.05);
}

.settings-profile-form__submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.settings-profile-form__submit--ghost {
  margin-left: 8px;
  color: var(--settings-accent, #2d6df6);
  background: #fff;
  border: 1px solid rgba(45, 109, 246, 0.35);
  box-shadow: none;
}

.settings-audit-list {
  list-style: none;
  margin: 0;
  padding: 0 16px 8px;
  max-height: 280px;
  overflow: auto;
}

.settings-audit-list__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
}

.settings-audit-list__action {
  font-weight: 600;
  color: #111827;
}

.settings-audit-list__meta {
  color: #6b7280;
  font-size: 12px;
}

.settings-profile__name {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #1a1a1a;
  line-height: 1.35;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-profile__brand {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.01em;
}

.settings-profile__sub {
  margin: 6px 0 0;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.4;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-profile__actions {
  margin-top: 16px;
  width: 100%;
}

.settings-profile__btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 38px;
  padding: 0 14px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.settings-profile__btn--primary {
  border: none;
  background: var(--settings-accent);
  color: #fff;
  box-shadow: 0 4px 12px rgba(45, 109, 246, 0.25);
}

.settings-profile__btn--primary:hover {
  filter: brightness(1.05);
}

.settings-profile__btn--ghost {
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #374151;
}

.settings-profile__btn--ghost:hover:not(:disabled) {
  background: #f9fafb;
  border-color: #d1d5db;
}

.settings-profile__btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.settings-page__hero {
  margin-bottom: 16px;
  padding: 0 4px;
}

.settings-page__title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #1a1a1a;
  line-height: 1.3;
}

.settings-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.settings-card {
  margin: 0;
  border: 1px solid var(--settings-card-border);
  border-radius: var(--settings-radius);
  background: var(--settings-card-bg);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.settings-card--nested {
  margin: 0;
  border: none;
  border-radius: 0;
  box-shadow: none;
  border-top: 1px solid var(--settings-divider);
}

.settings-card--about {
  border-style: dashed;
  background: #fafafa;
}

.settings-row {
  display: grid;
  grid-template-columns: var(--settings-icon-size) 1fr auto auto;
  align-items: center;
  gap: 12px;
  min-height: 56px;
  padding: 10px var(--settings-row-pad-x);
  cursor: pointer;
  list-style: none;
  user-select: none;
  transition: background-color 0.12s ease;
}

.settings-row--nested {
  grid-template-columns: var(--settings-icon-size) 1fr auto auto;
}

.settings-row:hover {
  background: #f9fafb;
}

.settings-row::-webkit-details-marker {
  display: none;
}

.settings-row__icon {
  width: var(--settings-icon-size);
  height: var(--settings-icon-size);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  color: #fff;
  font-size: 16px;
  flex-shrink: 0;
}

.settings-row__icon--blue { background: linear-gradient(145deg, #3b82f6, #2563eb); }
.settings-row__icon--purple { background: linear-gradient(145deg, #a78bfa, #7c3aed); }
.settings-row__icon--green { background: linear-gradient(145deg, #4ade80, #16a34a); }
.settings-row__icon--amber { background: linear-gradient(145deg, #fbbf24, #d97706); }
.settings-row__icon--orange { background: linear-gradient(145deg, #fb923c, #ea580c); }
.settings-row__icon--cyan { background: linear-gradient(145deg, #22d3ee, #0891b2); }
.settings-row__icon--indigo { background: linear-gradient(145deg, #818cf8, #4f46e5); }
.settings-row__icon--violet { background: linear-gradient(145deg, #c084fc, #9333ea); }
.settings-row__icon--slate { background: linear-gradient(145deg, #94a3b8, #64748b); }

.settings-row__label {
  font-size: 15px;
  font-weight: 500;
  color: #1a1a1a;
  min-width: 0;
}

.settings-row__meta {
  font-size: 13px;
  color: #9ca3af;
  max-width: 42%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-row__pill {
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
  padding: 4px 10px;
  border-radius: 999px;
  background: #f3f4f6;
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-row__arrow {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #d1d5db;
  font-size: 18px;
  line-height: 1;
  transition: transform 0.15s ease, color 0.15s ease;
}

.settings-row__arrow::before {
  content: '›';
  font-weight: 300;
}

.settings-card[open] > .settings-row .settings-row__arrow {
  transform: rotate(90deg);
  color: #9ca3af;
}

.settings-card__body {
  padding: 0 var(--settings-row-pad-x) 16px;
  border-top: 1px solid var(--settings-divider);
}

.settings-card__body--flush {
  padding: 0 12px 12px;
}

.settings-card__body--list {
  padding: 0;
  border-top: 1px solid var(--settings-divider);
}

.settings-card__body--compact {
  padding-top: 12px;
}

.settings-card__body--nested {
  padding: 12px var(--settings-row-pad-x) 14px;
  border-top: 1px solid var(--settings-divider);
  background: #fafafa;
}

.settings-card__footer {
  padding: 12px var(--settings-row-pad-x) 16px;
  border-top: 1px solid var(--settings-divider);
}

.settings-card:not([open]) > .settings-card__body,
.settings-card:not([open]) > .settings-card__footer {
  display: none;
}

.settings-item-list {
  display: flex;
  flex-direction: column;
}

.settings-item {
  display: grid;
  grid-template-columns: var(--settings-icon-size) 1fr minmax(100px, 42%);
  align-items: center;
  gap: 12px;
  min-height: 52px;
  padding: 8px var(--settings-row-pad-x);
  border-bottom: 1px solid var(--settings-divider);
}

.settings-item:last-child {
  border-bottom: none;
}

.settings-item__icon {
  width: var(--settings-icon-size);
  height: var(--settings-icon-size);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  color: #fff;
  font-size: 15px;
}

.settings-item__label {
  font-size: 15px;
  font-weight: 500;
  color: #1a1a1a;
  margin: 0;
}

.settings-item__control {
  --settings-control-chevron: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath fill='%236b7280' d='M2 1.5 6 6.5 10 1.5'/%3E%3C/svg%3E");
  justify-self: end;
  width: 100%;
  max-width: 200px;
  min-height: 36px;
  padding: 0 36px 0 12px;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.35;
  color: #111827;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background-color: #f9fafb;
  background-image: var(--settings-control-chevron);
  background-repeat: no-repeat;
  background-position: right 12px center;
  background-size: 12px 8px;
  -webkit-appearance: none;
  -moz-appearance: none;
  appearance: none;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease,
    box-shadow 0.15s ease;
}

select.settings-item__control,
.settings-item__control--select {
  text-align-last: left;
}

.settings-item__control:hover {
  border-color: #d1d5db;
  background-color: #fff;
}

.settings-item__control-group {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.settings-item__control-group .settings-item__control--text {
  flex: 1;
  min-width: 0;
}

.settings-item__save-btn {
  flex-shrink: 0;
  border: 1px solid #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.settings-item__save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.settings-item__control--text {
  background-color: #f9fafb;
  background-image: none;
  text-align: left;
  padding-right: 12px;
  font-weight: 400;
  cursor: text;
}

.settings-item__control--text:hover {
  background-color: #fff;
}

.settings-item__control:focus,
.settings-item__control:focus-visible {
  outline: none;
  border-color: #93c5fd;
  background-color: #fff;
  background-image: var(--settings-control-chevron);
  box-shadow: 0 0 0 3px rgba(45, 109, 246, 0.14);
}

.settings-item__control--text:focus,
.settings-item__control--text:focus-visible {
  background-image: none;
}

.settings-item__control option {
  font-size: 14px;
  font-weight: 500;
  color: #111827;
  background: #fff;
}

.settings-item__value {
  justify-self: end;
  font-size: 13px;
  color: #9ca3af;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

.settings-item__value--mono {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
}

.settings-primary-btn {
  width: 100%;
  min-height: 44px;
  border: none;
  border-radius: 12px;
  background: var(--settings-accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(45, 109, 246, 0.28);
  transition: opacity 0.15s ease, transform 0.1s ease;
}

.settings-primary-btn:hover:not(:disabled) {
  filter: brightness(1.05);
}

.settings-primary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.settings-table-wrap {
  overflow-x: auto;
  border-radius: 10px;
  border: 1px solid #f1f5f9;
}

.settings-table {
  margin: 0;
  font-size: 13px;
}

.settings-meta-line {
  margin: 10px 0 0;
  font-size: 12px;
}

.memory-v2-toolbar,
.memory-v2-form,
.memory-v2-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.memory-v2-toolbar {
  margin-bottom: 12px;
}

.memory-v2-select {
  max-width: 132px;
}

.memory-v2-form {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #f9fafb;
}

.memory-v2-form__type {
  max-width: 104px;
}

.memory-v2-form__input {
  flex: 1 1 132px;
  max-width: none;
}

.memory-v2-form__confidence {
  width: 86px;
  max-width: 86px;
}

.memory-v2-error {
  margin: 0 0 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.45;
}

.memory-v2-context {
  max-height: 132px;
  margin: 12px 0 0;
  padding: 10px 12px;
  overflow: auto;
  border-radius: 10px;
  background: #0f172a;
  color: #e5e7eb;
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.memory-v2-state {
  margin: 12px 0 0;
  font-size: 13px;
}

.memory-v2-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.memory-v2-item {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
}

.memory-v2-item__head,
.memory-v2-item__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.memory-v2-item__head {
  margin-bottom: 8px;
}

.memory-v2-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  background: #eef2ff;
  color: #4338ca;
  font-size: 11px;
  font-weight: 700;
}

.memory-v2-chip--active {
  background: #dcfce7;
  color: #166534;
}

.memory-v2-chip--pending {
  background: #fef3c7;
  color: #92400e;
}

.memory-v2-chip--rejected,
.memory-v2-chip--deleted {
  background: #f1f5f9;
  color: #64748b;
}

.memory-v2-item__time {
  margin-left: auto;
  color: #94a3b8;
  font-size: 11px;
}

.memory-v2-item__body {
  display: grid;
  grid-template-columns: minmax(96px, 32%) 1fr;
  gap: 10px;
  align-items: start;
}

.memory-v2-item__key {
  min-width: 0;
  overflow-wrap: anywhere;
  color: #111827;
  font-size: 13px;
}

.memory-v2-item__value {
  min-width: 0;
  overflow-wrap: anywhere;
  color: #374151;
  font-size: 13px;
  line-height: 1.45;
  white-space: pre-wrap;
}

.memory-v2-item__meta {
  margin-top: 8px;
  color: #94a3b8;
  font-size: 11px;
}

.memory-v2-actions {
  justify-content: flex-end;
  margin-top: 10px;
}

.memory-v2-edit {
  display: grid;
  gap: 8px;
}

.memory-v2-edit__input {
  max-width: none;
}

.memory-v2-edit__textarea {
  width: 100%;
  min-height: 76px;
  resize: vertical;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #f9fafb;
  color: #111827;
  font-size: 13px;
  line-height: 1.45;
}

.memory-v2-edit__textarea:focus,
.memory-v2-edit__textarea:focus-visible {
  outline: none;
  border-color: #93c5fd;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(45, 109, 246, 0.14);
}

.settings-about-line {
  margin: 0 0 6px;
  font-size: 14px;
  color: #374151;
}

.settings-about-version {
  margin: 0;
  font-size: 13px;
  line-height: 1.45;
}

.settings-about-actions {
  margin-top: 12px;
}

.settings-about-web-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
}

.settings-about-update-msg {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: #64748b;
}

.settings-about-update-msg.is-error {
  color: #dc2626;
}

.settings-model-service-empty {
  padding: 16px;
}

.settings-model-service-empty__title {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.settings-model-service-empty__lead {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
}

.settings-model-service-empty__list {
  margin: 10px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.65;
}

.settings-model-service-empty__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

/* 嵌入：模型服务 Mod */
#settings-model-payment :deep(.mp-root--embedded) {
  margin: 0;
}

#settings-model-payment :deep(.mp-page-content--embedded) {
  padding: 0;
}

#settings-model-payment :deep(.mp-embedded-toolbar) {
  align-items: center;
  gap: 16px;
  margin: 0 0 12px;
  padding: 10px 4px 14px;
  border-bottom: 1px solid #f1f5f9;
}

#settings-model-payment :deep(.mp-embedded-intro) {
  font-size: 13px;
}

#settings-model-payment :deep(.mp-hero-actions--embedded) {
  flex-wrap: nowrap;
}

#settings-model-payment :deep(.mp-hero-btn) {
  border-radius: 10px;
  font-size: 13px;
  padding: 8px 16px;
}

#settings-model-payment :deep(.mp-hero-btn--primary) {
  background: var(--settings-accent);
  border-color: var(--settings-accent);
  box-shadow: 0 4px 12px rgba(45, 109, 246, 0.28);
}

#settings-model-payment :deep(.mp-fold) {
  margin: 0;
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  border-bottom: 1px solid var(--settings-divider);
}

#settings-model-payment :deep(.mp-fold:last-child) {
  border-bottom: none;
}

#settings-model-payment :deep(.mp-fold-title) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 48px;
  margin: 0;
  padding: 12px 4px;
  font-size: 15px;
  font-weight: 500;
  color: #1a1a1a;
}

#settings-model-payment :deep(.mp-fold-title)::after {
  content: '›';
  color: #d1d5db;
  font-size: 18px;
  font-weight: 300;
  transition: transform 0.15s ease;
}

#settings-model-payment :deep(.mp-fold[open] .mp-fold-title)::after {
  transform: rotate(90deg);
}

#settings-model-payment :deep(.mp-fold-title::-webkit-details-marker) {
  display: none;
}

#settings-model-payment :deep(.mp-panel.mp-balance) {
  border-radius: 12px;
  border-color: #e2e8f0;
  box-shadow: none;
  margin-bottom: 0;
}

#settings-model-payment :deep(.card-header.mp-panel-title) {
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: none;
  background: transparent;
  font-size: 14px;
}

#settings-model-payment :deep(.mp-market-quota) {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}

#settings-model-payment :deep(.mp-market-quota > div) {
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #e8eef5;
  text-align: center;
}

#settings-model-payment :deep(.mp-market-quota span) {
  display: block;
  font-size: 11px;
  color: #64748b;
  margin-bottom: 4px;
}

#settings-model-payment :deep(.mp-market-quota strong) {
  font-size: 13px;
  color: #0f172a;
}

#settings-model-payment :deep(.mp-balance-amount) {
  align-self: flex-start;
}

#settings-model-payment :deep(.card) {
  margin-bottom: 0;
  box-shadow: none;
}

/* —— AI 意图 —— */

.intent-showcase-state {
  padding: 20px 0;
  text-align: center;
  font-size: 13px;
}

.intent-showcase-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.intent-showcase-tile {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid rgba(203, 213, 225, 0.85);
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.intent-showcase-tile.is-enabled {
  border-color: rgba(59, 130, 246, 0.35);
  background: linear-gradient(180deg, #fff 0%, #f8fbff 100%);
}

.intent-showcase-tile.is-disabled {
  opacity: 0.72;
  background: #f8fafc;
}

.intent-tile-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.intent-tile-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(219, 234, 254, 0.65);
  color: #2563eb;
  font-size: 16px;
}

.intent-showcase-tile.is-disabled .intent-tile-icon {
  background: #e2e8f0;
  color: #64748b;
}

.intent-tile-title-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
}

.intent-tile-title {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
  color: #0f172a;
  line-height: 1.3;
}

.intent-tile-status {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  line-height: 1.4;
}

.intent-tile-status--on {
  color: #166534;
  background: #dcfce7;
}

.intent-tile-status--off {
  color: #64748b;
  background: #f1f5f9;
}

.intent-tile-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
}

.intent-tile-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.intent-chip {
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 6px;
  background: rgba(219, 234, 254, 0.75);
  color: #1d4ed8;
  border: 1px solid rgba(147, 197, 253, 0.35);
}

.intent-showcase-tile.is-disabled .intent-chip:not(.intent-chip--empty) {
  background: #f1f5f9;
  color: #64748b;
  border-color: #e2e8f0;
}

.intent-chip--empty {
  background: transparent;
  border-style: dashed;
  color: #94a3b8;
}

.about-debug-entry {
  cursor: pointer;
  user-select: none;
}

.theme-color-chip {
  display: inline-block;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  margin: 0 6px -3px 4px;
  border: 1px solid rgba(15, 23, 42, 0.2);
}

.mod-fold-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--app-border-subtle);
}

.mod-fold-section:first-child {
  margin-top: 10px;
  padding-top: 10px;
  border-top: none;
}

.mod-fold-section--inline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
}

.mod-fold-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.settings-sidebar-theme-hint {
  line-height: 1.55;
  word-break: break-word;
}

.mod-ui-off-label {
  display: block;
  font-weight: 600;
  margin-bottom: 0;
}

.mod-ui-off-desc {
  margin: 8px 0 0;
  max-width: 52rem;
}

.mod-ui-off-desc code {
  font-size: 0.85em;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.06);
}

.mod-host-pack-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-top: 8px;
}

.mod-host-pack-stat {
  font-size: 13px;
  color: var(--app-text-secondary);
}

.mod-host-pack-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 160px;
  overflow-y: auto;
}

.mod-host-pack-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid var(--app-border-subtle);
}

.mod-host-pack-name {
  font-size: 12px;
  color: var(--app-text-strong);
  min-width: 0;
}

.mod-single-empty {
  margin: 8px 0 0;
  font-size: 13px;
}

.mod-single-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 180px;
  overflow-y: auto;
  padding-right: 4px;
}

.mod-single-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--app-border-subtle);
  border-radius: 10px;
  background: var(--card-bg);
  padding: 8px 10px 8px 12px;
  transition: border-color 0.16s ease, background-color 0.16s ease, box-shadow 0.16s ease;
}

.mod-single-item:hover {
  border-color: #bfdbfe;
  background: #f8fbff;
}

.mod-single-item.active {
  border-color: var(--app-interactive);
  background: var(--app-interactive-bg);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.mod-single-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.mod-single-main input[type='radio'] {
  margin: 0;
  flex-shrink: 0;
  width: 15px;
  height: 15px;
  accent-color: #2563eb;
}

.mod-single-uninstall {
  flex-shrink: 0;
  min-width: 56px;
}

.mod-single-text {
  font-size: 13px;
  color: var(--app-text-strong);
  line-height: 1.35;
}

.text-warning {
  color: #f59e0b !important;
}

@media (max-width: 1024px) {
  .intent-showcase-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  #settings-model-payment :deep(.mp-market-quota) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .settings-layout {
    grid-template-columns: 1fr;
    gap: 20px;
    padding: 16px 12px 40px;
    max-width: none;
  }

  .settings-profile {
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: flex-start;
    gap: 12px 16px;
    text-align: left;
    padding: 12px 14px;
    border-radius: var(--settings-radius);
    background: var(--settings-card-bg);
    border: 1px solid var(--settings-card-border);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  }

  .settings-profile__avatar {
    width: 56px;
    height: 56px;
    font-size: 22px;
    margin: 0;
    flex-shrink: 0;
  }

  .settings-profile__name,
  .settings-profile__sub {
    flex: 1;
    min-width: 120px;
    text-align: left;
  }

  .settings-profile__actions {
    margin: 0;
    width: auto;
    flex: 0 0 auto;
  }

  .settings-profile__btn {
    width: auto;
    min-width: 88px;
  }

  .settings-row__meta,
  .settings-row__pill {
    max-width: 34%;
  }

  .settings-item {
    grid-template-columns: var(--settings-icon-size) 1fr;
    grid-template-rows: auto auto;
    gap: 6px 12px;
  }

  .settings-item__control,
  .settings-item__value {
    grid-column: 2;
    justify-self: stretch;
    max-width: none;
    text-align: left;
  }

  .intent-showcase-grid {
    grid-template-columns: 1fr;
  }

  .memory-v2-select,
  .memory-v2-form__type,
  .memory-v2-form__input,
  .memory-v2-form__confidence {
    flex: 1 1 100%;
    width: 100%;
    max-width: none;
  }

  .memory-v2-item__body {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .memory-v2-item__time {
    width: 100%;
    margin-left: 0;
  }

  .memory-v2-actions {
    justify-content: flex-start;
  }

  #settings-model-payment :deep(.mp-embedded-toolbar) {
    flex-direction: column;
  }

  #settings-model-payment :deep(.mp-hero-actions) {
    width: 100%;
  }

  #settings-model-payment :deep(.mp-hero-btn) {
    flex: 1;
    justify-content: center;
  }
}
</style>
