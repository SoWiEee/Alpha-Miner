<script setup lang="ts">
import { ref } from 'vue'
import { useQueueStore } from '../stores/queue'

const queue = useQueueStore()
const alphaId = ref('')
const sharpe = ref<number>(0)
const fitness = ref<number>(0)
const returns = ref<number>(0)
const turnover = ref<number>(0)
const passed = ref(true)
const notes = ref('')
const loading = ref(false)
const success = ref('')
const error = ref('')

async function submit() {
  if (!alphaId.value) { error.value = 'Alpha ID is required'; return }
  loading.value = true; error.value = ''; success.value = ''
  try {
    await queue.importResult({
      alpha_id: alphaId.value,
      sharpe: sharpe.value,
      fitness: fitness.value,
      returns: returns.value,
      turnover: turnover.value,
      passed: passed.value,
      notes: notes.value || undefined,
    })
    success.value = `Result imported for ${alphaId.value.slice(0, 8)}…`
    alphaId.value = ''; sharpe.value = 0; fitness.value = 0
    returns.value = 0; turnover.value = 0; passed.value = true; notes.value = ''
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Import failed'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="import-form">
    <h4>Import Result from WQ Brain</h4>
    <div class="form-grid">
      <div class="field full">
        <label>Alpha ID</label>
        <input v-model="alphaId" class="input" placeholder="Paste alpha ID (full or partial)" />
      </div>
      <div class="field">
        <label>Sharpe</label>
        <input v-model.number="sharpe" type="number" step="0.01" class="input" />
      </div>
      <div class="field">
        <label>Fitness</label>
        <input v-model.number="fitness" type="number" step="0.01" class="input" />
      </div>
      <div class="field">
        <label>Returns</label>
        <input v-model.number="returns" type="number" step="0.001" class="input" />
      </div>
      <div class="field">
        <label>Turnover</label>
        <input v-model.number="turnover" type="number" step="0.001" class="input" />
      </div>
      <div class="field">
        <label>Passed</label>
        <select v-model="passed" class="input">
          <option :value="true">Yes</option>
          <option :value="false">No</option>
        </select>
      </div>
      <div class="field full">
        <label>Notes (optional)</label>
        <input v-model="notes" class="input" placeholder="Optional notes" />
      </div>
    </div>
    <button class="btn-primary" :disabled="loading" @click="submit">
      {{ loading ? 'Importing…' : 'Import Result' }}
    </button>
    <div v-if="success" class="success">{{ success }}</div>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<style scoped>
.import-form { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
h4 { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
.field { }
.field.full { grid-column: 1 / -1; }
.field label { display: block; font-size: 0.8rem; color: #94a3b8; margin-bottom: 4px; }
.input { width: 100%; background: #0f1117; border: 1px solid #2d3748; border-radius: 6px; padding: 8px 12px; color: #e2e8f0; font-size: 0.875rem; }
.input:focus { outline: none; border-color: #3b82f6; }
.success { margin-top: 8px; color: #6ee7b7; font-size: 0.875rem; }
.error { margin-top: 8px; color: #fca5a5; font-size: 0.875rem; }
</style>
