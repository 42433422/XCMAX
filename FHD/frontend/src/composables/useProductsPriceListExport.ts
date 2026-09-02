import { ref, type Ref } from 'vue';
import productsApi from '@/api/products';
import templatePreviewApi from '@/api/templatePreview';
import { appAlert } from '@/utils/appDialog';

/** Word 价目模板下拉项 */
interface WordTemplateOption {
  id: string;
  name: string;
}

/** 模板列表接口返回的单条模板（仅声明用到的字段） */
interface TemplateListItem {
  filename?: string;
  id?: string;
  slug?: string;
  name?: string;
  virtual?: boolean;
  category?: string;
}

interface TemplateListResponse {
  success?: boolean;
  templates?: TemplateListItem[];
}

/**
 * 产品价目表导出（Word/Excel）与 Word 价目模板选择。
 * 自 ProductsView 抽出，逻辑保持不变；导出参数依赖视图传入的 selectedUnit/searchQuery。
 */
export function useProductsPriceListExport(options: {
  selectedUnit: Ref<string>;
  searchQuery: Ref<string>;
}) {
  const { selectedUnit, searchQuery } = options;
  /** Word 价目表模板 slug，传给 /api/products/export.docx?template_id= */
  const selectedWordTemplateSlug = ref('');
  const wordTemplateOptions = ref<WordTemplateOption[]>([]);

  function docxSlugFromListTemplate(tpl?: TemplateListItem): string {
    const fn = String(tpl?.filename || '').trim();
    if (fn.toLowerCase().endsWith('.docx')) {
      return fn.replace(/\.docx$/i, '');
    }
    const raw = String(tpl?.id || '').replace(/^fs:/i, '').trim();
    if (raw.toLowerCase().endsWith('.docx')) {
      return raw.replace(/\.docx$/i, '');
    }
    return String(tpl?.slug || '').trim();
  }

  const exportPriceList = async () => {
    try {
      const params: Record<string, unknown> = {};
      if (selectedUnit.value) params.unit = selectedUnit.value;
      if (searchQuery.value) params.keyword = searchQuery.value;
      if (selectedWordTemplateSlug.value) params.template_id = selectedWordTemplateSlug.value;
      const response = await productsApi.exportUnitProductsDocx(params);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const contentDisposition = response.headers?.get('content-disposition') || '';
      let filename = '产品价格表.docx';
      const utf8NameMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
      const plainNameMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
      if (utf8NameMatch?.[1]) {
        try {
          filename = decodeURIComponent(utf8NameMatch[1]);
        } catch (_) {
          filename = utf8NameMatch[1];
        }
      } else if (plainNameMatch?.[1]) {
        filename = plainNameMatch[1];
      }
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('导出失败:', e);
      await appAlert('导出失败: ' + ((e as Error).message || '未知错误'));
    }
  };

  const exportPriceListExcel = async () => {
    try {
      const params: Record<string, unknown> = {};
      if (selectedUnit.value) params.unit = selectedUnit.value;
      if (searchQuery.value) params.keyword = searchQuery.value;
      const response = await productsApi.exportUnitProductsXlsx(params);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const contentDisposition = response.headers?.get('content-disposition') || '';
      let filename = '产品价格表.xlsx';
      const utf8NameMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
      const plainNameMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
      if (utf8NameMatch?.[1]) {
        try {
          filename = decodeURIComponent(utf8NameMatch[1]);
        } catch (_) {
          filename = utf8NameMatch[1];
        }
      } else if (plainNameMatch?.[1]) {
        filename = plainNameMatch[1];
      }
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Excel 导出失败:', e);
      await appAlert('Excel 导出失败: ' + ((e as Error).message || '未知错误'));
    }
  };

  const loadWordTemplateOptions = async () => {
    try {
      const res = (await templatePreviewApi.listTemplates()) as TemplateListResponse;
      if (!res?.success) return;
      const templates = Array.isArray(res.templates) ? res.templates : [];
      const slugSeen = new Set();
      const rows: WordTemplateOption[] = [];
      for (const tpl of templates) {
        if (!tpl || tpl.virtual || tpl.category !== 'word') continue;
        const fn = String(tpl.filename || '').toLowerCase();
        const nm = String(tpl.name || '').toLowerCase();
        const id = String(tpl.id || '').toLowerCase();
        const isPriceLike =
          fn.includes('price_list') ||
          fn.includes('价目') ||
          fn.includes('价格表') ||
          nm.includes('价目') ||
          nm.includes('价格表') ||
          id.includes('price_list');
        if (!isPriceLike) continue;
        const slug = docxSlugFromListTemplate(tpl);
        if (!slug || slugSeen.has(slug)) continue;
        slugSeen.add(slug);
        rows.push({
          id: slug,
          name: `${tpl.name || slug}（Word）`,
        });
      }
      if (!rows.length) {
        rows.push({ id: 'price_list_default', name: '产品价格表（Word 价目，默认）' });
      }
      wordTemplateOptions.value = rows;
      if (!rows.find((r) => String(r.id) === String(selectedWordTemplateSlug.value))) {
        selectedWordTemplateSlug.value = '';
      }
    } catch (e) {
      console.error('加载 Word 价目模板失败:', e);
    }
  };

  return {
    selectedWordTemplateSlug,
    wordTemplateOptions,
    docxSlugFromListTemplate,
    loadWordTemplateOptions,
    exportPriceList,
    exportPriceListExcel,
  };
}
