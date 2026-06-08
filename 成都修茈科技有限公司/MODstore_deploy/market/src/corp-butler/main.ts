import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import CorpButlerRoot from './CorpButlerRoot.vue'
import { useAgentStore } from '../stores/agent'
import { loadCorpBallPosition } from './corpBallPosition'

document.documentElement.dataset.workbenchTheme = 'light'

const initialPath =
  typeof window !== 'undefined' ? window.location.pathname + window.location.search : '/'

/** AgentChatHistory 等组件使用 useRoute()，官网独立 bundle 须挂载 memory router */
const corpRouter = createRouter({
  history: createMemoryHistory(initialPath),
  routes: [
    {
      path: '/:pathMatch(.*)*',
      name: 'corp-static',
      component: { template: '<div></div>' },
    },
  ],
})

async function bootCorpButler() {
  const mountEl = document.getElementById('xc-corp-butler-root')
  if (!mountEl) {
    console.warn('[xc-corp-butler] 未找到 #xc-corp-butler-root，管家未挂载')
    return
  }

  const pinia = createPinia()
  const app = createApp(CorpButlerRoot)
  app.use(pinia)
  app.use(corpRouter)
  await corpRouter.isReady()

  const store = useAgentStore(pinia)
  store.closePanel()
  const initial = loadCorpBallPosition()
  store.savePosition(initial.x, initial.y)

  app.mount(mountEl)
}

void bootCorpButler()
