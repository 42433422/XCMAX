import { modView } from '@/router/modViews'

const modRoutes = [{
  path: '/mod/kellai/workspace',
  name: 'mod-kellai',
  component: modView('kellai', 'KellaiView.vue'),
  meta: { title: '客来来', mod: 'kellai' },
}]
const modMenu = [{ id: 'mod-kellai', label: '客来来', icon: 'fa-comments', path: '/kellai' }]
export { modRoutes, modMenu }
