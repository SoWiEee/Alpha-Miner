<script setup lang="ts">
import type { PoolStatus } from '../api/client'
defineProps<{ status: PoolStatus | null; lastUpdated: string | null; loading: boolean }>()
const fmt = (v: number | null, d = 3) => v != null ? v.toFixed(d) : '—'
const fmtTime = (iso: string | null) => iso ? new Date(iso).toLocaleTimeString() : 'Never'
</script>

<template>
  <div class="card">
    <div class="card-header">
      <h3>Pool Health</h3>
      <span class="updated">Updated: {{ fmtTime(lastUpdated) }}</span>
    </div>
    <div v-if="loading" class="loading">Loading…</div>
    <div v-else-if="status" class="stats">
      <div class="stat">
        <div class="stat-value">{{ status.pool_size }}</div>
        <div class="stat-label">Pool Size</div>
      </div>
      <div class="stat">
        <div class="stat-value">{{ fmt(status.avg_sharpe, 2) }}</div>
        <div class="stat-label">Avg Sharpe</div>
      </div>
      <div class="stat">
        <div class="stat-value">{{ fmt(status.avg_fitness, 2) }}</div>
        <div class="stat-label">Avg Fitness</div>
      </div>
      <div class="stat">
        <div class="stat-value">{{ fmt(status.min_correlation, 2) }}</div>
        <div class="stat-label">Min Corr</div>
      </div>
      <div class="stat">
        <div class="stat-value">{{ fmt(status.max_correlation, 2) }}</div>
        <div class="stat-label">Max Corr</div>
      </div>
    </div>
    <div v-else class="empty">No pool data — submit some alphas first.</div>
  </div>
</template>

<style scoped>
.card { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.card-header h3 { font-size: 1rem; font-weight: 600; color: #e2e8f0; }
.updated { font-size: 0.75rem; color: #64748b; }
.stats { display: flex; gap: 24px; flex-wrap: wrap; }
.stat { text-align: center; min-width: 70px; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: #60a5fa; }
.stat-label { font-size: 0.75rem; color: #64748b; margin-top: 2px; }
.loading, .empty { color: #64748b; font-size: 0.9rem; padding: 8px 0; }
</style>
