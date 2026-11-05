type DeliverySeedPlan = {
  account_delivery_seed_packages?: Array<{ mod_id?: unknown }>
  deferred_account_custom_mod_ids?: string[]
  groups?: Array<{ items: Array<{ mod_id: string; runtime_mod_id?: string; delivery_deferred?: boolean }> }>
}

/** Do not seed packages still awaiting private delivery, including runtime aliases. */
export function deliverySeedModIds(plan: DeliverySeedPlan | null | undefined): string[] {
  const deferred = new Set(plan?.deferred_account_custom_mod_ids || [])
  for (const group of plan?.groups || []) {
    for (const item of group.items) {
      if (item.delivery_deferred || deferred.has(item.mod_id)) {
        deferred.add(item.mod_id)
        if (item.runtime_mod_id) deferred.add(item.runtime_mod_id)
      }
    }
  }
  return [...new Set((plan?.account_delivery_seed_packages || [])
    .map((row) => String(row?.mod_id || '').trim())
    .filter((id) => Boolean(id) && !deferred.has(id)))]
}
