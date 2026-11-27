<template>
  <details class="settings-card" :data-tutorial-id="`settings-${SETTINGS_ENTRIES.memory.id}`">
    <summary class="settings-row">
      <span class="settings-row__icon settings-row__icon--art" aria-hidden="true">
        <img class="settings-row__icon-art" :src="persyArtSrc" alt="" />
      </span>
      <span class="settings-row__label">{{ $t(SETTINGS_ENTRIES.memory.labelKey) }}</span>
      <span class="settings-row__meta">{{ persyFoldMeta }}</span>
      <span class="settings-row__arrow" aria-hidden="true"></span>
    </summary>

    <div class="settings-card__body settings-card__body--compact">
      <div class="persy-profile">
        <div v-if="persyError" class="memory-v2-error" role="alert">
          <p>{{ persyError }}</p>
          <button type="button" class="btn btn-sm btn-secondary" :disabled="persyLoading" @click="reloadPersyProfile">{{ $t('settings.refresh') }}</button>
        </div>
        <div v-if="persyLoading && !persyProfile" class="persy-profile__state muted">
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
        <div v-else-if="!persyError" class="persy-profile__state muted">
          {{ $t('settings.persyEmpty') }}
        </div>
      </div>

      <router-link class="btn btn-sm btn-secondary" :to="{ name: 'persy-knowledge', query: { space: 'user-memory' } }">
        {{ $t('settings.userMemory') }}
      </router-link>
    </div>
  </details>
</template>

<script setup lang="ts">
import { SETTINGS_ENTRIES } from './settingsNavigation'
import type { ButlerProfileView } from '@/api/butlerProfile'
import persyArtSrc from '@/assets/icons/settings/r2c1.png'

defineProps<{
  persyFoldMeta: string
  persyLoading: boolean
  persyError: string
  reloadPersyProfile: () => unknown
  persyProfile: ButlerProfileView | null
  persyInferring: boolean
  persyLastReason: string
  runPersyInfer: () => unknown
}>()
</script>

<style scoped src="../SettingsView.css"></style>
