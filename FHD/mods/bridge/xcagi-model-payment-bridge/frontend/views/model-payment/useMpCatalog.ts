import { computed } from 'vue';
import type { Ref } from 'vue';
import type { MarketAccountOverviewData, MarketLlmCatalogData, MarketLlmProvider } from '@/api/marketAccount';

/** 模型目录展示逻辑（拆分自 ModelPaymentView.vue，逻辑不变） */

export type CatalogModelRow = {
  provider: string;
  id: string;
  category: string;
  runtime_selectable?: boolean;
  chat_compatible?: boolean;
  priceText?: string;
};

export const CATEGORY_ORDER = ['llm', 'vlm', 'image', 'video', 'audio', 'embedding', 'rerank', 'other'];

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

export function formatModelPrice(pricing: Record<string, unknown> | undefined): string {
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
  const raw = (data as any)?.llm?.providers;
  if (!Array.isArray(raw)) return [];
  return raw.filter((p) => p && p.provider);
}

export function providerModelCount(provider: MarketLlmProvider): number {
  if (Array.isArray(provider.models_detailed) && provider.models_detailed.length) {
    return provider.models_detailed.length;
  }
  return Array.isArray(provider.models) ? provider.models.length : 0;
}

export function providerInitials(provider: MarketLlmProvider): string {
  const label = (provider.label || provider.provider || '').trim();
  if (!label) return '?';
  const parts = label.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return label.slice(0, 2).toUpperCase();
}

export function providerState(provider: MarketLlmProvider): 'ok' | 'warn' {
  return provider.error ? 'warn' : 'ok';
}

export function useMpCatalog(llmCatalog: Ref<MarketLlmCatalogData | null>) {
  const llmProviders = computed<MarketLlmProvider[]>(() => (
    (llmCatalog.value?.providers || [])
      .filter((p) => p && p.provider)
      .sort((a, b) => providerModelCount(b) - providerModelCount(a))
  ));

  const modelsByCategory = computed(() => {
    const labels = {
      ...DEFAULT_CATEGORY_LABELS,
      ...(llmCatalog.value?.category_labels || {}),
    };
    const buckets = new Map<string, CatalogModelRow[]>();
    for (const provider of llmProviders.value) {
      const detailed = Array.isArray(provider.models_detailed) ? provider.models_detailed : [];
      if (detailed.length) {
        for (const row of detailed) {
          if (!row || typeof row !== 'object') continue;
          const id = String((row as Record<string, unknown>).id || '').trim();
          if (!id) continue;
          const category = String((row as Record<string, unknown>).category || 'other').toLowerCase();
          const pricing = (row as Record<string, unknown>).pricing;
          const list = buckets.get(category) || [];
          list.push({
            provider: provider.provider,
            id,
            category,
            runtime_selectable: Boolean((row as Record<string, unknown>).runtime_selectable),
            chat_compatible: category === 'llm' || category === 'vlm',
            priceText: formatModelPrice(
              pricing && typeof pricing === 'object'
                ? (pricing as Record<string, unknown>)
                : undefined,
            ),
          });
          buckets.set(category, list);
        }
        continue;
      }
      // 无 detailed 时退化为 models 列表，归入 llm
      for (const mid of provider.models || []) {
        const id = String(mid || '').trim();
        if (!id) continue;
        const list = buckets.get('llm') || [];
        list.push({
          provider: provider.provider,
          id,
          category: 'llm',
          chat_compatible: true,
        });
        buckets.set('llm', list);
      }
    }
    return CATEGORY_ORDER
      .filter((c) => (buckets.get(c) || []).length > 0)
      .map((category) => ({
        category,
        label: labels[category] || category,
        models: buckets.get(category) || [],
      }));
  });

  const catalogCategorySummary = computed(() => {
    if (!modelsByCategory.value.length) return '';
    return modelsByCategory.value
      .map((b) => `${b.label.split(' ')[0]}${b.models.length}`)
      .join(' · ');
  });

  return { llmProviders, modelsByCategory, catalogCategorySummary };
}
