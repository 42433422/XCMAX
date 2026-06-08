const api = require('../../../api/index')
const app = getApp()
const { formatPrice } = require('../../../utils/util')

Page({
  data: {
    product: {},
    isFavorited: false,
    cartCount: 0,
    quantity: 1,
  },

  onLoad(options) {
    if (options.id) this.loadDetail(options.id)
  },

  onShow() { this.getCartCount() },

  async loadDetail(id) {
    wx.showNavigationBarLoading()
    try {
      const res = await api.getProductDetail(id)
      if (res.success) {
        this.setData({ product: res.data })
        wx.setNavigationBarTitle({ title: res.data.name })
        this.checkFavorite(id)
      }
    } catch (e) { console.error(e) }
    finally { wx.hideNavigationBarLoading() }
  },

  async checkFavorite(productId) {
    try {
      const res = await api.checkFavorite(productId)
      if (res.success) this.setData({ isFavorited: res.data.is_favorited })
    } catch (e) {}
  },

  async toggleFavorite() {
    if (!app.globalData.isLoggedIn) { wx.showToast({ title: '请先登录', icon: 'none' }); return }
    const productId = this.data.product.id
    try {
      if (this.data.isFavorited) {
        await api.removeFavorite(this.data.favId)
        this.setData({ isFavorited: false })
        wx.showToast({ title: '已取消收藏' })
      } else {
        const res = await api.addFavorite(productId)
        this.setData({ isFavorited: true, favId: res.data.fav_id })
        wx.showToast({ title: '收藏成功' })
      }
    } catch (e) { wx.showToast({ title: '操作失败', icon: 'none' }) }
  },

  async addToCart() {
    if (!app.globalData.isLoggedIn) { wx.showToast({ title: '请先登录', icon: 'none' }); return }
    try {
      await api.addToCart(this.data.product.id, this.data.quantity)
      wx.showToast({ title: '已加入购物车', icon: 'success' })
      this.getCartCount()
    } catch (e) { wx.showToast({ title: '添加失败', icon: 'none' }) }
  },

  buyNow() {
    this.addToCart().then(() => {
      wx.navigateTo({ url: '/pages/order/confirm/confirm?from=buy' })
    })
  },

  goCart() { wx.switchTab({ url: '/pages/cart/cart' }) },

  async getCartCount() {
    if (!app.globalData.isLoggedIn) return
    try {
      const res = await api.getCartList()
      if (res.success) {
        this.setData({ cartCount: res.data.summary.total_types })
      }
    } catch (e) {}
  },
})
