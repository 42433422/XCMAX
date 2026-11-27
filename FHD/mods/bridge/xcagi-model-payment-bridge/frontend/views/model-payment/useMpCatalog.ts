import { computed } from 'vue';
import type { Ref } from 'vue';
import type { MarketAccountOverviewData, MarketLlmCatalogData, MarketLlmProvider } from '@/api/marketAccount';

type CatalogModelRow = {
  provider: string;
  id: string;
  runtime_selectable?: boolean;
  chat_compatible?: boolean;
  priceText?: string;
};

const DEFAULT_CATEGORY_LABELS: Record<string, string> = {
  llm: '语言大模型 (LLM)',
  vlm: '视觉 / 多模态 (VLM)',
  image: '图像生成',
  video: '视频生成',
  audio: '语音 / 音频',
  embedding: '向量嵌入',
  rerank: '重排 / 相关性',
  other: '其他',
};

function formatModelPrice(pricing: Record<string, unknown> | undefined): string {
  if (!pricing || typeof pricing !== 'object') return '';
  const inn = pricing.input_per_1k ?? pricing.input_price_per_1k ?? pricing.in;
  const out = pricing.output_per_1k ?? pricing.output_price_per_1k ?? pricing.out;
  const parts: string[] = [];
  if (inn != null && inn !== '') parts.push(`入¥${inn}/1k`);
  if (out != null && out !== '') parts.push(`出¥${out}/1k`);
  return parts.join(' · ');
}

export function formatMoney(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(2);
}

export function formatInteger(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return String(Math.floor(n));
}

export function providersFromOverview(data: MarketAccountOverviewData | null): MarketLlmProvider[] {
  const raw = data?.llm?.providers;
  if (!Array.isArray(raw)) return [];
  return raw.filter((p) => p && p.provider);
}

export function useMpCatalog(llmCatalog: Ref<MarketLlmCatalogData | null>) {
  const llmProviders = computed(() => (llmCatalog.value?.providers || []).filter(row => row?.provider));

  const modelsByCategory = computed(() => {
    const labels = {
      ...DEFAULT_CATEGORY_LABELS,
      ...(llmCatalog.value?.category_labels || {}),
    };
    const buckets = new Map<string, CatalogModelRow[]>();
    for (const provider of llmProviders.value) {
      const rows: Array<Record<string, unknown>> = provider.models_detailed?.length
        ? provider.models_detailed
        : (provider.models || []).map(id => ({ id, category: 'llm' }));
      for (const row of rows) {
        const id = String(row?.id || '').trim();
        if (!id) continue;
        const category = String(row.category || 'other').toLowerCase();
        const list = buckets.get(category) || [];
        list.push({ provider: provider.provider, id, runtime_selectable: row.runtime_selectable === true,
          chat_compatible: category === 'llm' || category === 'vlm',
          priceText: formatModelPrice(row.pricing as Record<string, unknown> | undefined),
        });
        buckets.set(category, list);
      }
    }
    return Object.keys(DEFAULT_CATEGORY_LABELS)
      .filter((c) => (buckets.get(c) || []).length > 0)
      .map((category) => ({
        category,
        label: labels[category] || category,
        models: buckets.get(category) || [],
      }));
  });

  return { llmProviders, modelsByCategory };
}
