<script setup lang="ts">
import { useRoute } from 'vue-router'
const route = useRoute()
const isActive = (path: string) => route.path === path
</script>

<template>
  <nav class="navbar">
    <div class="nav-brand">&#9935; Alpha Miner</div>
    <div class="nav-links">
      <RouterLink to="/" :class="{ active: isActive('/') }">Dashboard</RouterLink>
      <RouterLink to="/alphas" :class="{ active: isActive('/alphas') }">Alphas</RouterLink>
      <RouterLink to="/generate" :class="{ active: isActive('/generate') }">Generate</RouterLink>
      <RouterLink to="/queue" :class="{ active: isActive('/queue') }">Queue</RouterLink>
      <RouterLink to="/pool" :class="{ active: isActive('/pool') }">Pool</RouterLink>
      <RouterLink to="/settings" :class="{ active: isActive('/settings') }">Settings</RouterLink>
    </div>
  </nav>
</template>

<style scoped>
.navbar {
  display: flex; align-items: center; gap: 32px;
  padding: 12px 24px; background: #1e2330; border-bottom: 1px solid #2d3748;
  position: sticky; top: 0; z-index: 100;
}
.nav-brand { font-size: 1.1rem; font-weight: 700; color: #60a5fa; white-space: nowrap; }
.nav-links { display: flex; gap: 4px; flex-wrap: wrap; }
.nav-links a {
  padding: 6px 14px; border-radius: 6px; color: #94a3b8; font-size: 0.9rem;
  transition: background 0.15s, color 0.15s;
}
.nav-links a:hover { background: #2d3748; color: #e2e8f0; text-decoration: none; }
.nav-links a.active { background: #1d4ed8; color: #fff; }
</style>
