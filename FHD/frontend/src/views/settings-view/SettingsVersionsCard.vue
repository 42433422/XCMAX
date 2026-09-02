<template>
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
</template>

<script setup lang="ts">
import type { DistillationVersion } from '@/composables/settings/utils'

defineProps<{
  loadingVersions: boolean
  versionsError: string
  versions: DistillationVersion[]
  sampleCount: number
  sampleCountWarning: string
}>()
</script>

<style scoped src="../SettingsView.css"></style>
