# VOIDSIGNAL Enterprise Research Studio

Decoupled React + TypeScript + Tailwind research console for the VOIDSIGNAL
Python backend (ODE solvers, docking, VCF, Graph ML, AI Scientist).

Design tokens and layout contracts live in [`DESIGN.md`](./DESIGN.md).

## Quick start

```bash
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173 — mock API is enabled by default (no FastAPI required).

## Connect to FastAPI

```bash
# PowerShell
$env:VITE_API_BASE="http://127.0.0.1:8000"
$env:VITE_USE_MOCK="false"
npm run dev
```

Vite proxies `/api` → `http://127.0.0.1:8000` when using relative paths.

## Package map

| Path | Role |
| --- | --- |
| `src/ui/design_system.ts` | Color / type / severity tokens |
| `src/ui/components/` | Dosing, trajectory, network, AI panel, docking |
| `src/ui/api/client.ts` | Typed REST/WS client + React hooks |
| `src/App.tsx` | Studio shell (header / sidebar / canvas / AI) |

## Scripts

- `npm run dev` — Vite dev server
- `npm run build` — production bundle
- `npm run preview` — serve build
