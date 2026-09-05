import type { EtlRun } from '@/api/etl'
import { useProductsStore, type ProductReadScope } from '@/stores/products'

/** Cache freshness is independent from the business outcome, including partial writes and failed rollbacks. */
export function createEtlProductInvalidation() {
  const products = useProductsStore()
  const observed = new Map<string, string>()
  let observedScope = ''
  const affectsProducts = (run: EtlRun) => ['products', 'customer_products', 'customers'].includes(run.target_type)
  function observe(run: EtlRun, scope: ProductReadScope): void {
    if (!products.isProductsScopeCurrent(scope) || !affectsProducts(run)) return
    const owner = `${scope.key}:${scope.epoch}`
    if (owner !== observedScope) { observed.clear(); observedScope = owner }
    if (!(run.summary.executed > 0 || run.rollback_status)) return
    const signature = JSON.stringify([run.status, run.summary.executed, run.executed_at, run.rollback_status, run.receipt?.rollback])
    if (observed.get(run.id) === signature) return
    observed.set(run.id, signature)
    products.invalidateProducts(scope)
  }
  async function read(request: () => Promise<EtlRun>): Promise<EtlRun> {
    const scope = products.captureProductsScope()
    const run = await request()
    observe(run, scope)
    return run
  }
  async function readMany(request: () => Promise<EtlRun[]>): Promise<EtlRun[]> {
    const scope = products.captureProductsScope()
    const runs = await request()
    runs.forEach(run => observe(run, scope))
    return runs
  }
  async function mutate(run: EtlRun, request: () => Promise<EtlRun>): Promise<EtlRun> {
    const scope = products.captureProductsScope()
    if (affectsProducts(run)) products.invalidateProducts(scope)
    try { return await request() }
    finally {
      // A rejected/lost response is not proof that no rows committed. Re-read; never mark business success here.
      if (affectsProducts(run)) products.invalidateProducts(scope)
    }
  }
  return { read, readMany, mutate }
}
