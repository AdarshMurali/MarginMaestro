# frontend

Next.js ops dashboard for MarginMaestro (Phase 8, epic MM-50) — connects to the
API via REST + WebSocket/SSE. Dark-only theme; see `docs/ROADMAP.md`'s Phase 8
note for the full design spec.

## Develop

```bash
npm install
cp .env.example .env.local   # adjust NEXT_PUBLIC_API_BASE_URL if needed
npm run dev                  # http://localhost:3000
```

Requires the FastAPI backend running separately (`docs/../CLAUDE.md`'s
`make` targets, or `uvicorn api.main:app --app-dir ../src`) with
`CORS_ALLOWED_ORIGINS` including `http://localhost:3000`.

## Checks

```bash
npx tsc --noEmit
npx eslint .
npm run build
```
