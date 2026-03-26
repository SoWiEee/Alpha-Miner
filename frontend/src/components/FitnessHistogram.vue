<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip } from 'chart.js'
import type { TopAlphaEntry } from '../api/client'

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip)

const props = defineProps<{ alphas: TopAlphaEntry[] }>()
const canvasRef = ref<HTMLCanvasElement | null>(null)
let chart: Chart | null = null

function buildChart() {
  if (!canvasRef.value) return
  const fitnesses = props.alphas.map(a => a.fitness ?? 0).filter(f => f > 0)
  if (fitnesses.length === 0) return

  // Bin into 10 buckets
  const min = Math.floor(Math.min(...fitnesses) * 10) / 10
  const max = Math.ceil(Math.max(...fitnesses) * 10) / 10
  const step = Math.max((max - min) / 10, 0.1)
  const bins: number[] = []
  const labels: string[] = []
  for (let i = min; i < max; i += step) {
    labels.push(i.toFixed(1))
    bins.push(fitnesses.filter(f => f >= i && f < i + step).length)
  }

  if (chart) chart.destroy()
  chart = new Chart(canvasRef.value, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: bins, backgroundColor: '#3b82f6', borderRadius: 4 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: (items) => `Fitness ≈ ${items[0].label}` } } },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#2d3748' } },
        y: { ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: '#2d3748' } },
      },
    },
  })
}

onMounted(buildChart)
watch(() => props.alphas, buildChart, { deep: true })
</script>

<template>
  <div class="histogram">
    <h4>Fitness Distribution</h4>
    <div class="chart-wrapper">
      <canvas ref="canvasRef" />
    </div>
    <div v-if="alphas.filter(a => a.fitness).length === 0" class="empty">No fitness data yet.</div>
  </div>
</template>

<style scoped>
.histogram { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
h4 { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 16px; }
.chart-wrapper { height: 200px; }
.empty { color: #64748b; font-size: 0.9rem; padding: 8px 0; }
</style>
