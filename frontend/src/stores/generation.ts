import { defineStore } from 'pinia'
import { generateApi, type RunRead } from '../api/client'

export const useGenerationStore = defineStore('generation', {
  state: () => ({
    runs: [] as RunRead[],
    loading: false,
    generating: false,
    lastResult: null as any,
    error: null as string | null,
  }),
  getters: {
    recentRuns: (state) => state.runs.slice(0, 10),
    runningGP: (state) => state.runs.some(r => r.mode === 'gp' && r.finished_at === null),
  },
  actions: {
    async fetchRuns() {
      this.loading = true
      try {
        const r = await generateApi.runs()
        this.runs = r.data
      } finally {
        this.loading = false
      }
    },
    async runMutate(alphaId?: string) {
      this.generating = true
      this.error = null
      try {
        const r = await generateApi.mutate(alphaId)
        this.lastResult = r.data
        await this.fetchRuns()
        return r.data
      } catch (e: any) {
        this.error = e?.response?.data?.detail ?? e?.message ?? 'Mutation failed'
        throw e
      } finally {
        this.generating = false
      }
    },
    async runLLM(theme: string | null, n: number) {
      this.generating = true
      this.error = null
      try {
        const r = await generateApi.llm(theme, n)
        this.lastResult = r.data
        await this.fetchRuns()
        return r.data
      } catch (e: any) {
        this.error = e?.response?.data?.detail ?? e?.message ?? 'LLM generation failed'
        throw e
      } finally {
        this.generating = false
      }
    },
    async runGP(nResults: number, generations?: number) {
      this.generating = true
      this.error = null
      try {
        const r = await generateApi.gp(nResults, generations)
        this.lastResult = r.data
        await this.fetchRuns()
        return r.data
      } catch (e: any) {
        this.error = e?.response?.data?.detail ?? e?.message ?? 'GP search failed'
        throw e
      } finally {
        this.generating = false
      }
    },
  },
})
