<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { usePoolStore } from '../stores/pool'
import { useGenerationStore } from '../stores/generation'
import PoolHealthCard from '../components/PoolHealthCard.vue'

const pool = usePoolStore()
const gen = useGenerationStore()

let interval: ReturnType<typeof setInterval>

onMounted(async () => {
  await Promise.all([pool.refresh(), gen.fetchRuns()])
  interval = setInterval(() => pool.refresh(), 30_000)
})
onUnmounted(() => clearInterval(interval))

const fmtDate = (s: string) => new Date(s).toLocaleString()
</script>

<template>
  <div>
    <h1 class="page-title">Dashboard</h1>
    <div class="grid-2">
      <PoolHealthCard :status="pool.status" :last-updated="pool.lastUpdated" :loading="pool.loading" />
      <div class="card">
        <h3>Quick Links</h3>
        <ul class="links">
          <li><RouterLink to="/generate">&#8594; Generate new alphas</RouterLink></li>
          <li><RouterLink to="/queue">&#8594; View submission queue</RouterLink></li>
          <li><RouterLink to="/pool">&#8594; Pool health &amp; correlations</RouterLink></li>
          <li><RouterLink to="/alphas">&#8594; Browse all alphas</RouterLink></li>
          <li><a href="http://localhost:8000/docs" target="_blank">&#8594; Backend API docs</a></li>
        </ul>
      </div>
    </div>

    <div class="section">
      <h2>Recent Generation Runs</h2>
      <table class="table" v-if="gen.recentRuns.length">
        <thead>
          <tr>
            <th>#</th><th>Mode</th><th>Generated</th><th>Saved</th><th>Theme</th><th>Started</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in gen.recentRuns" :key="r.id">
            <td class="mono">{{ r.id }}</td>
            <td><span class="badge" :class="r.mode">{{ r.mode }}</span></td>
            <td>{{ r.candidates_gen }}</td>
            <td>{{ r.candidates_pass }}</td>
            <td class="dim">{{ r.llm_theme ?? '—' }}</td>
            <td class="mono dim">{{ fmtDate(r.started_at) }}</td>
            <td>
              <span v-if="r.finished_at" class="status done">&#10003; Done</span>
              <span v-else class="status running">&#9203; Running</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">No generation runs yet. <RouterLink to="/generate">Start generating.</RouterLink></div>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; color: #e2e8f0; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 24px; }
.card { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
.card h3 { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin-bottom: 12px; }
.links { list-style: none; display: flex; flex-direction: column; gap: 8px; }
.links li a { color: #60a5fa; font-size: 0.9rem; }
.section { margin-top: 24px; }
.section h2 { font-size: 1.1rem; font-weight: 600; color: #e2e8f0; margin-bottom: 12px; }
.table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.table th { padding: 10px 12px; text-align: left; border-bottom: 2px solid #2d3748; color: #94a3b8; font-weight: 600; }
.table td { padding: 9px 12px; border-bottom: 1px solid #1a202c; }
.table tr:hover td { background: #1e2330; }
.mono { font-family: monospace; font-size: 0.8rem; }
.dim { color: #64748b; }
.empty { color: #64748b; font-size: 0.9rem; padding: 12px 0; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
.badge.mutation { background: #1e3a5f; color: #93c5fd; }
.badge.llm { background: #3b1f5e; color: #c4b5fd; }
.badge.gp { background: #3b2f1f; color: #fcd34d; }
.status.done { color: #6ee7b7; font-size: 0.8rem; }
.status.running { color: #fbbf24; font-size: 0.8rem; }
</style>
