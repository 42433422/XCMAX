function formatPrice(price) {
  if (price === null || price === undefined) return '0.00'
  return Number(price).toFixed(2)
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const h = String(date.getHours()).padStart(2, '0')
  const min = String(date.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${d} ${h}:${min}`
}

function formatShortDate(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const m = date.getMonth() + 1
  const d = date.getDate()
  return `${m}月${d}日`
}

function getStatusText(status) {
  const map = {
    pending: '待付款',
    paid: '待发货',
    shipped: '待收货',
    completed: '已完成',
    cancelled: '已取消',
  }
  return map[status] || status
}

function getStatusColor(status) {
  const map = {
    pending: '#faad14',
    paid: '#1890ff',
    shipped: '#52c41a',
    completed: '#999',
    cancelled: '#ff4d4f',
  }
  return map[status] || '#333'
}

function debounce(fn, delay = 300) {
  let timer = null
  return function(...args) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn.apply(this, args), delay)
  }
}

module.exports = {
  formatPrice,
  formatDate,
  formatShortDate,
  getStatusText,
  getStatusColor,
  debounce,
}
