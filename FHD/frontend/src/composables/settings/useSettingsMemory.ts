import { ref, computed, watch, reactive, type Ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { User } from '@/api/auth';
import { memoryV2Api, type MemoryV2Record, type MemoryV2Status, type MemoryV2Summary, type MemoryV2Type } from '@/api/memoryV2';
import { butlerProfileApi, type ButlerProfileView } from '@/api/butlerProfile';
import { resolveModeScopedChatUserId } from '@/composables/useChatDbTokenGate';
import { appAlert, appConfirm } from '@/utils/appDialog';
import { errorMessage } from './utils';

export function useSettingsMemory(localUser: Ref<User | null>) {
  const { t, locale } = useI18n();

  const memoryV2TypeOptions = computed<Array<{ value: MemoryV2Type; label: string }>>(() => [
    { value: 'preference', label: t('settings.memoryTypePreference') },
    { value: 'entity', label: t('settings.memoryTypeEntity') },
    { value: 'episodic', label: t('settings.memoryTypeEpisodic') },
  ]);
  const memoryV2StatusFilters = computed<Array<{ value: 'all' | MemoryV2Status; label: string }>>(() => [
    { value: 'all', label: t('settings.memoryStatusAll') },
    { value: 'pending', label: t('settings.memoryStatusPending') },
    { value: 'active', label: t('settings.memoryStatusActive') },
    { value: 'rejected', label: t('settings.memoryStatusRejected') },
    { value: 'deleted', label: t('settings.memoryStatusDeleted') },
  ]);
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

  // ========== 拟人 Persy 系统 ==========
  const persyProfile = ref<ButlerProfileView | null>(null);
  const persyLoading = ref(false);
  const persyInferring = ref(false);
  const persyLastReason = ref('');

  const persyUserId = computed(() => resolveModeScopedChatUserId());

  const persyFoldMeta = computed(() => {
    if (!persyProfile.value) return t('settings.persyFoldMetaEmpty');
    const identity = persyProfile.value.identity_composite || persyProfile.value.identity_primary || t('settings.persyUninitialized');
    const interactions = persyProfile.value.interaction_count || 0;
    return t('settings.persyFoldMeta', { identity, count: interactions });
  });

  async function loadPersyProfile() {
    persyLoading.value = true;
    try {
      const result = await butlerProfileApi.get(persyUserId.value);
      if (result.success === false) throw new Error(result.message || t('settings.persyLoadFailed'));
      persyProfile.value = result.profile || null;
    } catch {
      persyProfile.value = null;
    } finally {
      persyLoading.value = false;
    }
  }

  async function runPersyInfer() {
    persyInferring.value = true;
    persyLastReason.value = '';
    try {
      const result = await butlerProfileApi.infer({ userId: persyUserId.value });
      if (result.success === false) throw new Error(result.message || t('settings.persyInferFailed'));
      if (result.profile) persyProfile.value = result.profile;
      if (result.inference?.reasons?.length) {
        persyLastReason.value = result.inference.reasons[result.inference.reasons.length - 1];
      }
    } catch (e: unknown) {
      persyLastReason.value = e instanceof Error ? e.message : t('settings.persyInferFailed');
    } finally {
      persyInferring.value = false;
    }
  }

  const memoryV2UserId = computed(() => {
    const raw = localUser.value?.username || localUser.value?.id || 'default';
    return String(raw || 'default').trim() || 'default';
  });

  const memoryV2FoldMeta = computed(() => {
    const pending = Number(memoryV2Summary.value.by_status.pending || 0);
    const active = Number(memoryV2Summary.value.by_status.active || 0);
    return t('settings.memoryFoldMeta', { pending, active });
  });

  function memoryV2TypeLabel(type: unknown): string {
    return memoryV2TypeOptions.value.find((item) => item.value === type)?.label || String(type || t('settings.memoryUnknown'));
  }

  function memoryV2StatusLabel(status: unknown): string {
    return memoryV2StatusFilters.value.find((item) => item.value === status)?.label || String(status || t('settings.memoryUnknown'));
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
    return new Date(parsed).toLocaleString(locale.value === 'en-US' ? 'en-US' : 'zh-CN', {
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
      if (listResult.success === false) throw new Error(listResult.message || t('settings.memoryLoadFailed'));
      if (summaryResult.success === false) throw new Error(summaryResult.message || t('settings.memorySummaryFailed'));
      memoryV2Records.value = Array.isArray(listResult.memories) ? listResult.memories : [];
      memoryV2Summary.value = summaryResult.summary || listResult.summary || { total: 0, by_status: {}, by_type: {} };
      memoryV2PlannerContext.value = String(summaryResult.planner_context || '');
    } catch (e: unknown) {
      memoryV2Records.value = [];
      memoryV2PlannerContext.value = '';
      memoryV2Error.value = errorMessage(e, t('settings.memoryLoadFailed'));
    } finally {
      memoryV2Loading.value = false;
    }
  }

  async function createMemoryV2Candidate() {
    const key = memoryV2Draft.key.trim();
    const value = memoryV2Draft.value.trim();
    if (!key || !value) {
      await appAlert(t('settings.memoryFillKeyValue'));
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
      if (result.success === false) throw new Error(result.message || t('settings.memoryCreateFailed'));
      memoryV2Draft.key = '';
      memoryV2Draft.value = '';
      await loadMemoryV2();
    } catch (e: unknown) {
      memoryV2Error.value = errorMessage(e, t('settings.memoryCreateFailed'));
    } finally {
      memoryV2Creating.value = false;
    }
  }

  async function confirmMemoryV2(record: MemoryV2Record) {
    memoryV2BusyId.value = record.memory_id;
    memoryV2Error.value = '';
    try {
      const result = await memoryV2Api.confirm(record.memory_id, memoryV2UserId.value);
      if (result.success === false) throw new Error(result.message || t('settings.memoryConfirmFailed'));
      await loadMemoryV2();
    } catch (e: unknown) {
      memoryV2Error.value = errorMessage(e, t('settings.memoryConfirmFailed'));
    } finally {
      memoryV2BusyId.value = '';
    }
  }

  async function rejectMemoryV2(record: MemoryV2Record) {
    if (!(await appConfirm(t('settings.memoryRejectConfirm', { key: record.key }), { danger: true }))) return;
    memoryV2BusyId.value = record.memory_id;
    memoryV2Error.value = '';
    try {
      const result = await memoryV2Api.reject(record.memory_id, memoryV2UserId.value, 'settings_ui_rejected');
      if (result.success === false) throw new Error(result.message || t('settings.memoryRejectFailed'));
      await loadMemoryV2();
    } catch (e: unknown) {
      memoryV2Error.value = errorMessage(e, t('settings.memoryRejectFailed'));
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
      await appAlert(t('settings.memoryFillKey'));
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
      if (result.success === false) throw new Error(result.message || t('settings.memoryReviseFailed'));
      cancelMemoryV2Edit();
      await loadMemoryV2();
    } catch (e: unknown) {
      memoryV2Error.value = errorMessage(e, t('settings.memoryReviseFailed'));
    } finally {
      memoryV2BusyId.value = '';
    }
  }

  async function deleteMemoryV2(record: MemoryV2Record) {
    if (!(await appConfirm(t('settings.memoryDeleteConfirm', { key: record.key }), { danger: true }))) return;
    memoryV2BusyId.value = record.memory_id;
    memoryV2Error.value = '';
    try {
      const result = await memoryV2Api.remove(record.memory_id, memoryV2UserId.value, 'settings_ui_deleted');
      if (result.success === false) throw new Error(result.message || t('settings.memoryDeleteFailed'));
      if (memoryV2Edit.memoryId === record.memory_id) cancelMemoryV2Edit();
      await loadMemoryV2();
    } catch (e: unknown) {
      memoryV2Error.value = errorMessage(e, t('settings.memoryDeleteFailed'));
    } finally {
      memoryV2BusyId.value = '';
    }
  }

  watch(memoryV2UserId, () => {
    void loadMemoryV2();
  });

  watch(persyUserId, () => {
    void loadPersyProfile();
  });

  return {
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
  };
}
