<script setup lang="ts">
import { onMounted } from 'vue'
import { useGenerationStore } from '../stores/generation'
import GenerationPanel from '../components/GenerationPanel.vue'

const gen = useGenerationStore()
onMounted(() => gen.fetchRuns())
</script>

<template>
  <div>
    <h1 class="page-title">Generate</h1>
    <div class="layout">
      <div class="main">
        <GenerationPanel @done="gen.fetchRuns()" />
      </div>
      <div class="sidebar">
        <div class="card">
          <h3>Generation Runs</h3>
          <div v-if="gen.runs.length === 0" class="empty">No runs yet.</div>
          <div v-for="r in gen.recentRuns" :key="r.id" class="run-item">
            <span class="badge" :class="r.mode">{{ r.mode }}</span>
            <span class="run-info">{{ r.candidates_pass }}/{{ r.candidates_gen }} saved</span>
            <span v-if="r.finished_at" class="status-dot done">&#9679;</span>
            <span v-else class="status-dot running">&#9679;</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; color: #e2e8f0; }
.layout { display: grid; grid-template-columns: 1fr 280px; gap: 20px; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
.card { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
.card h3 { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 12px; }
.empty { color: #64748b; font-size: 0.875rem; }
.run-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #1a202c; font-size: 0.8rem; }
.run-item:last-child { border-bottom: none; }
.run-info { flex: 1; color: #94a3b8; }
.badge { padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
.badge.mutation { background: #1e3a5f; color: #93c5fd; }
.badge.llm { background: #3b1f5e; color: #c4b5fd; }
.badge.gp { background: #3b2f1f; color: #fcd34d; }
.status-dot { font-size: 0.6rem; }
.status-dot.done { color: #6ee7b7; }
.status-dot.running { color: #fbbf24; }
</style>
