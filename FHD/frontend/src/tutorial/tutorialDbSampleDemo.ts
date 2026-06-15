import { customersApi } from '@/api/customers'
import { productsApi } from '@/api/products'
import { TUTORIAL_SAMPLE_NAME_PREFIX } from '@/constants/tutorialSamples'
import { sleep } from './demoHelpers'

const PREFIX = TUTORIAL_SAMPLE_NAME_PREFIX
const TUTORIAL_UNIT = `${PREFIX}演示单位`
const TUTORIAL_DB_IDS_KEY = 'xcagi_tutorial_db_sample_ids'

export type TutorialDbSampleIds = {
  customerIds: number[]
  productIds: number[]
}

function readStoredIds(): TutorialDbSampleIds {
  if (typeof window === 'undefined') return { customerIds: [], productIds: [] }
  try {
    const raw = sessionStorage.getItem(TUTORIAL_DB_IDS_KEY)
    if (!raw) return { customerIds: [], productIds: [] }
    const parsed = JSON.parse(raw) as TutorialDbSampleIds
    return {
      customerIds: (parsed.customerIds || []).map(Number).filter(Boolean),
      productIds: (parsed.productIds || []).map(Number).filter(Boolean),
    }
  } catch {
    return { customerIds: [], productIds: [] }
  }
}

function storeIds(ids: TutorialDbSampleIds): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.setItem(TUTORIAL_DB_IDS_KEY, JSON.stringify(ids))
  } catch {
    /* ignore */
  }
}

export function clearTutorialDbSampleIds(): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.removeItem(TUTORIAL_DB_IDS_KEY)
  } catch {
    /* ignore */
  }
}

export async function seedQuickStartTutorialDbSamples(): Promise<TutorialDbSampleIds> {
  const customerIds: number[] = []
  const productIds: number[] = []

  for (const name of [`${PREFIX}市场部`, `${PREFIX}研发部`]) {
    try {
      const r = await customersApi.createCustomer({
        name,
        contact_person: '教程样本',
      })
      const id = Number(r?.data?.id)
      if (id) customerIds.push(id)
    } catch {
      /* 可能已存在，稍后按名称勾选删除 */
    }
  }

  const products = [
    { model_number: 'TUT-A1', name: `${PREFIX}签字笔` },
    { model_number: 'TUT-A2', name: `${PREFIX}笔记本` },
    { model_number: 'TUT-B1', name: `${PREFIX}张三` },
    { model_number: 'TUT-B2', name: `${PREFIX}李四` },
  ]
  for (const p of products) {
    try {
      const r = await productsApi.createProduct({
        ...p,
        unit: TUTORIAL_UNIT,
        price: 1,
        quantity: 1,
      })
      const id = Number(r?.data?.id)
      if (id) productIds.push(id)
    } catch {
      /* ignore */
    }
  }

  const ids = { customerIds, productIds }
  storeIds(ids)
  return ids
}

export async function purgeQuickStartTutorialDbSamples(): Promise<void> {
  const stored = readStoredIds()
  if (stored.customerIds.length) {
    try {
      await customersApi.batchDeleteCustomers(stored.customerIds)
    } catch {
      /* fallback UI/API */
    }
  }
  if (stored.productIds.length) {
    try {
      await productsApi.batchDeleteProducts(stored.productIds)
    } catch {
      /* ignore */
    }
  }
  clearTutorialDbSampleIds()
}

function selectRowsWithPrefix(containerSelector: string, prefix: string): number {
  const root = document.querySelector(containerSelector)
  if (!root) return 0
  let count = 0
  root.querySelectorAll('tbody tr').forEach((tr) => {
    const text = (tr.textContent || '').trim()
    if (!text.includes(prefix)) return
    const cb = tr.querySelector<HTMLInputElement>('input[type="checkbox"]')
    if (cb && !cb.checked) {
      cb.click()
      count += 1
    }
  })
  return count
}

async function confirmBatchDeleteDialog(): Promise<void> {
  await sleep(350)
  const btn = document.querySelector<HTMLElement>(
    '.confirm-dialog-footer .btn-danger, .confirm-dialog .btn-danger',
  )
  btn?.click()
}

export async function runQuickStartDeleteCustomersDemo(): Promise<void> {
  await sleep(500)
  selectRowsWithPrefix('#view-customers', PREFIX)
  await sleep(300)
  const batchBtn = document.querySelector<HTMLElement>(
    '#view-customers .customers-header-actions .btn-danger, #view-customers .btn-danger',
  )
  if (batchBtn) {
    batchBtn.click()
    await confirmBatchDeleteDialog()
  }
  const stored = readStoredIds()
  if (stored.customerIds.length) {
    try {
      await customersApi.batchDeleteCustomers(stored.customerIds)
    } catch {
      /* ignore */
    }
  }
  storeIds({ ...stored, customerIds: [] })
}

export async function runQuickStartDeleteProductsDemo(): Promise<void> {
  await sleep(500)
  const unitSelect = document.querySelector<HTMLSelectElement>('#view-products .search-box select')
  if (unitSelect) {
    const hasUnit = Array.from(unitSelect.options).some((o) => o.value === TUTORIAL_UNIT)
    if (!hasUnit) {
      const opt = document.createElement('option')
      opt.value = TUTORIAL_UNIT
      opt.textContent = TUTORIAL_UNIT
      unitSelect.appendChild(opt)
    }
    unitSelect.value = TUTORIAL_UNIT
    unitSelect.dispatchEvent(new Event('change', { bubbles: true }))
    await sleep(800)
  }
  selectRowsWithPrefix('#view-products', PREFIX)
  await sleep(300)
  const batchBtn = document.querySelector<HTMLElement>('#view-products .page-header .btn-danger')
  if (batchBtn) {
    batchBtn.click()
    await confirmBatchDeleteDialog()
  }
  const stored = readStoredIds()
  if (stored.productIds.length) {
    try {
      await productsApi.batchDeleteProducts(stored.productIds)
    } catch {
      /* ignore */
    }
  }
  clearTutorialDbSampleIds()
}
