const api = require('../../api/index')
const app = getApp()

Page({
  data: {
    messages: [], inputText: '', isTyping: false, scrollToMsg: '', isOnline: true,
    intents: [
      { key: 'price', label: '💰 询价', example: '这个产品多少钱？' },
      { key: 'search', label: '🔍 找货', example: '有没有白色的底漆？' },
      { key: 'order', label: '📦 查单', example: '我的订单到哪了？' },
      { key: 'after_sales', label: '🛠 售后', example: '产品质量有问题怎么办？' },
    ],
  },

  onShow() { this.loadIntents() },

  async loadIntents() {
    try { const r = await api.aiIntents(); if (r.success) this.setData({ intents: r.data }) } catch (e) {}
  },

  onInput(e) { this.setData({ inputText: e.detail.value }) },

  async sendMessage() {
    const text = this.data.inputText.trim()
    if (!text || this.data.isTyping) return

    const now = new Date()
    const h = String(now.getHours()).padStart(2, '0')
    const m = String(now.getMinutes()).padStart(2, '0')

    const userMsg = { id: Date.now(), role: 'user', content: text, time: `${h}:${m}` }
    this.setData({
      messages: [...this.data.messages, userMsg],
      inputText: '',
      isTyping: true,
      scrollToMsg: `msg-${userMsg.id}`,
    })

    try {
      const res = await api.aiChat(text)
      if (res.success) {
        const now2 = new Date()
        const h2 = String(now2.getHours()).padStart(2, '0')
        const m2 = String(now2.getMinutes()).padStart(2, '0')
        const aiMsg = { id: Date.now() + 1, role: 'ai', content: res.data.reply, time: `${h2}:${m2}` }
        this.setData({
          messages: [...this.data.messages, aiMsg],
          isTyping: false,
          scrollToMsg: `msg-${aiMsg.id}`,
        })
      }
    } catch (e) {
      const now2 = new Date()
      const errMsg = { id: Date.now() + 1, role: 'ai', content: '抱歉，AI 服务暂时不可用，请稍后再试。', time: `${String(now2.getHours()).padStart(2,'0')}:${String(now2.getMinutes()).padStart(2,'0')}` }
      this.setData({ messages: [...this.data.messages, errMsg], isTyping: false })
    }
  },

  sendIntent(e) {
    this.setData({ inputText: e.currentTarget.dataset.text })
    this.sendMessage()
  },
})
