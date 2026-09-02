/**
 * 数据库管理 · 五类数据加载与提示条（由 AdminDatabaseView.vue 原单文件机械迁出，行为不变）。
 */
import { ref } from 'vue'
import { api } from '../../api'
import type {
  AdminUserRow,
  CatalogRow,
  RefundAdminRow,
  TransactionRow,
  WalletRow,
} from './adminDatabaseHelpers'
import { errMsg } from './adminDatabaseHelpers'

export function useAdminDbData() {
  const loadingDb = ref(false)
  const message = ref('')
  const messageOk = ref(true)

  const dbUsers = ref<AdminUserRow[]>([])
  const dbWallets = ref<WalletRow[]>([])
  const dbCatalog = ref<CatalogRow[]>([])
  const dbTransactions = ref<TransactionRow[]>([])
  const pendingRefunds = ref<RefundAdminRow[]>([])

  function flash(msg: string, ok = true) {
    message.value = msg
    messageOk.value = ok
    setTimeout(() => { message.value = '' }, 5000)
  }

  async function loadDatabase() {
    loadingDb.value = true
    try {
      const settled = await Promise.allSettled([
        api.refundsAdminPending(),
        api.adminListUsers(200, 0),
        api.adminListWallets(),
        api.adminListCatalog(),
        api.adminListTransactions(),
      ])
      const labels = ['退款待审', '用户', '钱包', '商品目录', '交易流水']
      const errs: string[] = []

      const [refundsR, usersR, walletsR, catalogR, txnsR] = settled

      if (refundsR.status === 'fulfilled') {
        pendingRefunds.value = (refundsR.value.refunds || []) as RefundAdminRow[]
      } else {
        pendingRefunds.value = []
        errs.push(`${labels[0]}: ${errMsg(refundsR.reason)}`)
      }
      if (usersR.status === 'fulfilled') {
        dbUsers.value = (usersR.value.users || []) as AdminUserRow[]
      } else {
        dbUsers.value = []
        errs.push(`${labels[1]}: ${errMsg(usersR.reason)}`)
      }
      if (walletsR.status === 'fulfilled') {
        dbWallets.value = (walletsR.value.items || []) as WalletRow[]
      } else {
        dbWallets.value = []
        errs.push(`${labels[2]}: ${errMsg(walletsR.reason)}`)
      }
      if (catalogR.status === 'fulfilled') {
        dbCatalog.value = (catalogR.value.items || []) as CatalogRow[]
      } else {
        dbCatalog.value = []
        errs.push(`${labels[3]}: ${errMsg(catalogR.reason)}`)
      }
      if (txnsR.status === 'fulfilled') {
        dbTransactions.value = (txnsR.value.items || []) as TransactionRow[]
      } else {
        dbTransactions.value = []
        errs.push(`${labels[4]}: ${errMsg(txnsR.reason)}`)
      }

      if (errs.length) {
        flash('部分数据加载失败（其余已显示）: ' + errs.join('；'), false)
      }
    } finally {
      loadingDb.value = false
    }
  }

  return {
    loadingDb,
    message,
    messageOk,
    dbUsers,
    dbWallets,
    dbCatalog,
    dbTransactions,
    pendingRefunds,
    flash,
    loadDatabase,
  }
}
