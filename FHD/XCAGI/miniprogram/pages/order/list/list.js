const api = require('../../../api/index')
const { getStatusText, getStatusColor, formatShortDate } = require('../../../utils/util')

Page({
  data: {
    tabs: [
      { key: 'all', label: '全部' },
      { key: 'pending', label: '待付款' },
      { key: 'paid', label: '待发货' },
      { key: 'shipped', label: '待收货' },
      { key: 'completed', label: '已完成' },
      { key: 'cancelled', label: '已取消' },
    ],
    orders: [],
    currentTab: 'all',
    loading: false,
    refreshing: false,
    page: 1,
    hasMore: true,
  },

  onShow() { this.loadOrders() },

  switchTab(e) {
    this.setData({ currentTab: e.currentTarget.dataset.tab, page: 1, orders: [], hasMore: true })
    this.loadOrders()
  },

  async loadOrders() {
    if (!this.data.hasMore || this.data.loading) return
    this.setData({ loading: true })
    try {
      const res = await api.getOrderList({ status: this.data.currentTab, page: this.data.page, page_size: 10 })
      if (res.success) {
        const orders = (res.data.items || []).map(o => ({
          ...o,
          _statusText: getStatusText(o.status),
          _statusColor: getStatusColor(o.status),
          created_at: formatShortDate(o.created_at),
        }))
        const list = this.data.page === 1 ? orders : [...this.data.orders, ...orders]
        this.setData({ orders: list, hasMore: res.data.pagination.has_next, page: this.data.page + 1 })
      }
    } catch (e) { console.error(e) }
    finally { this.setData({ loading: false, refreshing: false }) }
  },

  loadMore() { this.loadOrders() },

  onRefresh() {
    this.setData({ refreshing: true, page: 1, orders: [], hasMore: true })
    this.loadOrders()
  },

  goDetail(e) { wx.navigateTo({ url: `/pages/order/detail/detail?id=${e.currentTarget.dataset.id}` }) },

  async cancelOrder(e) {
    const that = this
    wx.showModal({ title: '确认取消', content: '确定要取消该订单吗？', async success(r) {
      if (r.confirm) { try { await api.cancelOrder(e.currentTarget.dataset.id); that.refresh() } catch (e) {} }
    }})
  },
  payOrder(e) { wx.showToast({ title: '跳转支付...', icon: 'none' }) },
  async confirmReceive(e) {
    try { await api.confirmOrder(e.currentTarget.dataset.id); wx.showToast({ title: '已确认收货 ✓' }); this.refresh() } catch (e) {}
  },
  async rebuyOrder(e) {
    try { await api.rebuyOrder(e.currentTarget.dataset.id); wx.showToast({ title: '已加入购物车 ✓', icon: 'success' }) } catch (e) {}
  },
  goShopping() { wx.switchTab({ url: '/pages/index/index' }) },
  refresh() { this.setData({ page: 1, orders: [] }); this.loadOrders() },
})
