# Docker Development Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Docker Compose dev setup so the FastAPI backend and Vue3 frontend each run in their own container with hot-reload, accessible at `localhost:8000` and `localhost:5173`.

**Architecture:** Two containers orchestrated by `docker-compose.yml`. Backend installs Python packages into system Python (not `.venv`) so bind-mounting the project root doesn't clobber them. Frontend uses a named Docker volume to preserve `node_modules` inside the container when the source tree is bind-mounted over `/app`.

**Tech Stack:** Docker Compose 3.9, Python 3.11 slim, Node 20 Alpine, uvicorn `--reload`, Vite dev server with `host: true`.

---

### Task 1: Create `Dockerfile.backend`

**Files:**
- Create: `Dockerfile.backend`

- [ ] **Step 1: Create the file**

Create `Dockerfile.backend` at the project root with this exact content:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 2: Verify the file exists**

Run:
```bash
ls Dockerfile.backend
```
Expected: `Dockerfile.backend`

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.backend
git commit -m "feat: add backend Dockerfile for dev"
```

---

### Task 2: Create `frontend/Dockerfile`

**Files:**
- Create: `frontend/Dockerfile`

- [ ] **Step 1: Create the file**

Create `frontend/Dockerfile` with this exact content:

```dockerfile
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

CMD ["npm", "run", "dev"]
```

- [ ] **Step 2: Verify the file exists**

Run:
```bash
ls frontend/Dockerfile
```
Expected: `frontend/Dockerfile`

- [ ] **Step 3: Commit**

```bash
git add frontend/Dockerfile
git commit -m "feat: add frontend Dockerfile for dev"
```

---

### Task 3: Create `docker-compose.yml`

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create the file**

Create `docker-compose.yml` at the project root with this exact content:

```yaml
version: '3.9'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    env_file:
      - .env

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    volumes:
      - ./frontend:/app
      - frontend_node_modules:/app/node_modules
    environment:
      - VITE_API_BASE_URL=http://localhost:8000

volumes:
  frontend_node_modules:
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose for dev"
```

---

### Task 4: Patch `frontend/vite.config.ts` — bind to `0.0.0.0`

**Files:**
- Modify: `frontend/vite.config.ts`

Without `host: true`, Vite listens only on `127.0.0.1` inside the container and Docker cannot forward port 5173 to the host.

- [ ] **Step 1: Edit the file**

Current content of `frontend/vite.config.ts`:
```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
})
```

Replace with:
```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true, // bind to 0.0.0.0 so Docker port forwarding works
  },
})
```

- [ ] **Step 2: Verify local build still passes**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds (no errors), output like `dist/index.html` created.

- [ ] **Step 3: Commit**

```bash
git add frontend/vite.config.ts
git commit -m "feat: bind Vite to 0.0.0.0 for Docker"
```

---

### Task 5: Patch `frontend/src/api/client.ts` — read base URL from env var

**Files:**
- Modify: `frontend/src/api/client.ts`

This lets `VITE_API_BASE_URL` override the default when running inside Docker (or any environment where the backend lives at a non-default URL). When the env var is absent (local `npm run dev`), it falls back to `http://localhost:8000`.

- [ ] **Step 1: Edit line 3 of `frontend/src/api/client.ts`**

Find:
```ts
const BASE_URL = 'http://localhost:8000/api'
```

Replace with:
```ts
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000') + '/api'
```

- [ ] **Step 2: Verify local build still passes**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: read API base URL from VITE_API_BASE_URL env var"
```

---

### Task 6: Build and smoke-test the containers

- [ ] **Step 1: Build both images**

Run from the project root:
```bash
docker compose build
```
Expected: both images build without errors. You will see pip install output for the backend and npm install output for the frontend.

- [ ] **Step 2: Start both containers**

```bash
docker compose up
```
Expected output (interleaved):
- `backend-1  | INFO  [alembic.runtime.migration] Running upgrade ...`
- `backend-1  | INFO:     Uvicorn running on http://0.0.0.0:8000`
- `frontend-1 | VITE v... ready in ... ms`
- `frontend-1 | ➜  Local:   http://localhost:5173/`

- [ ] **Step 3: Verify backend health endpoint**

Open a new terminal and run:
```bash
curl http://localhost:8000/health
```
Expected:
```json
{"status": "ok"}
```

- [ ] **Step 4: Verify frontend is accessible**

Open `http://localhost:5173` in your browser.
Expected: Alpha Miner dashboard loads (NavBar visible, no console errors about failed API calls on the health check).

- [ ] **Step 5: Verify backend API docs**

Open `http://localhost:8000/docs` in your browser.
Expected: FastAPI Swagger UI loads showing all routes (`/api/alphas`, `/api/generate/...`, etc.).

- [ ] **Step 6: Stop containers**

```bash
docker compose down
```
Expected: containers stop cleanly.

- [ ] **Step 7: Commit final state**

```bash
git add .
git commit -m "feat: Docker dev setup complete"
```

---

## Troubleshooting Reference

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'backend'` | The project root must be bind-mounted to `/app`. Check `volumes: - .:/app` is present in `docker-compose.yml` for the backend service. |
| Frontend shows blank page / CORS errors | Ensure `CORS_ORIGINS=http://localhost:5173` is set in your `.env` file. |
| Vite HMR not triggering on file save | Add `server: { watch: { usePolling: true } }` to `frontend/vite.config.ts` (Windows WSL2 inotify limitation). |
| `alembic: command not found` | Alembic must be listed in `requirements.txt`. Confirm with `grep alembic requirements.txt`. |
| Port already in use | Check `netstat -ano | findstr :8000` and kill the occupying process, or change the host port in `docker-compose.yml`. |
