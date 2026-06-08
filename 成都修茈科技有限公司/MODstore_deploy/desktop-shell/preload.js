'use strict'
const { contextBridge } = require('electron')

// 最小安全桥：仅暴露版本/平台只读信息，供 Web 端识别桌面客户端。
contextBridge.exposeInMainWorld('xcagiDesktop', {
  isDesktop: true,
  version: '10.0.0',
  platform: process.platform,
})
