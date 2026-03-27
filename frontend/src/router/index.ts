import { createRouter, createWebHashHistory } from 'vue-router'
import DashboardPage from '../pages/DashboardPage.vue'
import AlphasPage from '../pages/AlphasPage.vue'
import GeneratePage from '../pages/GeneratePage.vue'
import QueuePage from '../pages/QueuePage.vue'
import PoolPage from '../pages/PoolPage.vue'
import SettingsPage from '../pages/SettingsPage.vue'

const routes = [
  { path: '/', component: DashboardPage, meta: { title: 'Dashboard' } },
  { path: '/alphas', component: AlphasPage, meta: { title: 'Alphas' } },
  { path: '/generate', component: GeneratePage, meta: { title: 'Generate' } },
  { path: '/queue', component: QueuePage, meta: { title: 'Queue' } },
  { path: '/pool', component: PoolPage, meta: { title: 'Pool' } },
  { path: '/settings', component: SettingsPage, meta: { title: 'Settings' } },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
