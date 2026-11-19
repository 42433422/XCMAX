<template>
  <section class="persy-user-memory" :aria-label="$t('settings.userMemory')">
    <h2>{{ $t('settings.userMemory') }}</h2>
    <p v-if="!memoryV2UserId" class="memory-v2-state muted">{{ $t('settings.userMemorySignIn') }}</p>
    <template v-else>
      <div class="memory-v2-toolbar">
        <select
          v-model="memoryV2StatusFilter"
          :aria-label="$t('settings.memoryStatusAll')"
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
          :aria-label="$t('settings.memoryAllTypes')"
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

      <form class="memory-v2-form" @submit.prevent="saveMemoryV2">
        <select
          v-model="memoryV2Draft.memoryType"
          class="settings-item__control settings-item__control--select memory-v2-form__type"
          :disabled="mutatingMemory"
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
          :disabled="mutatingMemory"
        />
        <input
          v-model="memoryV2Draft.value"
          class="settings-item__control settings-item__control--text memory-v2-form__input"
          type="text"
          maxlength="240"
          :placeholder="$t('settings.memoryValue')"
          :disabled="mutatingMemory"
        />
        <button type="submit" class="btn btn-sm btn-primary" :disabled="mutatingMemory">
          {{ memoryV2Creating ? $t('settings.memorySaving') : $t('settings.memorySave') }}
        </button>
        <span v-if="memoryV2Saved && !memoryV2Draft.key && !memoryV2Draft.value" class="muted" role="status">
          {{ $t('settings.memorySaved') }}
        </span>
      </form>

      <p v-if="memoryV2Loading" class="memory-v2-state muted" role="status">
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
              :disabled="mutatingMemory"
            />
            <textarea
              v-model="memoryV2Edit.value"
              class="memory-v2-edit__textarea"
              rows="3"
              :disabled="mutatingMemory"
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
                :disabled="mutatingMemory"
                @click="saveMemoryV2Edit(record)"
              >
                {{ $t('settings.save') }}
              </button>
              <button
                type="button"
                class="btn btn-sm btn-secondary"
                :disabled="mutatingMemory"
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
                :disabled="mutatingMemory"
                @click="confirmMemoryV2(record)"
              >
                {{ $t('settings.confirm') }}
              </button>
              <button
                v-if="record.status === 'pending'"
                type="button"
                class="btn btn-sm btn-secondary"
                :disabled="mutatingMemory"
                @click="rejectMemoryV2(record)"
              >
                {{ $t('settings.reject') }}
              </button>
              <button
                v-if="canEditMemoryV2(record)"
                type="button"
                class="btn btn-sm btn-secondary"
                :disabled="mutatingMemory"
                @click="startMemoryV2Edit(record)"
              >
                {{ $t('settings.revise') }}
              </button>
              <button
                v-if="record.status !== 'deleted'"
                type="button"
                class="btn btn-sm btn-danger"
                :disabled="mutatingMemory"
                @click="deleteMemoryV2(record)"
              >
                {{ $t('settings.delete') }}
              </button>
            </template>
          </div>
        </li>
      </ul>
      <p v-else-if="!memoryV2Error" class="memory-v2-state muted">{{ $t('settings.memoryEmpty') }}</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onActivated, onDeactivated } from 'vue'
import { useUserMemory } from '@/composables/useUserMemory'

const {
  memoryV2UserId, memoryV2Records, memoryV2StatusFilters, memoryV2StatusFilter,
  memoryV2TypeOptions, memoryV2TypeFilter, memoryV2Loading, memoryV2Error,
  memoryV2Draft, memoryV2Creating, memoryV2Edit, memoryV2Saved, mutatingMemory,
  loadMemoryV2, saveMemoryV2, confirmMemoryV2, rejectMemoryV2, startMemoryV2Edit,
  cancelMemoryV2Edit, saveMemoryV2Edit, deleteMemoryV2, memoryV2TypeLabel, memoryV2StatusLabel,
  memoryV2Time, memoryV2DisplayValue, canEditMemoryV2,
} = useUserMemory()

let needsRefresh = false
onDeactivated(() => { needsRefresh = true })
onActivated(() => {
  if (!needsRefresh) return
  needsRefresh = false
  void loadMemoryV2()
})
</script>

<style scoped src="./persy-user-memory.css"></style>
