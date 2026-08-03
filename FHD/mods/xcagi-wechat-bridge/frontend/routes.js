/**
 * 微信集成 Mod — 前端路由。
 */

import { modView } from '@/router/modViews'

const MOD_ID = 'xcagi-wechat-bridge'
const PREFIX = `/mod/${MOD_ID}`

function route(pathSuffix, name, viewFile, title) {
  return {
    path: `${PREFIX}${pathSuffix}`,
    name,
    component: modView(MOD_ID, viewFile),
    meta: { title, mod: MOD_ID },
  }
}

const modRoutes = [
  route('/wechat-contacts', 'mod-wechat-contacts', 'WechatContactsView.vue', '微信联系人'),
]

const modMenu = [
  { id: 'mod-wechat-contacts', label: '微信联系人', icon: 'fa-weixin', path: `${PREFIX}/wechat-contacts` },
]

export { modRoutes, modMenu }