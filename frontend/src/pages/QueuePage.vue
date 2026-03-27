<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useQueueStore } from '../stores/queue'
import ResultImportForm from '../components/ResultImportForm.vue'

const queue = useQueueStore()
const showExport = ref(false)
const exportData = ref<any[]>([])

onMounted(() => queue.refresh())

async function doExport() {
  exportData.value = await queue.fetchExport()
  showExport.value = true
}
</script>

<template>
  <div>
    <h1 class="page-title">Submission Queue</h1>

    <div class="toolbar">
      <button class="btn-secondary" @click="queue.refresh">&#8635; Refresh</button>
      <button class="btn-primary" @click="doExport">&#11015; Export Pending</button>
      <span class="count">{{ queue.pending.length }} pending · {{ queue.completed.length }} completed</span>
    </div>

    <!-- Queue table -->
    <div class="card mb">
      <h3>Queue</h3>
      <table class="table" v-if="queue.items.length">
        <thead>
          <tr><th>ID</th><th>Alpha ID</th><th>Status</th><th>Sharpe</th><th>Fitness</th><th>Submitted</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in queue.items" :key="item.id">
            <td class="mono">{{ item.id }}</td>
            <td class="mono">{{ item.alpha_id.slice(0, 8) }}…</td>
            <td><span class="status-badge" :class="item.status">{{ item.status }}</span></td>
            <td>{{ item.sharpe?.toFixed(2) ?? '—' }}</td>
            <td>{{ item.fitness?.toFixed(2) ?? '—' }}</td>
            <td class="mono dim">{{ item.submitted_at ? new Date(item.submitted_at).toLocaleString() : '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">Queue is empty. <RouterLink to="/generate">Generate some alphas first.</RouterLink></div>
    </div>

    <!-- Export modal -->
    <div v-if="showExport" class="modal-overlay" @click.self="showExport = false">
      <div class="modal">
        <div class="modal-header">
          <h3>Export for WQ Brain</h3>
          <button class="close-btn" @click="showExport = false">&#10005;</button>
        </div>
        <div v-if="exportData.length === 0" class="empty">No pending alphas to export.</div>
        <pre v-else class="export-json">{{ JSON.stringify(exportData, null, 2) }}</pre>
      </div>
    </div>

    <!-- Import form -->
    <ResultImportForm />
  </div>
</template>

<style scoped>
.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; color: #e2e8f0; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.count { color: #64748b; font-size: 0.85rem; }
.card { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
.card h3 { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 12px; }
.mb { margin-bottom: 20px; }
.table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.table th { padding: 10px 12px; text-align: left; border-bottom: 2px solid #2d3748; color: #94a3b8; font-weight: 600; }
.table td { padding: 9px 12px; border-bottom: 1px solid #1a202c; }
.mono { font-family: monospace; font-size: 0.8rem; }
.dim { color: #64748b; }
.empty { color: #64748b; font-size: 0.875rem; }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
.status-badge.pending { background: #3b2f1f; color: #fcd34d; }
.status-badge.submitted { background: #1e3a5f; color: #93c5fd; }
.status-badge.completed { background: #064e3b; color: #6ee7b7; }
.status-badge.failed { background: #3b1f1f; color: #fca5a5; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 200; }
.modal { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 24px; max-width: 700px; width: 90%; max-height: 80vh; display: flex; flex-direction: column; }
.modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.modal-header h3 { font-size: 1rem; font-weight: 600; color: #e2e8f0; }
.close-btn { background: none; border: none; color: #64748b; font-size: 1.2rem; cursor: pointer; }
.export-json { font-family: monospace; font-size: 0.75rem; color: #a78bfa; overflow: auto; flex: 1; white-space: pre; }
</style>
