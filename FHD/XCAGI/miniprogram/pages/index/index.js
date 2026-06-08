const api = require('../../api/index')
const app = getApp()

Page({
  data: {
    banners: [
      { id: 1, title: '智能采购平台', desc: 'AI 驱动 · 一站式采购', bg: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', btnText: '立即体验' },
      { id: 2, title: '新品上架', desc: '高品质涂料产品', bg: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' },
      { id: 3, title: '限时优惠', desc: '全场满减活动进行中', bg: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' },
    ],
    quickEntries: [
      { id: 1, icon: '📦', label: '全部商品', type: 'category', bgColor: 'linear-gradient(135deg, #e0f2fe, #bae6fd)' },
      { id: 2, icon: '🔥', label: '热销排行', type: 'hot', bgColor: 'linear-gradient(135deg, #fff1f0, #ffccc7)' },
      { id: 3, icon: '🆕', label: '新品上市', type: 'new', bgColor: 'linear-gradient(135deg, #f6ffed, #d9f7be)' },
      { id: 4, icon: '💰', label: '特价专区', type: 'sale', badge: 'HOT', bgColor: 'linear-gradient(135deg, #fffbe6, #ffe58f)' },
      { id: 5, icon: '🤖', label: 'AI助手', type: 'ai', bgColor: 'linear-gradient(135deg, #f9f0ff, #efdbff)' },
      { id: 6, icon: '📋', label: '我的订单', type: 'order', bgColor: 'linear-gradient(135deg, #e6f7ff, #91caff)' },
      { id: 7, icon: '⭐', label: '我的收藏', type: 'favorite', bgColor: 'linear-gradient(135deg, #fff0f6, #ffadd2)' },
      { id: 8, icon: '🎁', label: '优惠活动', type: 'promo', bgColor: 'linear-gradient(135deg, #fcffe6, #eaff8f)' },
    ],
    products: [],
    loading: false,
    page: 1,
    hasMore: true,
    unreadCount: 0,
  },

  onShow() {
    if (!app.globalData.isLoggedIn) this.wxLogin()
    this.loadBanners()
    this.loadProducts()
    this.loadUnreadCount()
  },

  onPullDownRefresh() {
    this.setData({ page: 1, hasMore: true, products: [] })
    this.loadProducts()
    wx.stopPullDownRefresh()
  },

  onReachBottom() {
    if (this.data.hasMore && !this.data.loading) this.loadProducts()
  },

  async wxLogin() {
    try {
      const loginRes = await new Promise(resolve => wx.login({ success: resolve }))
      const res = await api.login(loginRes.code)
      if (res.success) {
        app.setToken(res.data.token)
        app.globalData.userInfo = res.data.user
      }
    } catch (e) { console.error('登录失败:', e) }
  },

  loadBanners() {},
  async loadUnreadCount() {
    try {
      const res = await api.getUnreadCount()
      if (res.success) this.setData({ unreadCount: res.data.count })
    } catch (e) {}
  },

  async loadProducts() {
    if (this.data.loading) return
    this.setData({ loading: true })
    try {
      const res = await api.getProductList({ page: this.data.page, page_size: 10 })
      if (res.success) {
        const items = (res.data.items || []).map(p => ({
          ...p,
          price: Number(p.price).toFixed(2),
          isFav: false,
        }))
        const list = this.data.page === 1 ? items : [...this.data.products, ...items]
        this.setData({ products: list, hasMore: res.data.pagination.has_next, page: this.data.page + 1 })
      }
    } catch (e) { console.error(e) }
    finally { this.setData({ loading: false }) }
  },

  loadMoreProducts() { this.loadProducts() },

  goSearch() { wx.navigateTo({ url: '/pages/search/search' }) },
  goCategory() { wx.switchTab({ url: '/pages/category/category' }) },
  goMessage() { wx.navigateTo({ url: '/pages/message/list/list' }) },
  goDetail(e) { wx.navigateTo({ url: `/pages/product/detail/detail?id=${e.currentTarget.dataset.id}` }) },
  onBannerTap(e) { if (e.currentTarget.dataset.url) wx.navigateTo({ url: e.currentTarget.dataset.url }) },

  onEntryTap(e) {
    const type = e.currentTarget.dataset.type
    const map = { category: () => wx.switchTab({ url: '/pages/category/category' }), hot: () => wx.navigateTo({ url: '/pages/search/search?sort=sales' }), new: () => wx.navigateTo({ url: '/pages/search/search?sort=newest' }), sale: () => wx.navigateTo({ url: '/pages/search/search?sort=price_asc' }), ai: () => wx.navigateTo({ url: '/pages/chat/chat' }), order: () => wx.switchTab({ url: '/pages/profile/index/index' }), favorite: () => wx.navigateTo({ url: '/pages/profile/favorite/favorite' }), promo: () => wx.showToast({ title: '敬请期待', icon: 'none' }) }
    ;(map[type] || map.category)()
  },

  async toggleFavorite(e) {
    if (!app.globalData.isLoggedIn) { wx.showToast({ title: '请先登录', icon: 'none' }); return }
    const id = e.currentTarget.dataset.id
    const products = this.data.products
    const idx = products.findIndex(p => p.id === id)
    if (idx === -1) return
    try {
      if (products[idx].isFav) {
        await api.removeFavorite(products[idx].favId)
        products[idx].isFav = false
      } else {
        const res = await api.addFavorite(id)
        products[idx].isFav = true
        products[idx].favId = res.data.fav_id
      }
      this.setData({ products })
      wx.showToast({ title: products[idx].isFav ? '已收藏' : '已取消', icon: 'none' })
    } catch (err) { wx.showToast({ title: '操作失败', icon: 'none' }) }
  },

  async quickAddCart(e) {
    if (!app.globalData.isLoggedIn) { wx.showToast({ title: '请先登录', icon: 'none' }); return }
    try {
      await api.addToCart(e.currentTarget.dataset.id, 1)
      wx.showToast({ title: '已加入购物车 ✓', icon: 'success' })
    } catch (err) { wx.showToast({ title: '添加失败', icon: 'none' }) }
  },
})
