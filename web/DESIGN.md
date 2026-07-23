# VOIDSIGNAL Enterprise Research Studio — Design System

Biotech / dark-mode precision console for ODE simulation, genomic VCF workflows,
graph ML, and autonomous AI Scientist briefs. Tokens in this document are the
source of truth; `src/ui/design_system.ts` and Tailwind utilities must stay in sync.

---

## 1. Visual language

| Token | Value | Usage |
| --- | --- | --- |
| `bg.void` | `#0B0F17` | Application chrome / canvas |
| `bg.panel` | `rgba(17, 24, 39, 0.72)` | Glassmorphic surfaces |
| `bg.panelSolid` | `#111827` | Opaque fallbacks |
| `bg.elevated` | `#151C2C` | Nested controls, inputs |
| `border.subtle` | `rgba(148, 163, 184, 0.12)` | Hairline dividers |
| `border.cyan` | `#00E5FF` | Focus / active / glow |
| `border.cyanMuted` | `rgba(0, 229, 255, 0.28)` | Panel outlines |
| `text.primary` | `#F8FAFC` | Headings, primary labels |
| `text.secondary` | `#94A3B8` | Metadata, hints |
| `text.muted` | `#64748B` | Disabled / tertiary |
| `accent.cyan` | `#00E5FF` | Primary accent |
| `accent.teal` | `#2DD4BF` | Secondary success / activation |
| `accent.amber` | `#FBBF24` | Warnings / washout |
| `accent.rose` | `#FB7185` | Inhibition / critical |
| `accent.lime` | `#A3E635` | Healthy / online |

**Glass recipe:** `background: bg.panel` + `backdrop-filter: blur(16px)` +
`border: 1px solid border.cyanMuted` + optional `box-shadow: 0 0 24px rgba(0,229,255,0.06)`.

**Glow (use sparingly):** `0 0 0 1px rgba(0,229,255,0.35), 0 0 18px rgba(0,229,255,0.12)`.

---

## 2. Typography

| Role | Family | Weight | Size / line |
| --- | --- | --- | --- |
| Display / brand | Geist Sans (fallback Inter) | 600 | 18–22 / 1.2 |
| UI label | Geist Sans / Inter | 500 | 12–13 / 1.35 |
| Body | Geist Sans / Inter | 400 | 13–14 / 1.5 |
| Mono scientific | JetBrains Mono | 400–500 | 11–13 / 1.4 |

**Mono only for:** stoichiometric equations, VCF genomic coordinates, kinetic rates
(`k_cat`, `K_m`, `K_i`, `C_0`), trajectory scrubber times, node IDs.

---

## 3. Layout structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│ HEADER — health · patient VCF badge · HSI/PDS gauges · AI Scientist CTA │
├──────────┬──────────────────────────────────────────────┬───────────────┤
│ SIDEBAR  │ MAIN CANVAS (tabs)                           │ RIGHT PANEL   │
│ dosing   │  Trajectory | Network | Docking              │ AI stream     │
│ targets  │                                              │ LAS cards     │
│ combos   │                                              │ brief MD      │
└──────────┴──────────────────────────────────────────────┴───────────────┘
```

- Header: 56px fixed
- Left sidebar: 280px (collapsible to 56px icons)
- Right panel: 340px (collapsible)
- Main: fluid; min-height `calc(100vh - 56px)`

---

## 4. Component variants

### Cards / panels
- `glass` — default research surface
- `solid` — denser nested forms
- `critical` — rose border for tox / collapse flags
- `active` — cyan glow when selected

### Badges (severity)
| Severity | Condition | Color |
| --- | --- | --- |
| `healthy` | HSI &lt; 0.35 | lime |
| `moderate` | 0.35 ≤ HSI &lt; 0.55 | amber |
| `elevated` | 0.55 ≤ HSI &lt; 0.75 | rose soft |
| `critical` | HSI ≥ 0.75 | rose |

PDS uses the same ladder on a 0–1 normalized score.

### Buttons
- `primary` — cyan fill / void text
- `ghost` — transparent + cyan border
- `danger` — rose outline
- `mono` — JetBrains Mono for run / scrub actions

### Sliders
Track `#1E293B`, fill cyan gradient, thumb 14px with cyan ring. Show live
value in mono to the right (`C₀ = 2.50 μM`).

---

## 5. Motion

- Panel expand/collapse: 180ms ease-out
- Tab switch fade: 120ms
- Telemetry pulse (online): 2s opacity breathe on lime dot
- Trajectory scrubber: no spring — linear time mapping only

---

## 6. Chart / graph grammar

- Trajectory series palette (ordered): cyan, teal, amber, rose, lime, slate-300
- Washout band: amber at 12% opacity
- Activation edges: teal; inhibition: rose; phospho: cyan dashed
- Integrated-gradient heat: map |attribution| → cyan intensity on nodes

---

## 7. Accessibility

- Focus rings: `2px solid #00E5FF`, offset 2px
- Contrast: primary text on void ≥ WCAG AA
- All sliders keyboard operable (←/→ step, Shift for 10×)

---

## 8. File map

| Path | Role |
| --- | --- |
| `DESIGN.md` | This document |
| `src/ui/design_system.ts` | Typed tokens + helpers |
| `src/ui/components/*` | Studio components |
| `src/ui/api/client.ts` | REST/WS typed client + hooks |
| `src/index.css` | Tailwind + CSS variable bridge |
