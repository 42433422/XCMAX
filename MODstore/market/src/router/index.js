import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/register', name: 'register', component: () => import('../views/RegisterView.vue') },
  { path: '/catalog/:id', name: 'catalog-detail', component: () => import('../views/CatalogDetailView.vue') },
  { path: '/my-store', name: 'my-store', component: () => import('../views/MyStoreView.vue'), meta: { auth: true } },
  { path: '/wallet', name: 'wallet', component: () => import('../views/WalletView.vue'), meta: { auth: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  if (to.meta.auth && !localStorage.getItem('modstore_token')) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
})

export default router
