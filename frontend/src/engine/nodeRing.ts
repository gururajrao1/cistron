/**
 * Node "progress ring" — two concentric activity arcs (baseline vs current),
 * rendered as an SVG data URI so it can drop straight into Cytoscape's
 * per-node `background-image` (no separate DOM/SVG overlay layer to keep in
 * sync with pan/zoom).
 */

const VIEWBOX = 120
const CENTER = VIEWBOX / 2
const RADIUS = 50
const STROKE_WIDTH = 7
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

const TRACK_COLOR = '#1B2836'
const BASELINE_COLOR = '#4E6479'
const CURRENT_COLOR = '#94A3B8'

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

function arc(fraction: number, color: string, opacity: number): string {
  const len = CIRCUMFERENCE * clamp01(fraction)
  return `<circle cx="${CENTER}" cy="${CENTER}" r="${RADIUS}" fill="none" stroke="${color}" stroke-width="${STROKE_WIDTH}" stroke-dasharray="${len.toFixed(2)} ${CIRCUMFERENCE.toFixed(2)}" stroke-linecap="round" opacity="${opacity}" transform="rotate(-90 ${CENTER} ${CENTER})" />`
}

/**
 * Baseline = untreated/pre-perturbation value, current = live/perturbed
 * value. Both are already-real 0..1 activities from LabContext trajectories.
 */
export function nodeRingDataUri(baseline: number, current: number): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${VIEWBOX} ${VIEWBOX}">` +
    `<circle cx="${CENTER}" cy="${CENTER}" r="${RADIUS}" fill="none" stroke="${TRACK_COLOR}" stroke-width="${STROKE_WIDTH}" />` +
    arc(baseline, BASELINE_COLOR, 0.55) +
    arc(current, CURRENT_COLOR, 1) +
    `</svg>`
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}
