/**
 * 里程碑 K / O：局域网授权页 — 物理视图在 Mod 包内。
 */

import { modView } from '@/router/modViews'

const MOD_ID = 'xcagi-lan-license-bridge'
const PREFIX = `/mod/${MOD_ID}`

const modRoutes = [
  {
    path: `${PREFIX}/lan-gate`,
    name: 'mod-lan-gate',
    component: modView(MOD_ID, 'LanGateView.vue'),
    meta: { title: '局域网授权', mod: MOD_ID, publicAccess: true, hideChrome: true },
  },
]

const modMenu = [
  {
    id: 'mod-lan-gate',
    label: '局域网授权',
    icon: 'fa-shield',
    path: `${PREFIX}/lan-gate`,
  },
]

export { modRoutes, modMenu }
