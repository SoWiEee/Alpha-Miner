<script setup lang="ts">
import { computed } from 'vue'
import type { CorrelationEntry } from '../api/client'

const props = defineProps<{ correlations: CorrelationEntry[] }>()

// Get unique alpha IDs (truncated to 8 chars for display)
const ids = computed(() => {
  const set = new Set<string>()
  props.correlations.forEach(c => { set.add(c.alpha_a); set.add(c.alpha_b) })
  return Array.from(set).sort()
})

// Build matrix: corrMap[a][b] = correlation
const corrMap = computed(() => {
  const m: Record<string, Record<string, number>> = {}
  ids.value.forEach(a => { m[a] = {} })
  props.correlations.forEach(c => {
    m[c.alpha_a][c.alpha_b] = c.correlation
    m[c.alpha_b][c.alpha_a] = c.correlation
  })
  return m
})

const getCorr = (a: string, b: string) => {
  if (a === b) return 1
  return corrMap.value[a]?.[b] ?? null
}

// Color: 0=blue, 0.7=yellow, 1=red
const corrColor = (v: number | null): string => {
  if (v === null) return '#2d3748'
  const r = Math.round(255 * v)
  const b = Math.round(255 * (1 - v))
  const g = Math.round(255 * (1 - Math.abs(v - 0.5) * 2))
  return `rgb(${r},${g},${b})`
}

const short = (id: string) => id.slice(0, 6)
</script>

<template>
  <div class="heatmap-wrap">
    <h4>Correlation Heatmap</h4>
    <div v-if="ids.length === 0" class="empty">No correlation data. Run Recompute first.</div>
    <div v-else class="heatmap-scroll">
      <div class="heatmap" :style="{ gridTemplateColumns: `60px repeat(${ids.length}, 28px)` }">
        <!-- Header row -->
        <div class="hm-corner"></div>
        <div v-for="id in ids" :key="'h-'+id" class="hm-label hm-col-label" :title="id">{{ short(id) }}</div>
        <!-- Data rows -->
        <template v-for="rowId in ids" :key="'r-'+rowId">
          <div class="hm-label hm-row-label" :title="rowId">{{ short(rowId) }}</div>
          <div
            v-for="colId in ids" :key="'c-'+colId"
            class="hm-cell"
            :style="{ background: corrColor(getCorr(rowId, colId)) }"
            :title="`${short(rowId)} x ${short(colId)}: ${getCorr(rowId, colId)?.toFixed(3) ?? 'n/a'}`"
          ></div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.heatmap-wrap { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
h4 { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 16px; }
.heatmap-scroll { overflow-x: auto; }
.heatmap { display: grid; gap: 2px; width: fit-content; }
.hm-corner { width: 60px; height: 28px; }
.hm-label { font-size: 0.65rem; color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hm-col-label { width: 28px; height: 28px; writing-mode: vertical-lr; text-align: center; }
.hm-row-label { width: 60px; height: 28px; line-height: 28px; text-align: right; padding-right: 4px; }
.hm-cell { width: 28px; height: 28px; border-radius: 3px; transition: opacity 0.1s; }
.hm-cell:hover { opacity: 0.8; }
.empty { color: #64748b; font-size: 0.9rem; }
</style>
