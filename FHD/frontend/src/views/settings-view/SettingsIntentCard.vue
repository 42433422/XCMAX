<template>
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
</template>

<script setup lang="ts">
defineProps<{
  currentIntentIndustryLabel: string
  currentIndustryUnit: string
  currentIndustryConfig: unknown
  intentPackageEntries: Array<{
    key: string
    name: string
    iconClass: string
    description: string
    enabled: boolean
    keywords: string[]
  }>
}>()
</script>

<style scoped src="../SettingsView.css"></style>
