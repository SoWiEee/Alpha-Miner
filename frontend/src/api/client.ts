import axios from 'axios'

const BASE_URL = 'http://localhost:8000/api'
export const api = axios.create({ baseURL: BASE_URL })

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PoolStatus {
  pool_size: number
  avg_sharpe: number | null
  avg_fitness: number | null
  max_correlation: number | null
  min_correlation: number | null
}

export interface CorrelationEntry {
  alpha_a: string
  alpha_b: string
  correlation: number
  computed_at: string
}

export interface TopAlphaEntry {
  id: string
  expression: string
  source: string
  sharpe: number | null
  fitness: number | null
  returns: number | null
  turnover: number | null
  passed: boolean | null
}

export interface AlphaRead {
  id: string
  expression: string
  universe: string
  region: string
  delay: number
  decay: number
  neutralization: string
  truncation: number
  pasteurization: string
  nan_handling: string
  source: string
  parent_id: string | null
  rationale: string | null
  filter_skipped: boolean
  created_at: string
}

export interface SimulationRead {
  id: number
  alpha_id: string
  sharpe: number | null
  fitness: number | null
  returns: number | null
  turnover: number | null
  passed: boolean | null
  status: string
  submitted_at: string | null
  completed_at: string | null
  wq_sim_id: string | null
  notes: string | null
}

export interface RunRead {
  id: number
  mode: string
  candidates_gen: number
  candidates_pass: number
  llm_theme: string | null
  gp_generations: number | null
  started_at: string
  finished_at: string | null
}

export interface ExportEntry {
  alpha_id: string
  expression: string
  settings: {
    region: string
    universe: string
    delay: number
    decay: number
    neutralization: string
    truncation: number
    pasteurization: string
    nan_handling: string
  }
}

export interface RecomputeResult {
  pairs_computed: number
  skipped: number
}

// ─── Pool ─────────────────────────────────────────────────────────────────────

export const poolApi = {
  status: () => api.get<PoolStatus>('/pool/status'),
  correlations: () => api.get<CorrelationEntry[]>('/pool/correlations'),
  top: (n = 10) => api.get<TopAlphaEntry[]>(`/pool/top?n=${n}`),
  recompute: () => api.post<RecomputeResult>('/pool/recompute'),
}

// ─── Alphas ───────────────────────────────────────────────────────────────────

export const alphasApi = {
  list: (source?: string) =>
    api.get<AlphaRead[]>('/alphas', { params: source ? { source } : undefined }),
  get: (id: string) => api.get<AlphaRead>(`/alphas/${id}`),
}

// ─── Queue / Submit ───────────────────────────────────────────────────────────

export const submitApi = {
  queue: (status?: string) =>
    api.get<SimulationRead[]>('/submit/queue', { params: status ? { status } : undefined }),
  export: () => api.get<ExportEntry[]>('/submit/export'),
  importResult: (data: {
    alpha_id: string
    sharpe: number
    fitness: number
    returns: number
    turnover: number
    passed: boolean
    notes?: string
  }) => api.post<SimulationRead>('/submit/result', data),
}

// ─── Generate ─────────────────────────────────────────────────────────────────

export const generateApi = {
  mutate: (alpha_id?: string) =>
    api.post('/generate/mutate', { alpha_id: alpha_id ?? null }),
  llm: (theme: string | null, n = 10) =>
    api.post('/generate/llm', { theme, n }),
  gp: (n_results = 10, generations?: number) =>
    api.post('/generate/gp', { n_results, generations: generations ?? null }),
  runs: () => api.get<RunRead[]>('/generate/runs'),
}
