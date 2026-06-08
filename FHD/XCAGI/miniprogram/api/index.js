const { get, post, put, del } = require('../utils/request')

module.exports = {
  login(code) {
    return post('/api/mp/v1/auth/login', { code })
  },

  checkSession() {
    return get('/api/mp/v1/auth/session/check')
  },

  getUserInfo() {
    return get('/api/mp/v1/user/info')
  },

  updateUserInfo(data) {
    return put('/api/mp/v1/user/info', data)
  },

  getProductList(params) {
    return get('/api/mp/v1/product/list', params)
  },

  getProductDetail(id) {
    return get(`/api/mp/v1/product/detail/${id}`)
  },

  getProductCategories() {
    return get('/api/mp/v1/product/categories')
  },

  searchProducts(keyword, page) {
    return get('/api/mp/v1/product/search', { keyword, page })
  },

  getCartList() {
    return get('/api/mp/v1/cart/list')
  },

  addToCart(productId, quantity) {
    return post('/api/mp/v1/cart/add', { product_id: productId, quantity })
  },

  updateCart(productId, quantity) {
    return put('/api/mp/v1/cart/update', { product_id: productId, quantity })
  },

  removeFromCart(productId) {
    return del('/api/mp/v1/cart/remove', { product_id: productId })
  },

  selectCart(productId, selected) {
    return put('/api/mp/v1/cart/select', { product_id: productId, selected })
  },

  clearCart() {
    return del('/api/mp/v1/cart/clear')
  },

  createOrder(data) {
    return post('/api/mp/v1/order/create', data)
  },

  getOrderList(params) {
    return get('/api/mp/v1/order/list', params)
  },

  getOrderDetail(id) {
    return get(`/api/mp/v1/order/detail/${id}`)
  },

  cancelOrder(id) {
    return put(`/api/mp/v1/order/cancel/${id}`)
  },

  confirmOrder(id) {
    return put(`/api/mp/v1/order/confirm/${id}`)
  },

  rebuyOrder(id) {
    return post(`/api/mp/v1/order/rebuy/${id}`)
  },

  getAddressList() {
    return get('/api/mp/v1/address/list')
  },

  createAddress(data) {
    return post('/api/mp/v1/address/create', data)
  },

  updateAddress(id, data) {
    return put(`/api/mp/v1/address/update/${id}`, data)
  },

  deleteAddress(id) {
    return del(`/api/mp/v1/address/delete/${id}`)
  },

  setDefaultAddress(id) {
    return put(`/api/mp/v1/address/default/${id}`)
  },

  getFavoriteList(params) {
    return get('/api/mp/v1/favorite/list', params)
  },

  addFavorite(productId) {
    return post('/api/mp/v1/favorite/add', { product_id: productId })
  },

  removeFavorite(favId) {
    return del(`/api/mp/v1/favorite/remove/${favId}`)
  },

  checkFavorite(productId) {
    return get(`/api/mp/v1/favorite/check/${productId}`)
  },

  getMessageList(params) {
    return get('/api/mp/v1/message/list', params)
  },

  readMessage(msgId) {
    return put(`/api/mp/v1/message/read/${msgId}`)
  },

  readAllMessages() {
    return put('/api/mp/v1/message/read-all')
  },

  getUnreadCount() {
    return get('/api/mp/v1/message/unread-count')
  },

  aiChat(message, sessionId) {
    return post('/api/mp/v1/ai/chat', { message, session_id: sessionId })
  },

  getAiHistory(params) {
    return get('/api/mp/v1/ai/history', params)
  },

  submitFeedback(data) {
    return post('/api/mp/v1/feedback/submit', data)
  },

  getFeedbackList(params) {
    return get('/api/mp/v1/feedback/list', params)
  },
}
