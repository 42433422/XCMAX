import { ref } from 'vue';

// 离线兜底套餐（与历史硬编码一致）：后端 /api/market/membership-plans 不可达时使用
export type MarketMembershipPlan = {
  id: string;
  tier: string;
  title: string;
  price: string;
  description: string;
  badge?: string;
  recommended?: boolean;
  features: string[];
};

export const FALLBACK_PLANS: MarketMembershipPlan[] = [
  {
    id: 'plan_basic',
    tier: 'vip',
    title: 'VIP',
    price: '9.90',
    description: '入门会员，解锁基础 AI 调用与平台能力。',
    features: ['基础 AI 对话', '基础模型额度', '可购买更多余额', '会员身份标识'],
  },
  {
    id: 'plan_pro',
    tier: 'vip_plus',
    title: 'VIP+',
    price: '29.90',
    description: '进阶会员，更高额度 + BYOK + 用量明细。',
    badge: '推荐',
    recommended: true,
    features: ['更高 AI 调用额度', 'BYOK 自有密钥', '优先模型接入', '用量明细'],
  },
  {
    id: 'plan_enterprise',
    tier: 'svip1',
    title: 'SVIP',
    price: '99.90',
    description: '企业级会员，含更高额度、团队与高级能力入口。',
    features: ['企业级 AI 额度', '高级功能优先体验', '团队协作入口', 'SVIP 身份标识'],
  },
];

export function useMpMembershipPlans() {
  // SSOT：会员套餐改从后端代理修茈市场 GET /api/payment/plans 读取（不再硬编码）
  const membershipPlans = ref<MarketMembershipPlan[]>([...FALLBACK_PLANS]);

  const PLAN_TIER_BY_ID: Record<string, string> = {
    plan_basic: 'vip',
    plan_pro: 'vip_plus',
    plan_enterprise: 'svip1',
  };

  async function loadMembershipPlans(): Promise<void> {
    try {
      const res = await fetch('/api/market/membership-plans', {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      if (!res.ok) return;
      const body = await res.json();
      const raw = body?.data?.plans;
      if (!Array.isArray(raw) || raw.length === 0) return;
      membershipPlans.value = raw.map((p: Record<string, unknown>) => {
        const id = String(p.id || '');
        return {
          id,
          tier: String(p.tier || PLAN_TIER_BY_ID[id] || ''),
          title: String(p.name || p.title || ''),
          price: String(p.price ?? ''),
          description: String(p.description || ''),
          recommended: id === 'plan_pro',
          badge: id === 'plan_pro' ? '推荐' : undefined,
          features: Array.isArray(p.features) ? p.features.map(String) : [],
        };
      });
    } catch {
      /* 保底用 FALLBACK_PLANS */
    }
  }

  return { membershipPlans, loadMembershipPlans };
}
