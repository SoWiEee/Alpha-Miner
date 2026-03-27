<template>
  <div>
    <h1 class="page-title">Settings</h1>
    <div class="card">
      <h3>Backend Connection</h3>
      <div class="info-row">
        <span class="label">API Base URL</span>
        <code>http://localhost:8000/api</code>
      </div>
      <div class="info-row">
        <span class="label">Docs</span>
        <a href="http://localhost:8000/docs" target="_blank">http://localhost:8000/docs &#8599;</a>
      </div>
    </div>

    <div class="card">
      <h3>Configuration</h3>
      <p class="note">Settings are managed via <code>.env</code> in the project root. Restart the backend after changes.</p>
      <table class="table">
        <thead><tr><th>Setting</th><th>Description</th><th>Default</th></tr></thead>
        <tbody>
          <tr><td><code>CLAUDE_API_KEY</code></td><td>Anthropic API key for LLM generation</td><td>—</td></tr>
          <tr><td><code>WQ_MODE</code></td><td>manual or auto</td><td>manual</td></tr>
          <tr><td><code>DIVERSITY_THRESHOLD</code></td><td>Max Spearman correlation allowed</td><td>0.7</td></tr>
          <tr><td><code>LLM_MAX_CALLS_PER_DAY</code></td><td>Daily LLM call cap</td><td>20</td></tr>
          <tr><td><code>GP_POPULATION_SIZE</code></td><td>GP population size</td><td>500</td></tr>
          <tr><td><code>GP_GENERATIONS</code></td><td>GP generations</td><td>20</td></tr>
          <tr><td><code>PROXY_DATA_TICKERS</code></td><td>Number of S&amp;P 500 tickers to cache</td><td>500</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3>Useful Commands</h3>
      <pre class="code">uv run uvicorn backend.main:app --reload --port 8000  # Start backend
uv run python scripts/seed_alpha101.py               # Load Alpha101 seeds
uv run python scripts/update_proxy_data.py           # Refresh proxy data
cd frontend &amp;&amp; npm run dev                           # Start this dashboard</pre>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; color: #e2e8f0; }
.card { background: #1e2330; border: 1px solid #2d3748; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.card h3 { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; margin-bottom: 12px; }
.info-row { display: flex; align-items: center; gap: 16px; padding: 8px 0; border-bottom: 1px solid #1a202c; font-size: 0.875rem; }
.info-row:last-child { border-bottom: none; }
.label { color: #94a3b8; min-width: 130px; }
code { background: #0f1117; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 0.8rem; color: #a78bfa; }
.note { font-size: 0.875rem; color: #64748b; margin-bottom: 12px; }
.table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
.table th { padding: 8px 12px; text-align: left; border-bottom: 2px solid #2d3748; color: #94a3b8; }
.table td { padding: 8px 12px; border-bottom: 1px solid #1a202c; }
.code { font-family: monospace; font-size: 0.8rem; background: #0f1117; padding: 16px; border-radius: 8px; color: #6ee7b7; white-space: pre-wrap; line-height: 1.7; }
</style>
