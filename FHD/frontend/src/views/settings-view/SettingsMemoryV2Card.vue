<template>
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
          v-model="draft.memoryType"
          class="settings-item__control settings-item__control--select memory-v2-form__type"
          :disabled="memoryV2Creating"
        >
          <option v-for="item in memoryV2TypeOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
        <input
          v-model="draft.key"
          class="settings-item__control settings-item__control--text memory-v2-form__input"
          type="text"
          maxlength="64"
          :placeholder="$t('settings.memoryKey')"
          :disabled="memoryV2Creating"
        />
        <input
          v-model="draft.value"
          class="settings-item__control settings-item__control--text memory-v2-form__input"
          type="text"
          maxlength="240"
          :placeholder="$t('settings.memoryValue')"
          :disabled="memoryV2Creating"
        />
        <input
          v-model.number="draft.confidence"
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

          <div v-if="edit.memoryId === record.memory_id" class="memory-v2-edit">
            <input
              v-model="edit.key"
              class="settings-item__control settings-item__control--text memory-v2-edit__input"
              type="text"
              maxlength="64"
              :disabled="memoryV2BusyId === record.memory_id"
            />
            <textarea
              v-model="edit.value"
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
            <template v-if="edit.memoryId === record.memory_id">
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
</template>

<script setup lang="ts">
import type { MemoryV2Record, MemoryV2Status, MemoryV2Type } from '@/api/memoryV2'
import type { ButlerProfileView } from '@/api/butlerProfile'

const props = defineProps<{
  persyFoldMeta: string
  persyLoading: boolean
  persyProfile: ButlerProfileView | null
  persyInferring: boolean
  persyLastReason: string
  memoryV2StatusFilters: Array<{ value: 'all' | MemoryV2Status; label: string }>
  memoryV2TypeOptions: Array<{ value: MemoryV2Type; label: string }>
  memoryV2Loading: boolean
  memoryV2Error: string
  memoryV2Draft: { memoryType: MemoryV2Type; key: string; value: string; confidence: number }
  memoryV2Creating: boolean
  memoryV2PlannerContext: string
  memoryV2Records: MemoryV2Record[]
  memoryV2Edit: { memoryId: string; key: string; value: string }
  memoryV2BusyId: string
  runPersyInfer: () => unknown
  loadMemoryV2: () => unknown
  createMemoryV2Candidate: () => unknown
  memoryV2TypeLabel: (type: unknown) => string
  memoryV2StatusLabel: (status: unknown) => string
  memoryV2Time: (value: unknown) => string
  memoryV2DisplayValue: (value: unknown) => string
  canEditMemoryV2: (record: MemoryV2Record) => boolean
  saveMemoryV2Edit: (record: MemoryV2Record) => unknown
  cancelMemoryV2Edit: () => unknown
  confirmMemoryV2: (record: MemoryV2Record) => unknown
  rejectMemoryV2: (record: MemoryV2Record) => unknown
  startMemoryV2Edit: (record: MemoryV2Record) => unknown
  deleteMemoryV2: (record: MemoryV2Record) => unknown
}>()

// v-model 转发回父级；draft/edit 与父级共享同一 reactive 对象，模板内 v-model 直接生效
const memoryV2StatusFilter = defineModel<'all' | MemoryV2Status>('memoryV2StatusFilter', { required: true })
const memoryV2TypeFilter = defineModel<'all' | MemoryV2Type>('memoryV2TypeFilter', { required: true })
const draft = props.memoryV2Draft
const edit = props.memoryV2Edit
</script>

<style scoped src="../SettingsView.css"></style>
