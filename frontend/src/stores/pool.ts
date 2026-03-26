import { defineStore } from 'pinia'
import { poolApi, type PoolStatus, type CorrelationEntry, type TopAlphaEntry } from '../api/client'

export const usePoolStore = defineStore('pool', {
  state: () => ({
    status: null as PoolStatus | null,
    correlations: [] as CorrelationEntry[],
    topAlphas: [] as TopAlphaEntry[],
    loading: false,
    lastUpdated: null as string | null,
    error: null as string | null,
  }),
  actions: {
    async refresh() {
      this.loading = true
      this.error = null
      try {
        const [s, c, t] = await Promise.all([
          poolApi.status(),
          poolApi.correlations(),
          poolApi.top(20),
        ])
        this.status = s.data
        this.correlations = c.data
        this.topAlphas = t.data
        this.lastUpdated = new Date().toISOString()
      } catch (e: any) {
        this.error = e?.message ?? 'Failed to load pool data'
      } finally {
        this.loading = false
      }
    },
    async recompute() {
      await poolApi.recompute()
      await this.refresh()
    },
  },
})
