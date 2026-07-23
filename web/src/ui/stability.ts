/** Shared UI stability helpers — debounce + empty encyclopedia fallback. */

import type { EncyclopediaCard } from "./api/types";

export function debounce<T extends (...args: never[]) => void>(fn: T, ms: number): T & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const wrapped = ((...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, ms);
  }) as T & { cancel: () => void };
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return wrapped;
}

/** Stable stub card when a node has no UniProt-style metadata. */
export function emptyEncyclopediaCard(nodeId: string, label?: string): EncyclopediaCard {
  const title = label || nodeId || "Unknown";
  return {
    card_type: "protein",
    title,
    subtitle: "Select a biological entity to inspect",
    identity: {
      gene_symbol: title,
      full_name: null,
      uniprot_id: null,
      kegg_id: null,
      aliases: [],
      species: "Homo sapiens",
    },
    biology: {
      cellular_localization: null,
      domains: [],
      ptm_sites: [],
      pathway_membership: [],
    },
    structure: {
      pdb_id: null,
      alphafold_plddt_score: null,
      disruption_delta: 0,
    },
    clinical: {
      diseases: [],
      somatic_mutations: [],
      clinical_significance: null,
      oncogene: false,
      tumor_suppressor: false,
    },
    drugs: [],
    kinetics: {},
    state: { entity_id: nodeId },
    entity_id: nodeId,
  };
}
