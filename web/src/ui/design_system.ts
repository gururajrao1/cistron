/**
 * CISTRON V1 design tokens — Life Sciences Enterprise aesthetic
 */

export const colors = {
  bg: {
    void: "#0B0F17",
    panel: "rgba(19, 27, 46, 0.88)",
    panelSolid: "#131B2E",
    elevated: "#182338",
    track: "#1E293B",
  },
  border: {
    subtle: "rgba(148, 163, 184, 0.14)",
    cyan: "#00F0FF",
    cyanMuted: "rgba(0, 240, 255, 0.28)",
  },
  text: {
    primary: "#F8FAFC",
    secondary: "#94A3B8",
    muted: "#64748B",
    inverse: "#0B0F17",
  },
  accent: {
    cyan: "#00F0FF",
    teal: "#2DD4BF",
    amber: "#FFB800",
    rose: "#FB7185",
    lime: "#00E676",
    emerald: "#00E676",
  },
} as const;

export const typography = {
  sans: '"IBM Plex Sans", Inter, ui-sans-serif, system-ui, sans-serif',
  mono: '"IBM Plex Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
  sizes: {
    xs: "11px",
    sm: "12px",
    md: "13px",
    lg: "14px",
    xl: "18px",
    display: "22px",
  },
} as const;

export const layout = {
  headerHeight: 56,
  sidebarWidth: 220,
  sidebarCollapsed: 56,
  rightPanelWidth: 360,
  radius: {
    sm: 6,
    md: 10,
    lg: 14,
  },
  blur: "18px",
} as const;

export type HsiSeverity = "healthy" | "moderate" | "elevated" | "critical";

export const HSI_THRESHOLDS = {
  healthy: 0.35,
  moderate: 0.55,
  elevated: 0.75,
} as const;

export function hsiSeverity(hsi: number): HsiSeverity {
  if (hsi < HSI_THRESHOLDS.healthy) return "healthy";
  if (hsi < HSI_THRESHOLDS.moderate) return "moderate";
  if (hsi < HSI_THRESHOLDS.elevated) return "elevated";
  return "critical";
}

export const severityColor: Record<HsiSeverity, string> = {
  healthy: colors.accent.emerald,
  moderate: colors.accent.amber,
  elevated: colors.accent.rose,
  critical: colors.accent.rose,
};

export type PanelVariant = "glass" | "solid" | "critical" | "active";

export const seriesPalette = [
  colors.accent.cyan,
  colors.accent.teal,
  colors.accent.amber,
  colors.accent.rose,
  colors.accent.emerald,
  "#CBD5E1",
] as const;

/** Tailwind class abstractions — V1 glassmorphic surfaces */
export const tw = {
  glass:
    "bg-[rgba(19,27,46,0.88)] backdrop-blur-[18px] border border-[rgba(0,240,255,0.22)] rounded-[10px]",
  glassActive:
    "bg-[rgba(19,27,46,0.94)] backdrop-blur-[18px] border border-[#00F0FF] rounded-[10px] shadow-[0_0_0_1px_rgba(0,240,255,0.35),0_0_22px_rgba(0,240,255,0.14)]",
  glassCritical:
    "bg-[rgba(19,27,46,0.88)] backdrop-blur-[18px] border border-[#FFB800]/55 rounded-[10px]",
  solid: "bg-[#131B2E] border border-[rgba(148,163,184,0.14)] rounded-[10px]",
  label: "text-[12px] font-medium text-[#94A3B8] tracking-wide",
  mono: "font-mono text-[12px] text-[#F8FAFC] tabular-nums",
  title: "text-[13px] font-semibold text-[#F8FAFC]",
  btnPrimary:
    "inline-flex items-center justify-center gap-2 rounded-[6px] bg-[#00F0FF] px-3 py-1.5 text-[12px] font-semibold text-[#0B0F17] hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#00F0FF]",
  btnGhost:
    "inline-flex items-center justify-center gap-2 rounded-[6px] border border-[rgba(0,240,255,0.28)] bg-transparent px-3 py-1.5 text-[12px] font-medium text-[#00F0FF] hover:border-[#00F0FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#00F0FF]",
  input:
    "w-full rounded-[6px] border border-[rgba(148,163,184,0.14)] bg-[#182338] px-2.5 py-1.5 font-mono text-[12px] text-[#F8FAFC] outline-none focus:border-[#00F0FF]",
} as const;

export function panelClasses(variant: PanelVariant = "glass"): string {
  switch (variant) {
    case "active":
      return tw.glassActive;
    case "critical":
      return tw.glassCritical;
    case "solid":
      return tw.solid;
    default:
      return tw.glass;
  }
}

export function clsx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
