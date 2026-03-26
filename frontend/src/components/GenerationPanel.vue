<script setup lang="ts">
import { ref } from 'vue'
import { useGenerationStore } from '../stores/generation'

const emit = defineEmits<{ done: [] }>()
const gen = useGenerationStore()
const tab = ref<'mutation' | 'llm' | 'gp'>('mutation')
const llmTheme = ref('')
const llmN = ref(10)
const gpResults = ref(10)
const gpGenerations = ref(20)

async function runMutate() {
  await gen.runMutate()
  emit('done')
}
async function runLLM() {
  await gen.runLLM(llmTheme.value || null, llmN.value)
  emit('done')
}
async function runGP() {
  await gen.runGP(gpResults.value, gpGenerations.value)
  emit('done')
}
</script>

<template>
  <div class="panel">
    <div class="tabs">
      <button v-for="t in ['mutation','llm','gp']" :key="t" :class="['tab', { active: tab === t }]" @click="tab = t as any">
        {{ t === 'mutation' ? '&#128256; Mutation' : t === 'llm' ? '&#129302; LLM' : '&#129514; GP' }}
      </button>
    </div>

    <div class="tab-body">
      <!-- Mutation -->
      <div v-if="tab === 'mutation'">
        <p class="desc">Generate mutations from all Alpha101 seed pool alphas.</p>
        <button class="btn-primary" :disabled="gen.generating" @click="runMutate">
          {{ gen.generating ? 'Running…' : 'Run Mutation' }}
        </button>
      </div>

      <!-- LLM -->
      <div v-if="tab === 'llm'">
        <p class="desc">Ask Claude to generate novel alphas based on current pool context.</p>
        <div class="field">
          <label>Theme (optional)</label>
          <input v-model="llmTheme" type="text" placeholder="e.g. volume-price divergence" class="input" />
        </div>
        <div class="field">
          <label>Candidates to generate</label>
          <input v-model.number="llmN" type="number" min="1" max="50" class="input short" />
        </div>
        <button class="btn-primary" :disabled="gen.generating" @click="runLLM">
          {{ gen.generating ? 'Generating…' : 'Generate with LLM' }}
        </button>
      </div>

      <!-- GP -->
      <div v-if="tab === 'gp'">
        <p class="desc">Run symbolic regression on proxy data (~20–30 min on CPU).</p>
        <div class="field">
          <label>Results to extract</label>
          <input v-model.number="gpResults" type="number" min="1" max="50" class="input short" />
        </div>
        <div class="field">
          <label>Generations</label>
          <input v-model.number="gpGenerations" type="number" min="1" max="100" class="input short" />
        </div>
        <button class="btn-primary" :disabled="gen.generating" @click="runGP">
          {{ gen.generating ? 'Dispatching…' : 'Start GP Search' }}
        </button>
        <p v-if="gen.runningGP" class="gp-running">&#9203; GP run in progress — check Runs below when complete.</p>
      </div>
    </div>

    <div v-if="gen.error" class="error">{{ gen.error }}</div>

    <div v-if="gen.lastResult" class="result">
      <strong>Last result:</strong>
      <span v-if="gen.lastResult.candidates_generated !== undefined">
        {{ gen.lastResult.candidates_generated }} generated,
        {{ gen.lastResult.candidates_passed_validation ?? gen.lastResult.candidates_pass ?? '?' }} saved
      </span>
      <span v-else-if="gen.lastResult.run_id">Run #{{ gen.lastResult.run_id }} started</span>
    </div>
  </div>
</template>

<style scoped>
.panel { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; }
.tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid #2d3748; padding-bottom: 12px; }
.tab { background: none; border: 1px solid #2d3748; color: #94a3b8; padding: 7px 16px; border-radius: 6px; font-size: 0.875rem; }
.tab:hover { background: #2d3748; color: #e2e8f0; }
.tab.active { background: #1d4ed8; border-color: #1d4ed8; color: #fff; }
.tab-body { min-height: 120px; }
.desc { color: #94a3b8; font-size: 0.875rem; margin-bottom: 16px; }
.field { margin-bottom: 12px; }
.field label { display: block; font-size: 0.8rem; color: #94a3b8; margin-bottom: 4px; }
.input { background: #0f1117; border: 1px solid #2d3748; border-radius: 6px; padding: 8px 12px; color: #e2e8f0; font-size: 0.875rem; width: 100%; }
.input.short { width: 100px; }
.input:focus { outline: none; border-color: #3b82f6; }
.error { margin-top: 12px; padding: 8px 12px; background: #3b1f1f; border: 1px solid #ef4444; border-radius: 6px; color: #fca5a5; font-size: 0.875rem; }
.result { margin-top: 12px; font-size: 0.875rem; color: #6ee7b7; }
.gp-running { margin-top: 8px; font-size: 0.8rem; color: #fbbf24; }
</style>
