# Docker Development Setup Design

**Date**: 2026-03-26
**Status**: Approved
**Scope**: `Dockerfile.backend`, `frontend/Dockerfile`, `docker-compose.yml`, minor edits to `frontend/vite.config.ts` and `frontend/src/api/client.ts`

---

## 1. Goals

- Run backend (FastAPI) and frontend (Vite) as separate Docker containers via Docker Compose
- Support hot-reload: backend uses `uvicorn --reload`, frontend uses Vite HMR
- Fresh SQLite DB on each start (no volume persistence needed)
- `.env` file on the host is passed into the backend container unchanged
- Works with Docker Desktop on Windows

---

## 2. Architecture

```
Host (Windows)
├── http://localhost:8000  ←→  backend container (FastAPI + uvicorn --reload)
└── http://localhost:5173  ←→  frontend container (Vite dev server)
                                     │
                              Browser (on host) makes
                              API calls to localhost:8000
```

The browser runs on the **host**, not inside a container. So:
- Backend port 8000 is forwarded host→container: browser hits `http://localhost:8000` directly
- Frontend port 5173 is forwarded host→container: browser hits `http://localhost:5173` directly
- No container-to-container networking needed for API calls; `VITE_API_BASE_URL` is resolved by the **browser**, not by the frontend container

---

## 3. Files Created / Modified

### 3.1 `Dockerfile.backend`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Source code is bind-mounted at /app at runtime — do not COPY here
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"]
```

Key decisions:
- Packages installed into **system Python** (`/usr/local/lib/...`), not into `.venv`. This means bind-mounting `/app` at runtime does not clobber installed packages.
- `alembic upgrade head` runs on every container start (safe on fresh SQLite DB).
- `--host 0.0.0.0` required so Docker port forwarding reaches uvicorn.

### 3.2 `frontend/Dockerfile`

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
# Source code is bind-mounted at /app at runtime — do not COPY here
CMD ["npm", "run", "dev"]
```

Key decisions:
- `node_modules` is installed inside the image at `/app/node_modules`.
- A **named Docker volume** (`frontend_node_modules`) is overlaid on `/app/node_modules` in `docker-compose.yml`. This preserves the container's packages when the host `./frontend` is bind-mounted over `/app`, because Docker named volumes take precedence over bind mounts for the same path.

### 3.3 `docker-compose.yml`

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

### 3.4 `frontend/vite.config.ts` — add `server.host`

```ts
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,   // listen on 0.0.0.0 so Docker port forwarding works
  },
})
```

Without `host: true`, Vite only binds to `127.0.0.1` inside the container and Docker cannot forward port 5173 to the host.

### 3.5 `frontend/src/api/client.ts` — read base URL from env var

Change line 3 from:
```ts
const BASE_URL = 'http://localhost:8000/api'
```
to:
```ts
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000') + '/api'
```

`VITE_API_BASE_URL` defaults to `http://localhost:8000` when running outside Docker (`npm run dev` locally). Inside Docker, the `docker-compose.yml` sets it to `http://localhost:8000` as well — so the value is the same but the mechanism is explicit and overrideable.

---

## 4. Usage

```bash
# First time (or after dependency changes):
docker compose build

# Start both services:
docker compose up

# Backend only:
docker compose up backend

# Tear down:
docker compose down
```

- Backend: http://localhost:8000 (API docs at /docs)
- Frontend: http://localhost:5173

---

## 5. Known Limitations

| Limitation | Notes |
|------------|-------|
| File-watch latency on Windows | Docker Desktop uses WSL2; inotify events from Windows host → container may be slow. If hot-reload feels sluggish, Vite's `server.watch.usePolling: true` can be added to `vite.config.ts`. |
| `.venv` visible in container | The host `.venv` is bind-mounted into `/app/.venv` but is ignored — packages come from system Python. No conflict, just dead weight. |
| SQLite fresh on restart | By design. To persist data, add `- ./alpha_miner.db:/app/alpha_miner.db` to backend volumes. |
