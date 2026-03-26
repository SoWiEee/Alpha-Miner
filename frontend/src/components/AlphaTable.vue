<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { alphasApi, type AlphaRead } from '../api/client'

const alphas = ref<AlphaRead[]>([])
const loading = ref(false)
const sourceFilter = ref('')
const sortKey = ref<'created_at' | 'source' | 'expression'>('created_at')
const sortDir = ref<'asc' | 'desc'>('desc')

const sources = computed(() => ['', ...new Set(alphas.value.map(a => a.source))])

const filtered = computed(() => {
  let list = alphas.value
  if (sourceFilter.value) list = list.filter(a => a.source === sourceFilter.value)
  list = [...list].sort((a, b) => {
    const va = a[sortKey.value], vb = b[sortKey.value]
    const cmp = (va ?? '') < (vb ?? '') ? -1 : (va ?? '') > (vb ?? '') ? 1 : 0
    return sortDir.value === 'asc' ? cmp : -cmp
  })
  return list
})

async function load() {
  loading.value = true
  try { alphas.value = (await alphasApi.list()).data }
  finally { loading.value = false }
}

function toggleSort(k: typeof sortKey.value) {
  if (sortKey.value === k) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  else { sortKey.value = k; sortDir.value = 'asc' }
}

onMounted(load)
defineExpose({ reload: load })
</script>

<template>
  <div>
    <div class="toolbar">
      <select v-model="sourceFilter" class="select">
        <option v-for="s in sources" :key="s" :value="s">{{ s || 'All sources' }}</option>
      </select>
      <button class="btn-secondary" @click="load">&#8635; Refresh</button>
      <span class="count">{{ filtered.length }} alphas</span>
    </div>
    <div v-if="loading" class="loading">Loading…</div>
    <table v-else class="table">
      <thead>
        <tr>
          <th @click="toggleSort('source')" class="sortable">Source {{ sortKey==='source' ? (sortDir==='asc'?'↑':'↓') : '' }}</th>
          <th @click="toggleSort('expression')" class="sortable">Expression {{ sortKey==='expression' ? (sortDir==='asc'?'↑':'↓') : '' }}</th>
          <th>ID</th>
          <th>Filter</th>
          <th @click="toggleSort('created_at')" class="sortable">Created {{ sortKey==='created_at' ? (sortDir==='asc'?'↑':'↓') : '' }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in filtered" :key="a.id" :title="a.rationale ?? ''">
          <td><span class="badge" :class="a.source">{{ a.source }}</span></td>
          <td class="expr">{{ a.expression }}</td>
          <td class="mono">{{ a.id.slice(0, 8) }}</td>
          <td>{{ a.filter_skipped ? '⚠ skipped' : '✓' }}</td>
          <td class="mono">{{ new Date(a.created_at).toLocaleDateString() }}</td>
        </tr>
        <tr v-if="filtered.length === 0">
          <td colspan="5" class="empty">No alphas found.</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.count { color: #64748b; font-size: 0.85rem; }
.select { background: #0f1117; border: 1px solid #2d3748; border-radius: 6px; padding: 7px 12px; color: #e2e8f0; font-size: 0.875rem; }
.table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.table th { padding: 10px 12px; text-align: left; border-bottom: 2px solid #2d3748; color: #94a3b8; font-weight: 600; white-space: nowrap; }
.table td { padding: 9px 12px; border-bottom: 1px solid #1a202c; vertical-align: middle; }
.table tr:hover td { background: #1e2330; }
.sortable { cursor: pointer; user-select: none; }
.sortable:hover { color: #e2e8f0; }
.expr { font-family: monospace; font-size: 0.8rem; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #a78bfa; }
.mono { font-family: monospace; font-size: 0.8rem; color: #64748b; }
.empty { text-align: center; color: #64748b; padding: 24px; }
.loading { color: #64748b; font-size: 0.9rem; padding: 8px 0; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
.badge.seed { background: #064e3b; color: #6ee7b7; }
.badge.mutation { background: #1e3a5f; color: #93c5fd; }
.badge.llm { background: #3b1f5e; color: #c4b5fd; }
.badge.gp { background: #3b2f1f; color: #fcd34d; }
.badge.manual { background: #374151; color: #9ca3af; }
</style>
