/** 客服消息能力已并入「信息」；保留旧 URL 只用于兼容跳转。 */

const MOD_ID = 'xcagi-customer-service-bridge'
const PREFIX = `/mod/${MOD_ID}`

const modRoutes = [
  {
    path: `${PREFIX}/enterprise-customer-service`,
    name: 'mod-enterprise-customer-service',
    redirect: '/im',
    meta: { title: '信息', mod: MOD_ID },
  },
  {
    path: `${PREFIX}/internal-customer-service`,
    name: 'mod-internal-customer-service',
    redirect: '/im',
    meta: { title: '信息', mod: MOD_ID },
  },
]

const modMenu = []

export { modRoutes, modMenu }
