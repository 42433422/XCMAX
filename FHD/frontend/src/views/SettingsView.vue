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
            <img v-if="profileAvatarUrl" :src="profileAvatarUrl" alt="" class="settings-profile__avatar-img" />
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
          />
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
            <router-link v-else class="settings-profile__btn settings-profile__btn--primary" :to="loginRoute">
              {{ $t('settings.login') }}
            </router-link>
          </div>
        </aside>

        <div class="settings-layout__main">
          <header class="settings-page__hero">
            <h1 class="settings-page__title">{{ $t('settings.pageTitle') }}</h1>
          </header>

          <div class="settings-list">
            <details v-if="isLoggedIn" id="settings-profile-home" class="settings-card" data-tutorial-id="settings-profile-home" open>
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
                      />
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
                      />
                    </label>
                  </div>
                  <div class="settings-profile-form__readonly" aria-readonly="true">
                    <span class="settings-profile-form__label">{{ $t('settings.loginName') }}</span>
                    <span class="settings-profile-form__readonly-value">{{ localUser?.username || '—' }}</span>
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

            <details id="settings-model-payment" class="settings-card" data-tutorial-id="settings-model-payment" open>
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
                  v-if="showModelPaymentBridge"
                  embedded
                  mod-id="xcagi-model-payment-bridge"
                  view="ModelPaymentView"
                  :title="$t('settings.modelService')"
                />
                <div v-else class="settings-model-service-empty">
                  <p class="settings-model-service-empty__title">
                    {{ $t('settings.modelServiceMissingTitle') }}
                  </p>
                  <p class="muted settings-model-service-empty__lead">
                    {{ $t('settings.modelServiceMissingLead') }}
                  </p>
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

            <details v-if="isLoggedIn && isLocalAdmin" class="settings-card" data-tutorial-id="settings-audit-logs">
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--amber" aria-hidden="true">
                  <i class="fa fa-shield"></i>
                </span>
                <span class="settings-row__label">{{ $t('settings.securityAudit') }}</span>
                <span class="settings-row__meta">{{ $t('settings.auditCount', { count: auditLogsTotal }) }}</span>
                <span class="settings-row__arrow" aria-hidden="true"></span>
              </summary>
              <div class="settings-card__body settings-card__body--list">
                <p v-if="auditLogsLoading" class="muted" style="padding: 12px 16px; margin: 0">
                  {{ $t('settings.auditLoading') }}
                </p>
                <p v-else-if="auditLogsError" class="settings-profile-form__hint" role="alert" style="padding: 12px 16px">
                  {{ auditLogsError }}
                </p>
                <ul v-else-if="auditLogs.length" class="settings-audit-list">
                  <li v-for="(row, idx) in auditLogs" :key="idx" class="settings-audit-list__item">
                    <span class="settings-audit-list__action">{{ row.action || '—' }}</span>
                    <span class="settings-audit-list__meta">
                      {{ row.timestamp || row.ts || '' }}
                      · {{ row.user_id ?? '—' }} ·
                      {{ row.success === false ? $t('settings.auditFailed') : $t('settings.auditSuccess') }}
                    </span>
                  </li>
                </ul>
                <p v-else class="muted" style="padding: 12px 16px; margin: 0">
                  {{ $t('settings.auditEmpty') }}
                </p>
                <div class="settings-profile-form__actions" style="padding: 0 16px 16px">
                  <button type="button" class="settings-profile-form__submit" @click="loadAuditLogs">
                    {{ $t('settings.refresh') }}
                  </button>
                  <button
                    type="button"
                    class="settings-profile-form__submit settings-profile-form__submit--ghost"
                    @click="downloadAuditCsv"
                  >
                    {{ $t('settings.exportCsv') }}
                  </button>
                </div>
              </div>
            </details>

            <details class="settings-card" data-tutorial-id="settings-intent" open>
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--purple" aria-hidden="true">
                  <i class="fa fa-magic"></i>
                </span>
                <span class="settings-row__label">{{ $t('settings.aiIntent') }}</span>
                <span v-if="currentIntentIndustryLabel" class="settings-row__pill" @click.stop>
                  {{ currentIntentIndustryLabel }}
                  <template v-if="currentIndustryUnit"> · {{ currentIndustryUnit }}</template>
                </span>
                <span v-else class="settings-row__meta">{{ $t('settings.readOnly') }}</span>
                <span class="settings-row__arrow" aria-hidden="true"></span>
              </summary>

              <div class="settings-card__body">
                <div v-if="!currentIndustryConfig" class="intent-showcase-state muted">
                  {{ $t('settings.intentNotLoaded') }}
                </div>
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
                        <span class="intent-tile-status" :class="entry.enabled ? 'intent-tile-status--on' : 'intent-tile-status--off'">
                          {{ entry.enabled ? $t('settings.intentEnabled') : $t('settings.intentDisabled') }}
                        </span>
                      </div>
                    </div>
                    <p class="intent-tile-desc">{{ entry.description }}</p>
                    <div class="intent-tile-keywords">
                      <span v-for="kw in entry.keywords" :key="`${entry.key}-${kw}`" class="intent-chip">{{ kw }}</span>
                      <span v-if="!entry.keywords.length" class="intent-chip intent-chip--empty">{{
                        $t('settings.noSampleKeywords')
                      }}</span>
                    </div>
                  </article>
                </div>
              </div>
            </details>

            <details class="settings-card" data-tutorial-id="settings-memory-v2" open>
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--blue" aria-hidden="true">
                  <i class="fa fa-bookmark"></i>
                </span>
                <span class="settings-row__label">{{ $t('settings.persySystem') }}</span>
                <span class="settings-row__meta">{{ persyFoldMeta }}</span>
                <span class="settings-row__arrow" aria-hidden="true"></span>
              </summary>

              <div class="settings-card__body settings-card__body--compact">
                <div class="persy-profile">
                  <div v-if="persyLoading" class="persy-profile__state muted">
                    {{ $t('settings.persyLoading') }}
                  </div>
                  <div v-else-if="persyProfile" class="persy-profile__body">
                    <div class="persy-profile__head">
                      <span class="persy-profile__identity">{{ persyProfile.identity_composite || persyProfile.identity_primary }}</span>
                      <span class="persy-profile__type">{{ persyProfile.mbti_type }}</span>
                      <span class="persy-profile__meta">{{
                        $t('settings.persyInteractions', { count: persyProfile.interaction_count })
                      }}</span>
                    </div>
                    <div class="persy-profile__axes">
                      <div class="persy-axis">
                        <span class="persy-axis__label">{{ $t('settings.persyWarmth') }}</span>
                        <div class="persy-axis__bar">
                          <div class="persy-axis__fill" :style="{ width: `${persyProfile.four_axes.warmth}%` }"></div>
                        </div>
                        <span class="persy-axis__score">{{ persyProfile.four_axes.warmth }}</span>
                      </div>
                      <div class="persy-axis">
                        <span class="persy-axis__label">{{ $t('settings.persyVerbosity') }}</span>
                        <div class="persy-axis__bar">
                          <div class="persy-axis__fill" :style="{ width: `${persyProfile.four_axes.verbosity}%` }"></div>
                        </div>
                        <span class="persy-axis__score">{{ persyProfile.four_axes.verbosity }}</span>
                      </div>
                      <div class="persy-axis">
                        <span class="persy-axis__label">{{ $t('settings.persyProactiveness') }}</span>
                        <div class="persy-axis__bar">
                          <div class="persy-axis__fill" :style="{ width: `${persyProfile.four_axes.proactiveness}%` }"></div>
                        </div>
                        <span class="persy-axis__score">{{ persyProfile.four_axes.proactiveness }}</span>
                      </div>
                      <div class="persy-axis">
                        <span class="persy-axis__label">{{ $t('settings.persyStructuredness') }}</span>
                        <div class="persy-axis__bar">
                          <div class="persy-axis__fill" :style="{ width: `${persyProfile.four_axes.structuredness}%` }"></div>
                        </div>
                        <span class="persy-axis__score">{{ persyProfile.four_axes.structuredness }}</span>
                      </div>
                    </div>
                    <div class="persy-profile__footer">
                      <button type="button" class="btn btn-sm btn-secondary" :disabled="persyInferring" @click="runPersyInfer">
                        {{ persyInferring ? $t('settings.persyInferring') : $t('settings.persyInfer') }}
                      </button>
                      <span v-if="persyLastReason" class="persy-profile__reason">{{ persyLastReason }}</span>
                    </div>
                  </div>
                  <div v-else class="persy-profile__state muted">
                    {{ $t('settings.persyEmpty') }}
                  </div>
                </div>

                <div class="memory-v2-toolbar">
                  <select
                    v-model="memoryV2StatusFilter"
                    class="settings-item__control settings-item__control--select memory-v2-select"
                    :disabled="memoryV2Loading"
                    @change="loadMemoryV2"
                  >
                    <option v-for="item in memoryV2StatusFilters" :key="item.value" :value="item.value">
                      {{ item.label }}
                    </option>
                  </select>
                  <select
                    v-model="memoryV2TypeFilter"
                    class="settings-item__control settings-item__control--select memory-v2-select"
                    :disabled="memoryV2Loading"
                    @change="loadMemoryV2"
                  >
                    <option value="all">{{ $t('settings.memoryAllTypes') }}</option>
                    <option v-for="item in memoryV2TypeOptions" :key="item.value" :value="item.value">
                      {{ item.label }}
                    </option>
                  </select>
                  <button type="button" class="btn btn-sm btn-secondary" :disabled="memoryV2Loading" @click="loadMemoryV2">
                    {{ $t('settings.refresh') }}
                  </button>
                </div>

                <p v-if="memoryV2Error" class="memory-v2-error" role="alert">{{ memoryV2Error }}</p>

                <form class="memory-v2-form" @submit.prevent="createMemoryV2Candidate">
                  <select
                    v-model="memoryV2Draft.memoryType"
                    class="settings-item__control settings-item__control--select memory-v2-form__type"
                    :disabled="memoryV2Creating"
                  >
                    <option v-for="item in memoryV2TypeOptions" :key="item.value" :value="item.value">
                      {{ item.label }}
                    </option>
                  </select>
                  <input
                    v-model="memoryV2Draft.key"
                    class="settings-item__control settings-item__control--text memory-v2-form__input"
                    type="text"
                    maxlength="64"
                    :placeholder="$t('settings.memoryKey')"
                    :disabled="memoryV2Creating"
                  />
                  <input
                    v-model="memoryV2Draft.value"
                    class="settings-item__control settings-item__control--text memory-v2-form__input"
                    type="text"
                    maxlength="240"
                    :placeholder="$t('settings.memoryValue')"
                    :disabled="memoryV2Creating"
                  />
                  <input
                    v-model.number="memoryV2Draft.confidence"
                    class="settings-item__control settings-item__control--text memory-v2-form__confidence"
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    :disabled="memoryV2Creating"
                  />
                  <button type="submit" class="btn btn-sm btn-primary" :disabled="memoryV2Creating">
                    {{ memoryV2Creating ? $t('settings.memoryWriting') : $t('settings.memoryWriteCandidate') }}
                  </button>
                </form>

                <pre v-if="memoryV2PlannerContext" class="memory-v2-context">{{ memoryV2PlannerContext }}</pre>

                <p v-if="memoryV2Loading" class="memory-v2-state muted">
                  {{ $t('settings.memoryLoading') }}
                </p>
                <ul v-else-if="memoryV2Records.length" class="memory-v2-list">
                  <li v-for="record in memoryV2Records" :key="record.memory_id" class="memory-v2-item">
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
                      />
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
                      <span>{{ record.source || $t('settings.memoryUnknown') }}</span>
                      <span>{{
                        $t('settings.memoryConfidence', {
                          value: Number(record.confidence || 0).toFixed(2),
                        })
                      }}</span>
                    </div>

                    <div class="memory-v2-actions">
                      <template v-if="memoryV2Edit.memoryId === record.memory_id">
                        <button
                          type="button"
                          class="btn btn-sm btn-primary"
                          :disabled="memoryV2BusyId === record.memory_id"
                          @click="saveMemoryV2Edit(record)"
                        >
                          {{ $t('settings.save') }}
                        </button>
                        <button
                          type="button"
                          class="btn btn-sm btn-secondary"
                          :disabled="memoryV2BusyId === record.memory_id"
                          @click="cancelMemoryV2Edit"
                        >
                          {{ $t('settings.cancel') }}
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
                          {{ $t('settings.confirm') }}
                        </button>
                        <button
                          v-if="record.status === 'pending'"
                          type="button"
                          class="btn btn-sm btn-secondary"
                          :disabled="memoryV2BusyId === record.memory_id"
                          @click="rejectMemoryV2(record)"
                        >
                          {{ $t('settings.reject') }}
                        </button>
                        <button
                          v-if="canEditMemoryV2(record)"
                          type="button"
                          class="btn btn-sm btn-secondary"
                          :disabled="memoryV2BusyId === record.memory_id"
                          @click="startMemoryV2Edit(record)"
                        >
                          {{ $t('settings.revise') }}
                        </button>
                        <button
                          v-if="record.status !== 'deleted'"
                          type="button"
                          class="btn btn-sm btn-danger"
                          :disabled="memoryV2BusyId === record.memory_id"
                          @click="deleteMemoryV2(record)"
                        >
                          {{ $t('settings.delete') }}
                        </button>
                      </template>
                    </div>
                  </li>
                </ul>
                <p v-else class="memory-v2-state muted">{{ $t('settings.memoryEmpty') }}</p>
              </div>
            </details>

            <details class="settings-card" data-tutorial-id="settings-basic" open>
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
                      <option v-for="theme in sidebarThemeOptions" :key="theme.value" :value="theme.value">
                        {{ theme.label }}
                      </option>
                    </select>
                  </div>

                  <div v-if="showCompanyBrandEditor" class="settings-item">
                    <span class="settings-item__icon settings-row__icon--amber" aria-hidden="true">
                      <i class="fa fa-building"></i>
                    </span>
                    <label class="settings-item__label" for="settings-company-brand">{{ $t('settings.companyBrand') }}</label>
                    <div class="settings-item__control-group">
                      <input
                        id="settings-company-brand"
                        v-model="companyBrandDraft"
                        class="settings-item__control settings-item__control--text"
                        type="text"
                        maxlength="64"
                        :placeholder="$t('settings.companyBrandPlaceholder')"
                      />
                      <button
                        type="button"
                        class="settings-item__save-btn"
                        :disabled="companyBrandSaving || !companyBrandDirty"
                        @click="saveCompanyBrand"
                      >
                        {{ companyBrandSaving ? $t('settings.saving') : $t('settings.save') }}
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
                    />
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
                    <span class="settings-item__label">{{ $t('settings.dataStorage') }}</span>
                    <span class="settings-item__value">{{ databaseStorageLabel }}</span>
                  </div>

                  <div v-if="desktopDatabaseVisible" class="settings-item settings-item--readonly">
                    <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
                      <i class="fa fa-folder-open-o"></i>
                    </span>
                    <span class="settings-item__label">{{ $t('settings.dbPath') }}</span>
                    <span class="settings-item__value settings-item__value--mono" :title="currentDbPath">{{ currentDbPath }}</span>
                  </div>

                  <div class="settings-item">
                    <span class="settings-item__icon settings-row__icon--violet" aria-hidden="true">
                      <i class="fa fa-cloud"></i>
                    </span>
                    <label class="settings-item__label" for="settings-ai-mode">{{ $t('settings.aiDeployMode') }}</label>
                    <select
                      id="settings-ai-mode"
                      v-model="deploymentMode"
                      class="settings-item__control settings-item__control--select"
                      @change="onDeploymentModeChange"
                    >
                      <option v-for="mode in displayDeploymentModes" :key="mode.id" :value="mode.id">
                        {{
                          $t('settings.deploymentModeOption', {
                            label: mode.label,
                            badge: mode.badge,
                          })
                        }}
                      </option>
                    </select>
                  </div>

                  <div class="settings-item settings-item--readonly">
                    <span class="settings-item__icon settings-row__icon--cyan" aria-hidden="true">
                      <i class="fa fa-random"></i>
                    </span>
                    <span class="settings-item__label">{{ $t('settings.networkPerf') }}</span>
                    <span class="settings-item__value">{{ deploymentModeBadge }}</span>
                  </div>

                  <div v-if="performanceModeSelected" class="settings-item settings-item--stacked">
                    <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
                      <i class="fa fa-database"></i>
                    </span>
                    <label class="settings-item__label" for="settings-postgres-url">{{ $t('settings.postgresConnection') }}</label>
                    <input
                      id="settings-postgres-url"
                      v-model="postgresUrlDraft"
                      class="settings-item__control settings-item__control--text settings-item__control--wide"
                      type="password"
                      autocomplete="off"
                      placeholder="postgresql+psycopg://user:password@host:5432/xcagi"
                    />
                    <p class="settings-item__hint">
                      {{ $t('settings.performanceModeHint') }}
                    </p>
                  </div>

                  <transition name="settings-fade">
                    <div
                      v-if="deploymentSaving || deploymentStatusMessage"
                      class="deployment-transition"
                      :class="{ 'deployment-transition--done': !deploymentSaving }"
                    >
                      <span v-if="deploymentSaving" class="deployment-transition__spinner" aria-hidden="true"></span>
                      <i v-else class="fa fa-check-circle deployment-transition__done" aria-hidden="true"></i>
                      <span>{{ deploymentSaving ? deploymentTransitionText : deploymentStatusMessage }}</span>
                    </div>
                  </transition>

                  <p v-if="deploymentSyncCommand" class="deployment-sync-command" :title="deploymentSyncCommand">
                    {{ deploymentSyncCommand }}
                  </p>
                </div>

                <details class="settings-card settings-card--nested" data-tutorial-id="settings-mobile-pairing" open>
                  <summary class="settings-row settings-row--nested">
                    <span class="settings-row__icon settings-row__icon--cyan" aria-hidden="true">
                      <i class="fa fa-qrcode"></i>
                    </span>
                    <span class="settings-row__label">{{ $t('settings.mobilePairing') }}</span>
                    <span class="settings-row__meta">{{ $t('settings.mobilePairingMeta') }}</span>
                    <span class="settings-row__arrow" aria-hidden="true"></span>
                  </summary>
                  <div class="settings-card__body settings-card__body--nested">
                    <MobilePairingQrCard />
                  </div>
                </details>

                <details v-if="!clientModsUiOff" class="settings-card settings-card--nested" data-tutorial-id="settings-extensions">
                  <summary class="settings-row settings-row--nested">
                    <span class="settings-row__icon settings-row__icon--orange" aria-hidden="true">
                      <i class="fa fa-puzzle-piece"></i>
                    </span>
                    <span class="settings-row__label">{{ $t('settings.extensions') }}</span>
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
                      {{ modRoutesRetrying ? $t('settings.retrying') : $t('settings.retryLoadMods') }}
                    </button>

                    <section v-if="hostBridgeMods.length" class="mod-fold-section">
                      <div class="mod-fold-section-head">
                        <span class="mod-ui-off-label">{{ $t('settings.hostBridgePack') }}</span>
                        <span class="mod-host-pack-stat">
                          {{
                            $t('settings.hostReady', {
                              installed: hostBridgeInstalledCount,
                              expected: hostBridgeExpectedCount,
                            })
                          }}
                        </span>
                      </div>
                      <div class="mod-host-pack-bar">
                        <button type="button" class="btn btn-secondary btn-sm" @click="hostPackExpanded = !hostPackExpanded">
                          {{ hostPackExpanded ? $t('settings.collapse') : $t('settings.inventory') }}
                        </button>
                        <button type="button" class="btn btn-link btn-sm" @click="goHostPackOnboarding">
                          {{ $t('settings.installAll') }}
                        </button>
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
                            {{ uninstallingModId === mod.id ? $t('settings.uninstalling') : $t('settings.uninstall') }}
                          </button>
                        </li>
                      </ul>
                    </section>

                    <section v-if="workflowEmployeeMods.length" class="mod-fold-section mod-fold-section--inline">
                      <span class="mod-ui-off-label">{{ $t('settings.workflowEmployees') }}</span>
                      <span class="muted">{{ $t('settings.workflowCount', { count: workflowEmployeeMods.length }) }}</span>
                      <button type="button" class="btn btn-link btn-sm" @click="goModStore">
                        {{ $t('settings.modStore') }}
                      </button>
                    </section>

                    <section class="mod-fold-section">
                      <div class="mod-fold-section-head">
                        <span class="mod-ui-off-label">{{ $t('settings.industryExtensions') }}</span>
                        <button type="button" class="btn btn-link btn-sm" @click="goModStore">
                          {{ $t('settings.modStore') }}
                        </button>
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
                            />
                            <span class="mod-single-text">{{ mod.name || mod.id }}</span>
                          </label>
                          <button
                            type="button"
                            class="btn btn-danger btn-sm mod-single-uninstall"
                            :disabled="uninstallingModId === mod.id || isProtectedClientModId(mod.id)"
                            @click="onUninstallMod(mod.id)"
                          >
                            {{ uninstallingModId === mod.id ? $t('settings.uninstalling') : $t('settings.uninstall') }}
                          </button>
                        </div>
                      </div>
                      <p v-else class="muted mod-single-empty">
                        <template v-if="loadError">{{ $t('settings.loadModsFailed') }}</template>
                        <template v-else>{{ $t('settings.noIndustryExt') }}</template>
                      </p>
                    </section>
                  </div>
                </details>

                <div class="settings-card__footer">
                  <button class="settings-primary-btn" type="button" @click="saveSettings" :disabled="loading || deploymentSaving">
                    {{
                      deploymentSaving ? $t('settings.switchingDeployMode') : loading ? $t('settings.saving') : $t('settings.saveSettings')
                    }}
                  </button>
                </div>
              </div>
            </details>

            <details class="settings-card">
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--amber" aria-hidden="true">
                  <i class="fa fa-flask"></i>
                </span>
                <span class="settings-row__label">{{ $t('settings.distillationVersions') }}</span>
                <span class="settings-row__meta">{{ $t('settings.trainingArtifacts') }}</span>
                <span class="settings-row__arrow" aria-hidden="true"></span>
              </summary>
              <div class="settings-card__body settings-card__body--compact">
                <p v-if="loadingVersions" class="muted">{{ $t('settings.versionsLoading') }}</p>
                <p v-else-if="versionsError" class="muted">{{ versionsError }}</p>
                <p v-else-if="versions.length === 0" class="muted">
                  {{ $t('settings.noVersions') }}
                </p>
                <div v-else class="settings-table-wrap">
                  <table class="data-table settings-table">
                    <thead>
                      <tr>
                        <th>{{ $t('settings.colFile') }}</th>
                        <th>{{ $t('settings.colDescription') }}</th>
                        <th>{{ $t('settings.colModified') }}</th>
                        <th>{{ $t('settings.colSize') }}</th>
                      </tr>
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
                <p class="muted settings-meta-line">
                  {{ $t('settings.sampleCountAccumulated', { count: sampleCount }) }}
                </p>
                <p v-if="sampleCountWarning" class="muted settings-meta-line">
                  {{ sampleCountWarning }}
                </p>
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
                  <label v-if="isDesktopShell" class="settings-about-autolaunch" :title="$t('settings.autoLaunchHint')">
                    <input
                      type="checkbox"
                      :checked="autoLaunch"
                      :disabled="autoLaunchBusy"
                      @change="onAutoLaunchChange(($event.target as HTMLInputElement).checked)"
                    />
                    <span>{{ $t('settings.desktopLaunchAtStartup') }}</span>
                  </label>
                  <p v-else class="muted settings-about-web-hint">
                    {{ $t('settings.updateWebHint') }}
                  </p>
                </div>
                <p
                  v-if="autoLaunchMessage"
                  class="settings-about-update-msg"
                  :class="{ 'is-error': autoLaunchMessage !== $t('settings.autoLaunchUpdated') }"
                >
                  {{ autoLaunchMessage }}
                </p>
                <p v-if="aboutUpdateMessage" class="settings-about-update-msg" :class="{ 'is-error': aboutUpdateError }">
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
import { onMounted, onActivated, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { useIndustryStore } from '../stores/industry'
import { readStoredSidebarTheme, applySidebarTheme } from '@/utils/sidebarTheme'
import { isProtectedClientModId } from '@/constants/protectedMods'
import HostModBridgeView from '@/components/HostModBridgeView.vue'
import MobilePairingQrCard from '@/components/settings/MobilePairingQrCard.vue'
import { useSettingsAccount } from '@/composables/settings/useSettingsAccount'
import { useSettingsMods } from '@/composables/settings/useSettingsMods'
import { useSettingsMemory } from '@/composables/settings/useSettingsMemory'
import { useSettingsBasics } from '@/composables/settings/useSettingsBasics'

const route = useRoute()
const modsStore = useModsStore()
const industryStore = useIndustryStore()

const {
  localUser,
  sessionValid,
  accountLoading,
  logoutLoading,
  companyBrandDraft,
  companyBrandSaving,
  avatarInputRef,
  avatarUploading,
  profileDisplayNameDraft,
  profileEmailDraft,
  profileSaving,
  isLoggedIn,
  isLocalAdmin,
  auditLogsLoading,
  auditLogs,
  auditLogsTotal,
  auditLogsError,
  profileBrandTitle,
  profileSubline,
  showCompanyBrandEditor,
  companyBrandDirty,
  avatarInitial,
  profileAvatarUrl,
  profileHomeSummary,
  profileFormDirty,
  loginRoute,
  loadAuditLogs,
  downloadAuditCsv,
  syncProfileDraftsFromUser,
  loadLocalUser,
  saveCompanyBrand,
  onAvatarClick,
  onAvatarFileChange,
  saveProfile,
  onLogout,
} = useSettingsAccount()

const {
  clientModsUiOff,
  loadError,
  isLoaded,
  mods,
  modRoutes,
  activeModId,
  modelPaymentBridgeInstalled,
  showModelPaymentBridge,
  uninstallingModId,
  hostPackExpanded,
  hostBridgeMods,
  hostBridgeInstalledCount,
  hostBridgeExpectedCount,
  selectableExtensionMods,
  workflowEmployeeMods,
  activeModMeta,
  activeModIndustry,
  modRoutesRetrying,
  modRoutesStatusText,
  showModRoutesRetry,
  modSettingsFoldMeta,
  installedAccountCustomMod,
  deliveryBrandName,
  industries,
  currentIndustry,
  currentIndustryUnit,
  currentIndustryConfig,
  currentIndustryLabel,
  currentIntentIndustryLabel,
  intentPackages,
  intentPackageEntries,
  systemDisplayName,
  aboutDisplayLine,
  openSettingsExtensions,
  goHostPackOnboarding,
  goModStore,
  retryModRoutesLoad,
  onActiveModChange,
  onUninstallMod,
  loadIndustries,
  loadCurrentIndustryDetail,
  updateIndustryKeywords,
  loadIntentPackages,
} = useSettingsMods()

const {
  memoryV2TypeOptions,
  memoryV2StatusFilters,
  memoryV2Records,
  memoryV2Summary,
  memoryV2PlannerContext,
  memoryV2Loading,
  memoryV2Creating,
  memoryV2BusyId,
  memoryV2Error,
  memoryV2StatusFilter,
  memoryV2TypeFilter,
  memoryV2Draft,
  memoryV2Edit,
  persyProfile,
  persyLoading,
  persyInferring,
  persyLastReason,
  persyUserId,
  persyFoldMeta,
  memoryV2UserId,
  memoryV2FoldMeta,
  loadPersyProfile,
  runPersyInfer,
  memoryV2TypeLabel,
  memoryV2StatusLabel,
  memoryV2EditableValue,
  memoryV2DisplayValue,
  parseMemoryV2InputValue,
  memoryV2Time,
  canEditMemoryV2,
  loadMemoryV2,
  createMemoryV2Candidate,
  confirmMemoryV2,
  rejectMemoryV2,
  startMemoryV2Edit,
  cancelMemoryV2Edit,
  saveMemoryV2Edit,
  deleteMemoryV2,
} = useSettingsMemory(localUser)

const {
  appLocale,
  onLocaleChange,
  loading,
  loadingVersions,
  aiMode,
  deploymentModes,
  deploymentMode,
  deploymentSaving,
  deploymentStatusMessage,
  deploymentSyncCommand,
  deploymentRestartRequired,
  postgresUrlDraft,
  postgresConfigured,
  assistantName,
  versions,
  sampleCount,
  versionsError,
  sampleCountWarning,
  aboutUpdateBusy,
  aboutUpdateMessage,
  aboutUpdateError,
  currentDbPath,
  databaseStorageLabel,
  desktopDatabaseVisible,
  isDeploymentModeId,
  normalizeDeploymentModeId,
  selectedDeploymentMode,
  deploymentModeBadge,
  performanceModeSelected,
  deploymentTransitionText,
  localizeDeploymentMode,
  displayDeploymentModes,
  selectedDisplayDeploymentMode,
  storageLabel,
  onDeploymentModeChange,
  loadDesktopDatabaseStatus,
  sidebarThemePreset,
  appVersionLabel,
  isDesktopShell,
  sidebarThemeOptions,
  selectedSidebarAccent,
  normalizedAssistantName,
  basicSettingsSummary,
  loadPreferences,
  saveSettings,
  saveDeploymentSettings,
  onSidebarThemeChange,
  loadDistillationVersions,
  onCheckForUpdates,
  autoLaunch,
  autoLaunchBusy,
  autoLaunchMessage,
  loadAutoLaunch,
  onAutoLaunchChange,
} = useSettingsBasics()

function scrollToSettingsSection() {
  const section = String(route.query.section || '').trim()
  if (!section) return
  nextTick(() => {
    const el = document.getElementById(`settings-${section}`) || document.querySelector(`[data-tutorial-id="settings-${section}"]`)
    if (el instanceof HTMLDetailsElement) {
      el.open = true
    } else if (el) {
      const parentDetails = el.closest('details.settings-card')
      if (parentDetails instanceof HTMLDetailsElement) parentDetails.open = true
    }
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

watch(() => route.query.section, scrollToSettingsSection)

onMounted(async () => {
  scrollToSettingsSection()
  await loadLocalUser()
  void loadAuditLogs()
  void loadDesktopDatabaseStatus()
  const uname = String(localUser.value?.username || '').trim()
  if (!modsStore.isLoaded) {
    await modsStore.initialize(true, {
      accountUsername: uname,
    })
  }
  sidebarThemePreset.value = readStoredSidebarTheme()
  applySidebarTheme(sidebarThemePreset.value)
  await industryStore.initialize()
  await loadIndustries()
  const piniaIndustryId = industryStore.currentIndustry?.id
  if (piniaIndustryId !== undefined && piniaIndustryId !== null && String(piniaIndustryId).trim() !== '') {
    currentIndustry.value = String(piniaIndustryId).trim()
  }
  await loadCurrentIndustryDetail()
  await loadIntentPackages()
  void loadPreferences()
  loadAutoLaunch()
  void loadMemoryV2()
  void loadPersyProfile()
  loadDistillationVersions()
})

onActivated(() => {
  void loadLocalUser().then(() => {
    loadMemoryV2()
    loadPersyProfile()
  })
})
</script>

<style scoped src="./SettingsView.css"></style>
