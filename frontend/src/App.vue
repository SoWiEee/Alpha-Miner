<script setup lang="ts">
import NavBar from './components/NavBar.vue'
</script>

<template>
  <div class="app">
    <NavBar />
    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; }
.app { display: flex; flex-direction: column; min-height: 100vh; }
.main-content { flex: 1; padding: 24px; max-width: 1400px; margin: 0 auto; width: 100%; }
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
button { cursor: pointer; font-family: inherit; }
input, textarea, select { font-family: inherit; }
</style>
