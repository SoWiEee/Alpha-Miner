<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { usePoolStore } from '../stores/pool'
import CorrelationHeatmap from '../components/CorrelationHeatmap.vue'
import FitnessHistogram from '../components/FitnessHistogram.vue'

const pool = usePoolStore()
const recomputing = ref(false)
const recomputeMsg = ref('')

onMounted(() => pool.refresh())

async function recompute() {
  recomputing.value = true
  recomputeMsg.value = ''
  try {
    await pool.recompute()
    recomputeMsg.value = `Done. Correlations updated.`
  } catch (e: any) {
    recomputeMsg.value = e?.response?.data?.detail ?? 'Recompute failed'
  } finally {
    recomputing.value = false
  }
}

const fmt = (v: number | null, d = 3) => v != null ? v.toFixed(d) : '—'
</script>

<template>
  <div>
    <h1 class="page-title">Pool</h1>

    <div class="toolbar">
      <button class="btn-primary" :disabled="recomputing" @click="recompute">
        {{ recomputing ? 'Recomputing…' : '&#8635; Recompute Correlations' }}
      </button>
      <button class="btn-secondary" @click="pool.refresh">Refresh</button>
      <span v-if="recomputeMsg" class="msg">{{ recomputeMsg }}</span>
    </div>

    <div class="grid-2 mb">
      <CorrelationHeatmap :correlations="pool.correlations" />
      <FitnessHistogram :alphas="pool.topAlphas" />
    </div>

    <!-- Top alphas table -->
    <div class="card">
      <h3>Top Alphas by Fitness</h3>
      <table class="table" v-if="pool.topAlphas.length">
        <thead>
          <tr><th>Expression</th><th>Source</th><th>Sharpe</th><th>Fitness</th><th>Returns</th><th>Turnover</th><th>Passed</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in pool.topAlphas" :key="a.id">
            <td class="expr" :title="a.expression">{{ a.expression }}</td>
            <td><span class="badge" :class="a.source">{{ a.source }}</span></td>
            <td>{{ fmt(a.sharpe, 2) }}</td>
            <td class="fitness">{{ fmt(a.fitness, 2) }}</td>
            <td>{{ fmt(a.returns, 3) }}</td>
            <td>{{ fmt(a.turnover, 3) }}</td>
            <td>{{ a.passed === null ? '—' : a.passed ? '✓' : '✗' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">No completed simulations yet.</div>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; color: #e2e8f0; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.msg { font-size: 0.875rem; color: #6ee7b7; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.mb { margin-bottom: 20px; }
.card { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
.card h3 { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 12px; }
.table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.table th { padding: 10px 12px; text-align: left; border-bottom: 2px solid #2d3748; color: #94a3b8; font-weight: 600; }
.table td { padding: 9px 12px; border-bottom: 1px solid #1a202c; }
.expr { font-family: monospace; font-size: 0.8rem; color: #a78bfa; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fitness { color: #60a5fa; font-weight: 600; }
.empty { color: #64748b; font-size: 0.875rem; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
.badge.seed { background: #064e3b; color: #6ee7b7; }
.badge.mutation { background: #1e3a5f; color: #93c5fd; }
.badge.llm { background: #3b1f5e; color: #c4b5fd; }
.badge.gp { background: #3b2f1f; color: #fcd34d; }
.badge.manual { background: #374151; color: #9ca3af; }
</style>
