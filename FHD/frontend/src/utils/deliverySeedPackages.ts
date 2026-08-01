type DeliverySeedPlan = {
  account_delivery_seed_packages?: Array<{ mod_id?: unknown }>;
};

/** 只拉配置了交付种子包的客户 Mod；员工扩展继续走标准安装链路。 */
export function deliverySeedModIds(plan: DeliverySeedPlan | null | undefined): string[] {
  return [
    ...new Set(
      (plan?.account_delivery_seed_packages || [])
        .map((row) => String(row?.mod_id || '').trim())
        .filter(Boolean)
    ),
  ];
}
