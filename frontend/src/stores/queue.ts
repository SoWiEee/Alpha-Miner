import { defineStore } from 'pinia'
import { submitApi, type SimulationRead, type ExportEntry } from '../api/client'

export const useQueueStore = defineStore('queue', {
  state: () => ({
    items: [] as SimulationRead[],
    exportData: [] as ExportEntry[],
    loading: false,
    error: null as string | null,
  }),
  getters: {
    pending: (state) => state.items.filter(i => i.status === 'pending'),
    submitted: (state) => state.items.filter(i => i.status === 'submitted'),
    completed: (state) => state.items.filter(i => i.status === 'completed'),
  },
  actions: {
    async refresh() {
      this.loading = true
      this.error = null
      try {
        const r = await submitApi.queue()
        this.items = r.data
      } catch (e: any) {
        this.error = e?.message ?? 'Failed to load queue'
      } finally {
        this.loading = false
      }
    },
    async fetchExport() {
      const r = await submitApi.export()
      this.exportData = r.data
      return r.data
    },
    async importResult(data: Parameters<typeof submitApi.importResult>[0]) {
      const r = await submitApi.importResult(data)
      await this.refresh()
      return r.data
    },
  },
})
