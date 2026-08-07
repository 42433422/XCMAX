/**
 * IM 信息页「联系人选择器」的状态与交互逻辑。
 *
 * 自包含：拥有弹窗开关、联系人列表、搜索关键字与过滤结果，以及加载联系人。
 * 唯一外接点是把「接口可达」标记回调给会话连接状态（imApiReachable）。
 */
import { computed, ref, type Ref } from 'vue';
import { fetchImContacts, type ImContact } from '@/api/im';
import { showAppToast } from '@/composables/useAppToast';
import { isEnterpriseDedicatedContact } from './useMessengerEntries';

export type UseContactPickerParams = {
  /** 由会话 composable 持有的「IM 接口可达」标记，加载联系人成功时置位。 */
  imApiReachable: Ref<boolean>;
};

export function useContactPicker(params: UseContactPickerParams) {
  const { imApiReachable } = params;

  const contactPickerOpen = ref(false);
  const contacts = ref<ImContact[]>([]);
  const contactKeyword = ref('');
  const contactsLoading = ref(false);

  const filteredContacts = computed(() => {
    const kw = contactKeyword.value.trim().toLowerCase();
    const pool = contacts.value.filter((c) => !isEnterpriseDedicatedContact(c));
    if (!kw) return pool;
    return pool.filter(
      (c) =>
        c.display_name.toLowerCase().includes(kw) || c.username.toLowerCase().includes(kw),
    );
  });

  async function loadContacts(): Promise<void> {
    contactsLoading.value = true;
    try {
      contacts.value = await fetchImContacts();
      imApiReachable.value = true;
    } catch (error) {
      showAppToast(error instanceof Error ? error.message : '加载联系人失败', 'error');
    } finally {
      contactsLoading.value = false;
    }
  }

  async function openContactPicker(): Promise<void> {
    contactPickerOpen.value = true;
    contactKeyword.value = '';
    await loadContacts();
  }

  function closeContactPicker(): void {
    contactPickerOpen.value = false;
  }

  function onContactSearch(): void {
    /* 本地过滤，filteredContacts 已响应式处理 */
  }

  return {
    contactPickerOpen,
    contacts,
    contactKeyword,
    contactsLoading,
    filteredContacts,
    loadContacts,
    openContactPicker,
    closeContactPicker,
    onContactSearch,
  };
}