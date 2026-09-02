// 拆分自 CatalogDetailView.vue：交互动作（关注作者/收藏/购买/下载/下架/评价/投诉），逻辑逐字迁移，行为不变。
import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../../api'
import { useAuthStore } from '../../stores/auth'
import type { CatalogItemDetail } from './catalogDetailTypes'
import { readAuthorFollowSet, writeAuthorFollowSet } from './catalogDetailTypes'

export interface CatalogActionDeps {
  item: Ref<CatalogItemDetail | null>
  catalogParamId: ComputedRef<string>
  loadReviews: () => Promise<void>
  loadEmployeeStatus: () => Promise<void>
}

export function useCatalogActions(deps: CatalogActionDeps) {
  const { item, catalogParamId, loadReviews, loadEmployeeStatus } = deps
  const router = useRouter()
  const authStore = useAuthStore()

  const buying = ref(false)
  const delisting = ref(false)
  const favBusy = ref(false)

  // 作者关注
  const authorFollowing = ref(false)

  const isAuthorSelf = computed(() => {
    const aid = item.value?.author?.id ?? item.value?.author_id
    const uid = authStore.user?.id
    return Boolean(aid && uid && Number(aid) === Number(uid))
  })

  function syncAuthorFollowing() {
    const aid = item.value?.author?.id ?? item.value?.author_id
    if (!aid) {
      authorFollowing.value = false
      return
    }
    authorFollowing.value = readAuthorFollowSet().has(Number(aid))
  }

  function toggleAuthorFollow() {
    const aid = item.value?.author?.id ?? item.value?.author_id
    if (!aid) return
    if (!localStorage.getItem('modstore_token')) {
      router.push({ name: 'login', query: { redirect: `/catalog/${catalogParamId.value}` } })
      return
    }
    const set = readAuthorFollowSet()
    const id = Number(aid)
    if (set.has(id)) set.delete(id)
    else set.add(id)
    writeAuthorFollowSet(set)
    authorFollowing.value = set.has(id)
  }

  async function toggleFavorite() {
    if (!item.value) return
    if (!localStorage.getItem('modstore_token')) {
      await router.push({ name: 'login', query: { redirect: `/catalog/${catalogParamId.value}` } })
      return
    }
    favBusy.value = true
    try {
      const r = await api.catalogToggleFavorite(catalogParamId.value)
      item.value.favorited = !!r.favorited
      if (item.value.creator_stats) {
        const delta = item.value.favorited ? 1 : -1
        const cur = Number(item.value.creator_stats.favorite_count ?? 0)
        item.value.creator_stats.favorite_count = Math.max(0, cur + delta)
      }
    } catch (e) {
      alert((e as Error)?.message || String(e))
    } finally {
      favBusy.value = false
    }
  }

  async function doBuy() {
    if (!localStorage.getItem('modstore_token')) {
      await router.push({
        name: 'login',
        query: { redirect: `/catalog/${catalogParamId.value}` },
      })
      return
    }
    const it = item.value
    if (!it) return

    if (it.price <= 0) {
      buying.value = true
      try {
        const res = await api.buyItem(catalogParamId.value)
        alert(res.message)
        item.value = (await api.catalogDetail(catalogParamId.value)) as CatalogItemDetail
        if (item.value.artifact === 'employee_pack' && item.value.purchased) {
          await loadEmployeeStatus()
        }
      } catch (e) {
        alert((e as Error)?.message || String(e))
      } finally {
        buying.value = false
      }
      return
    }

    buying.value = true
    try {
      const res = await api.paymentCheckout({
        item_id: Number(it.id),
        subject: it.name,
      })
      if (!res.ok) {
        alert(res.message || '下单失败')
        return
      }
      if (res.type === 'page' || res.type === 'wap') {
        window.location.href = res.redirect_url || ''
      } else if (res.type === 'precreate' || res.type === 'wechat_native') {
        await router.push({ name: 'checkout', params: { orderId: res.order_id } })
      } else {
        alert('未知的支付类型')
      }
    } catch (e) {
      alert((e as Error)?.message || String(e))
    } finally {
      buying.value = false
    }
  }

  async function doDownload() {
    try {
      await api.downloadItem(catalogParamId.value)
    } catch (e) {
      alert((e as Error)?.message || String(e))
    }
  }

  async function delistItem() {
    const it = item.value
    if (!it || delisting.value) return
    const ok = window.confirm(`确定下架「${it.name}」吗？下架后市场将不再展示该商品。`)
    if (!ok) return
    delisting.value = true
    try {
      await api.adminDeleteCatalog(it.id)
      await router.push({ name: 'ai-store' })
    } catch (e) {
      alert((e as Error)?.message || String(e))
    } finally {
      delisting.value = false
    }
  }

  function navigateToWorkflow() {
    router.push('/workflow')
  }

  // 评价
  const reviewRating = ref(5)
  const reviewContent = ref('')
  const reviewSubmitting = ref(false)

  async function submitReview() {
    if (!item.value || item.value.user_has_review) return
    reviewSubmitting.value = true
    try {
      await api.catalogSubmitReview(catalogParamId.value, reviewRating.value, reviewContent.value.trim())
      item.value.user_has_review = true
      reviewContent.value = ''
      await loadReviews()
    } catch (e) {
      alert((e as Error)?.message || String(e))
    } finally {
      reviewSubmitting.value = false
    }
  }

  // 投诉与申诉
  const complaintType = ref('plagiarism')
  const complaintReason = ref('')
  const complaintSubmitting = ref(false)
  const complaintPanelOpen = ref(false)

  function openComplaintPanel() {
    complaintPanelOpen.value = true
  }

  function customerServiceLink(scene = 'complaint') {
    const it = item.value
    return {
      name: 'customer-service',
      query: {
        scene,
        catalog_id: String(it?.id || catalogParamId.value || ''),
        pkg_id: it?.pkg_id || '',
        item_name: it?.name || '',
        material_category: it?.material_category || '',
        complaint_type: complaintType.value || '',
      },
    }
  }

  async function submitComplaint() {
    if (!item.value) return
    if (!localStorage.getItem('modstore_token')) {
      await router.push({ name: 'login', query: { redirect: `/catalog/${catalogParamId.value}` } })
      return
    }
    const reason = complaintReason.value.trim()
    if (reason.length < 4) {
      alert('请至少填写 4 个字的问题说明')
      return
    }
    complaintSubmitting.value = true
    try {
      await api.catalogSubmitComplaint(catalogParamId.value, complaintType.value, reason, {
        pkg_id: item.value.pkg_id,
        item_name: item.value.name,
        material_category: item.value.material_category,
      })
      complaintReason.value = ''
      item.value = (await api.catalogDetail(catalogParamId.value)) as CatalogItemDetail
      alert('已提交，建议继续进入 AI 客服补充证据材料。')
    } catch (e) {
      alert((e as Error)?.message || String(e))
    } finally {
      complaintSubmitting.value = false
    }
  }

  return {
    buying,
    delisting,
    favBusy,
    authorFollowing,
    isAuthorSelf,
    syncAuthorFollowing,
    toggleAuthorFollow,
    toggleFavorite,
    doBuy,
    doDownload,
    delistItem,
    navigateToWorkflow,
    reviewRating,
    reviewContent,
    reviewSubmitting,
    submitReview,
    complaintType,
    complaintReason,
    complaintSubmitting,
    complaintPanelOpen,
    openComplaintPanel,
    customerServiceLink,
    submitComplaint,
  }
}
