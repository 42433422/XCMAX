const api = require('../../api/index')
const app = getApp()

Page({
  data: {
    items: [],
    summary: { total_amount: '0.00', selected_count: 0, total_types: 0 },
    loading: true,
    allSelected: false,
  },

  onShow() {
    if (app.globalData.isLoggedIn) this.loadCart()
    else this.setData({ loading: false })
  },

  async loadCart() {
    this.setData({ loading: true })
    try {
      const res = await api.getCartList()
      if (res.success) {
        const items = res.data.items || []
        const summary = res.data.summary
        const allSelected = items.length > 0 && items.every(i => i.selected)
        this.setData({ items, summary, allSelected, loading: false })
      }
    } catch (e) { console.error(e); this.setData({ loading: false }) }
  },

  async toggleSelect(e) {
    const productId = e.currentTarget.dataset.id
    const item = this.data.items.find(i => i.product_id === productId)
    if (!item) return
    try {
      await api.selectCart(productId, !item.selected)
      this.loadCart()
    } catch (e) {}
  },

  async toggleSelectAll() {
    const newState = !this.data.allSelected
    for (const item of this.data.items) {
      try { await api.selectCart(item.product_id, newState) } catch (e) {}
    }
    this.loadCart()
  },

  async increaseQty(e) {
    const id = e.currentTarget.dataset.id
    const item = this.data.items.find(i => i.product_id === id)
    if (item) {
      try { await api.updateCart(id, item.quantity + 1); this.loadCart() } catch (e) {}
    }
  },

  async decreaseQty(e) {
    const id = e.currentTarget.dataset.id
    const item = this.data.items.find(i => i.product_id === id)
    if (item && item.quantity > 1) {
      try { await api.updateCart(id, item.quantity - 1); this.loadCart() } catch (e) {}
    }
  },

  async deleteItem(e) {
    const id = e.currentTarget.dataset.id
    const that = this
    wx.showModal({
      title: '提示',
      content: '确定删除该商品？',
      async success(res) {
        if (res.confirm) {
          try { await api.removeFromCart(id); that.loadCart() } catch (e) {}
        }
      }
    })
  },

  goDetail(e) { wx.navigateTo({ url: `/pages/product/detail/detail?id=${e.currentTarget.dataset.id}` }) },
  goShopping() { wx.switchTab({ url: '/pages/index/index' }) },
  goCheckout() {
    if (!this.data.summary.selected_count) { wx.showToast({ title: '请选择商品', icon: 'none' }); return }
    wx.navigateTo({ url: '/pages/order/confirm/confirm' })
  },
})
