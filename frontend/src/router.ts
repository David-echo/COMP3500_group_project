import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from './api'

const routes = [
  { path: '/', redirect: '/elections' },
  { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
  { path: '/elections', component: () => import('./views/ElectionsView.vue') },
  { path: '/elections/:id/vote', component: () => import('./views/BallotView.vue') },
  { path: '/receipt', component: () => import('./views/ReceiptView.vue') },
  { path: '/admin', component: () => import('./views/AdminView.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (!to.meta.public && !getToken()) return { path: '/login' }
  return true
})

export default router
