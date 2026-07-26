# Cistron VCL design reference

Source mockup (design canvas):

- `Cistron-VCL.dc.html` + `support.js` — original Systems Biology IDE layout
- `thumbnail.png` — mockup preview
- `studio-live.png` — live React Studio after integration

The live app implements this chrome under `frontend/`:

| Mockup region | Live |
|---|---|
| 46px header (CISTRON·VCL, ⌘K, scenario, RUN, ENGINE LIVE, EXPORT) | `Header.tsx` |
| 54px code rail ST/PW/… | `SidebarNav.tsx` |
| Stage toolbar (Graph / Spatial) | `StudioView.tsx` |
| Bottom dock (Trajectory / Organelle / FBA + scrub) | `layout/vcl/BottomAnalysisDock.tsx` |
| Right inspector (perturbations + impact/synergy) | `layout/vcl/RightInspectorDock.tsx` |
| Command palette ⌘K | `layout/vcl/CommandPalette.tsx` |
| Shell geometry + resizers | `layout/AppShell.tsx` |
