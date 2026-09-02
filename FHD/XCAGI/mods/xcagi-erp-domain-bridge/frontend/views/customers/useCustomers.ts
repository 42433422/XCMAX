import { ref, onMounted, watch } from 'vue'
import customersApi from '@/api/customers'
import ordersApi from '@/api/orders'
import templatePreviewApi from '@/api/templatePreview'
import { appAlert } from '@/utils/appDialog'
import { useCoreNavLabel } from '@/composables/useCoreNavLabel'

// 拆分自 CustomersView.vue script（原第 200–508 行）；逻辑逐字迁移，行为不变。
// DataTable / ConfirmDialog 组件仍在入口 SFC 中导入。
export function useCustomers() {
  const pageNavTitle = useCoreNavLabel('customers');
  const productsNavLabel = useCoreNavLabel('products');
  const shipmentNavLabel = useCoreNavLabel('shipment-records');

  const customers = ref<any[]>([]);
  const purchaseUnitOptions = ref<any[]>([]);
  const selectedPurchaseUnit = ref('');
  const loading = ref(false);
  const selectedIds = ref<any[]>([]);
  const page = ref(1);
  const perPage = 20;
  const totalCustomers = ref(0);
  const hasMore = ref(false);
  const importFileInput = ref<any>(null);
  const showEditModal = ref(false);
  const showDeleteConfirm = ref(false);
  const showBatchDeleteConfirm = ref(false);
  const showAddModal = ref(false);
  const addForm = ref<Record<string, any>>({ customer_name: '', contact_person: '', contact_phone: '', address: '' });
  const itemToDelete = ref<any>(null);
  const templateOptions = ref<any[]>([]);
  const selectedTemplateId = ref('');
  const loadingTemplateOptions = ref(false);
  const editForm = ref<Record<string, any>>({
    id: null,
    customer_name: '',
    contact_person: '',
    contact_phone: '',
    address: ''
  });

  const columns = [
    { key: 'customer_name', label: '客户名称' },
    { key: 'contact_person', label: '联系人' },
    { key: 'contact_phone', label: '电话' },
    { key: 'address', label: '地址' }
  ];

  function normalizeUnitsPayload(data: any) {
    const list = data?.data || data?.units || [];
    return Array.isArray(list) ? list : [];
  }

  function unitOptionValue(unit: any) {
    if (unit == null) return '';
    if (typeof unit === 'string') return unit.trim();
    const v = unit.name ?? unit.symbol ?? unit.unit_name ?? unit.customer_name ?? unit.unitName;
    return String(v ?? '').trim();
  }

  function unitOptionLabel(unit: any) {
    return unitOptionValue(unit) || '(未命名单位)';
  }

  function unitOptionKey(unit: any, idx: number) {
    if (unit != null && typeof unit === 'object' && unit.id != null) return `pu-${unit.id}`;
    const v = unitOptionValue(unit);
    return v ? `pu-${v}` : `pu-idx-${idx}`;
  }

  async function loadPurchaseUnitOptions() {
    try {
      const data = await ordersApi.getShipmentRecordUnits();
      if (data?.success === false) throw new Error(data?.message || '加载单位失败');
      purchaseUnitOptions.value = normalizeUnitsPayload(data);
    } catch (e) {
      console.error('加载购买单位失败:', e);
      purchaseUnitOptions.value = [];
    }
  }

  const mergeCustomers = (existing: any[], incoming: any[]) => {
    const merged = [...existing];
    const seen = new Set(existing.map((x) => x?.id).filter((id) => id !== undefined && id !== null));
    for (const row of incoming) {
      const rowId = row?.id;
      if (rowId === undefined || rowId === null) {
        merged.push(row);
        continue;
      }
      if (!seen.has(rowId)) {
        seen.add(rowId);
        merged.push(row);
      }
    }
    return merged;
  };

  const loadCustomers = async ({ reset = true }: { reset?: boolean } = {}) => {
    if (loading.value) return;
    loading.value = true;
    try {
      const nextPage = reset ? 1 : page.value;
      const pu = String(selectedPurchaseUnit.value || '').trim();
      const data: any = await customersApi.getCustomers({
        page: nextPage,
        per_page: perPage,
        ...(pu ? { purchase_unit: pu } : {})
      });
      if (data.success) {
        const incoming = data.customers || data.data || [];
        const total = Number(data.total ?? incoming.length ?? 0);
        totalCustomers.value = Number.isFinite(total) ? total : incoming.length;

        if (reset) {
          customers.value = incoming;
        } else {
          customers.value = mergeCustomers(customers.value, incoming);
        }

        page.value = nextPage + 1;
        hasMore.value = customers.value.length < totalCustomers.value;
      }
    } catch (e) {
      console.error('加载客户失败:', e);
    } finally {
      loading.value = false;
    }
  };

  const loadMoreCustomers = async () => {
    if (!hasMore.value || loading.value) return;
    await loadCustomers({ reset: false });
  };

  const handleDelete = (customer: any) => {
    itemToDelete.value = customer;
    showDeleteConfirm.value = true;
  };

  const confirmDelete = async () => {
    if (!itemToDelete.value?.id) return;
    try {
      await customersApi.deleteCustomer(itemToDelete.value.id);
      await loadCustomers({ reset: true });
    } catch (e: any) {
      console.error('删除客户失败:', e);
      await appAlert('删除失败: ' + (e?.message || '未知错误'));
    }
    itemToDelete.value = null;
  };

  const handleBatchDelete = () => {
    showBatchDeleteConfirm.value = true;
  };

  const confirmBatchDelete = async () => {
    try {
      await customersApi.batchDeleteCustomers(selectedIds.value);
      selectedIds.value = [];
      await loadCustomers({ reset: true });
    } catch (e: any) {
      console.error('批量删除失败:', e);
      await appAlert('批量删除失败: ' + (e.message || '未知错误'));
    }
  };

  const openEditModal = (customer: any) => {
    editForm.value = {
      id: customer.id,
      customer_name: customer.customer_name || customer.unit_name || customer.name || '',
      contact_person: customer.contact_person || '',
      contact_phone: customer.contact_phone || '',
      address: customer.address || customer.contact_address || ''
    };
    showEditModal.value = true;
  };

  const closeEditModal = () => {
    showEditModal.value = false;
  };

  const openAddModal = () => {
    addForm.value = { customer_name: '', contact_person: '', contact_phone: '', address: '' };
    showAddModal.value = true;
  };

  const closeAddModal = () => {
    showAddModal.value = false;
  };

  const saveAdd = async () => {
    if (!addForm.value.customer_name?.trim()) {
      await appAlert('客户名称不能为空');
      return;
    }
    try {
      await customersApi.createCustomer({
        customer_name: addForm.value.customer_name,
        contact_person: addForm.value.contact_person,
        contact_phone: addForm.value.contact_phone,
        contact_address: addForm.value.address,
      } as any);
      await appAlert('客户创建成功');
      closeAddModal();
      await loadCustomers({ reset: true });
    } catch (e: any) {
      await appAlert('创建失败: ' + (e?.message || '未知错误'));
    }
  };

  const saveEdit = async () => {
    if (!editForm.value.id) return;
    if (!editForm.value.customer_name?.trim()) {
      await appAlert('客户名称不能为空');
      return;
    }
    try {
      await customersApi.updateCustomer(editForm.value.id, {
        customer_name: editForm.value.customer_name,
        contact_person: editForm.value.contact_person,
        contact_phone: editForm.value.contact_phone,
        contact_address: editForm.value.address
      } as any);
      await appAlert('保存成功');
      closeEditModal();
      await loadCustomers({ reset: true });
    } catch (e: any) {
      console.error('保存失败:', e);
      await appAlert('保存失败: ' + (e?.message || '未知错误'));
    }
  };

  const exportCustomers = async () => {
    if (!selectedTemplateId.value) {
      await appAlert('请先选择导出模板');
      return;
    }
    try {
      const response = await customersApi.exportCustomersXlsx(selectedTemplateId.value);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = '购买单位列表.xlsx';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      console.error('导出失败:', e);
      await appAlert('导出失败: ' + (e.message || '未知错误'));
    }
  };

  const loadTemplateOptions = async () => {
    loadingTemplateOptions.value = true;
    try {
      const res: any = await templatePreviewApi.listTemplates();
      if (!res?.success) return;
      const templates = Array.isArray(res.templates) ? res.templates : [];
      templateOptions.value = templates.filter((tpl: any) => {
        if (!tpl || tpl.virtual || tpl.category !== 'excel') return false;
        const scope = String(tpl.business_scope || '').trim();
        const type = String(tpl.template_type || '').trim();
        return scope === 'customers' || type === '客户';
      });
      if (!selectedTemplateId.value && templateOptions.value.length) {
        selectedTemplateId.value = String(templateOptions.value[0].id);
      }
    } catch (e) {
      console.error('加载客户导出模板失败:', e);
    } finally {
      loadingTemplateOptions.value = false;
    }
  };

  const triggerImport = () => {
    importFileInput.value?.click();
  };

  const handleImport = async (e: any) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const formData = new FormData();
      formData.append('file', file);
      const data = await customersApi.importCustomersExcel(formData);
      if (data.success) {
        await appAlert('导入成功！');
        await loadCustomers({ reset: true });
      }
    } catch (e: any) {
      console.error('导入失败:', e);
      await appAlert('导入失败: ' + (e.message || '未知错误'));
    } finally {
      e.target.value = '';
    }
  };

  watch(selectedPurchaseUnit, () => {
    loadCustomers({ reset: true });
  });

  onMounted(() => {
    loadPurchaseUnitOptions();
    loadCustomers({ reset: true });
    loadTemplateOptions();
  });

  return {
    pageNavTitle,
    productsNavLabel,
    shipmentNavLabel,
    customers,
    purchaseUnitOptions,
    selectedPurchaseUnit,
    loading,
    selectedIds,
    totalCustomers,
    hasMore,
    importFileInput,
    showEditModal,
    showDeleteConfirm,
    showBatchDeleteConfirm,
    showAddModal,
    addForm,
    itemToDelete,
    templateOptions,
    selectedTemplateId,
    loadingTemplateOptions,
    editForm,
    columns,
    unitOptionValue,
    unitOptionLabel,
    unitOptionKey,
    loadMoreCustomers,
    handleDelete,
    confirmDelete,
    handleBatchDelete,
    confirmBatchDelete,
    openEditModal,
    closeEditModal,
    openAddModal,
    closeAddModal,
    saveAdd,
    saveEdit,
    exportCustomers,
    triggerImport,
    handleImport,
  }
}
