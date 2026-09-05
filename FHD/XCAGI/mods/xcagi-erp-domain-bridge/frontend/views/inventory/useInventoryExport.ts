import { ref } from 'vue';
import { api } from '@/api';
import { downloadBlob, getFilenameFromDisposition } from '@/utils';

const XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

export function useInventoryExport(readFilters: () => Record<string, string>) {
  const exporting = ref(false);
  const exportMessage = ref('');
  const exportError = ref('');

  async function exportInventory() {
    if (exporting.value) return;
    exporting.value = true;
    exportMessage.value = '正在生成全部筛选结果，请稍候…';
    exportError.value = '';
    try {
      const response = await api.download('/api/inventory/export.xlsx', readFilters(), {
        timeoutMs: 60000,
      });
      if (
        !response.ok ||
        !(response.headers.get('content-type') || '').includes(XLSX_CONTENT_TYPE)
      ) {
        throw new Error('未收到有效的库存 Excel 文件，请稍后重试。');
      }
      const blob = await response.blob();
      if (!blob.size) throw new Error('库存导出文件为空，请稍后重试。');
      downloadBlob(
        blob,
        getFilenameFromDisposition(response.headers.get('content-disposition'), '库存明细.xlsx')
      );
      const count = Number(response.headers.get('x-inventory-row-count'));
      const scope =
        Number.isSafeInteger(count) && count > 0 ? `${count} 条库存明细` : '全部筛选结果的库存明细';
      exportMessage.value = `已生成${scope}，已发起下载。`;
    } catch (error) {
      exportMessage.value = '';
      exportError.value = error instanceof Error ? error.message : '库存导出失败，请稍后重试。';
    } finally {
      exporting.value = false;
    }
  }

  return { exporting, exportMessage, exportError, exportInventory };
}
