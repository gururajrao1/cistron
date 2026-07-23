import type {

  AgentPlanRequest,

  AgentPlanResult,

  CausalNarrativePayload,

  DoseParams,

  DockingPose,

  EncyclopediaCard,

  MetricSnapshot,

  PatientBadge,

  PatientNetwork,

  SimulationRequest,

  SimulationRun,

  SystemHealth,

  TrajectorySeries,

} from "./types";



const MAPK_SPECIES = ["EGF", "EGFR", "RAS", "RAF", "MEK", "ERK"] as const;

const CROSSTALK_SPECIES = [

  "EGF",

  "EGFR",

  "RAS",

  "RAF",

  "MEK",

  "ERK",

  "PI3K",

  "AKT",

  "JAK",

  "STAT",

  "TP53",

] as const;

const COLORS = [

  "#00E5FF",

  "#2DD4BF",

  "#FBBF24",

  "#FB7185",

  "#A3E635",

  "#CBD5E1",

  "#38BDF8",

  "#C084FC",

  "#F472B6",

  "#FCD34D",

  "#94A3B8",

];



function linspace(n: number, t0: number, t1: number): number[] {

  if (n <= 1) return [t0];

  return Array.from({ length: n }, (_, i) => t0 + ((t1 - t0) * i) / (n - 1));

}



function synthSeries(

  name: string,

  color: string,

  t: number[],

  doses: DoseParams[],

  baseAmp: number,

): TrajectorySeries {

  const drug = doses.find((d) => d.enabled && d.target === name);

  const inhibit = drug ? Math.min(0.85, drug.c0 / (drug.c0 + 2.5)) : 0;

  const y = t.map((ti) => {

    const rise = 1 - Math.exp(-ti / 3.2);

    const osc = 0.08 * Math.sin(ti * 0.55);

    let val = baseAmp * rise + osc;

    if (drug && ti >= drug.tStart && ti <= drug.tEnd) {

      const local = (ti - drug.tStart) / Math.max(1e-6, drug.tEnd - drug.tStart);

      val *= 1 - inhibit * (0.35 + 0.65 * local);

    } else if (drug && ti > drug.tEnd) {

      const recovery = 1 - Math.exp(-(ti - drug.tEnd) / 4);

      val *= 1 - inhibit * (1 - recovery) * 0.9;

    }

    return Math.max(0, val);

  });

  return { id: name, name, color, t: [...t], y };

}



function proteinCard(partial: EncyclopediaCard): EncyclopediaCard {

  return partial;

}



export const ENCYCLOPEDIA: Record<string, EncyclopediaCard> = {

  EGFR: proteinCard({

    card_type: "protein",

    title: "EGFR",

    subtitle: "Epidermal growth factor receptor",

    identity: {

      gene_symbol: "EGFR",

      full_name: "Epidermal growth factor receptor",

      uniprot_id: "P00533",

      kegg_id: "hsa:1956",

      aliases: ["ERBB1", "HER1"],

      species: "Homo sapiens",

    },

    biology: {

      is_enzyme: true,

      cellular_localization: "Plasma Membrane",

      domains: [

        { name: "kinase", start: 712, end: 979, domain_type: "kinase", active: true },

        { name: "TM", start: 646, end: 668, domain_type: "transmembrane", active: true },

      ],

      ptm_sites: [

        {

          name: "Tyr1068",

          residue: "Tyr1068",

          modification: "phosphorylation",

          stoichiometry: 1,

          occupancy: 0.85,

          active: true,

        },

      ],

      pathway_membership: ["MAPK", "PI3K-AKT"],

    },

    structure: {

      pdb_id: "1M17",

      alphafold_plddt_score: 86.5,

      disruption_delta: 0,

    },

    clinical: {

      diseases: ["NSCLC", "glioblastoma"],

      somatic_mutations: ["EGFR p.L858R"],

      oncogene: true,

      clinical_significance: "pathogenic",

    },

    drugs: [

      {

        name: "Gefitinib",

        mechanism: "inhibitor",

        ic50_nM: 33,

        approval_status: "approved",

      },

    ],

    kinetics: { k_cat: 2.0, Km: 0.5 },

  }),

  RAS: proteinCard({

    card_type: "protein",

    title: "KRAS",

    subtitle: "GTPase KRas",

    identity: {

      gene_symbol: "KRAS",

      full_name: "GTPase KRas",

      uniprot_id: "P01116",

      aliases: ["RAS", "KRAS2"],

      species: "Homo sapiens",

    },

    biology: {

      cellular_localization: "Plasma Membrane",

      domains: [{ name: "G domain", start: 1, end: 166, domain_type: "GTPase", active: true }],

      ptm_sites: [],

      pathway_membership: ["MAPK", "PI3K-AKT"],

    },

    structure: { pdb_id: "4OBE", alphafold_plddt_score: 91.2 },

    clinical: {

      diseases: ["CRC", "PDAC", "NSCLC"],

      somatic_mutations: ["KRAS p.G12D"],

      oncogene: true,

    },

    drugs: [],

    kinetics: {},

  }),

  RAF: proteinCard({

    card_type: "protein",

    title: "BRAF",

    subtitle: "Serine/threonine-protein kinase B-raf",

    identity: {

      gene_symbol: "BRAF",

      full_name: "Serine/threonine-protein kinase B-raf",

      uniprot_id: "P15056",

      aliases: ["RAF", "BRAF1"],

      species: "Homo sapiens",

    },

    biology: {

      is_enzyme: true,

      cellular_localization: "Cytosol",

      domains: [{ name: "kinase", start: 457, end: 717, domain_type: "kinase", active: true }],

      pathway_membership: ["MAPK"],

    },

    structure: { pdb_id: "4XV2", alphafold_plddt_score: 84.0 },

    clinical: { diseases: ["melanoma"], somatic_mutations: [], oncogene: true },

    drugs: [{ name: "Vemurafenib", mechanism: "inhibitor", ic50_nM: 31, approval_status: "approved" }],

  }),

  MEK: proteinCard({

    card_type: "protein",

    title: "MAP2K1",

    subtitle: "Dual specificity MAP kinase kinase 1",

    identity: {

      gene_symbol: "MAP2K1",

      full_name: "Dual specificity mitogen-activated protein kinase kinase 1",

      uniprot_id: "Q02750",

      aliases: ["MEK", "MEK1"],

      species: "Homo sapiens",

    },

    biology: {

      is_enzyme: true,

      cellular_localization: "Cytosol",

      domains: [{ name: "kinase", start: 68, end: 369, domain_type: "kinase", active: true }],

      pathway_membership: ["MAPK"],

    },

    structure: { pdb_id: "3EQC", alphafold_plddt_score: 88.1 },

    clinical: { diseases: [], somatic_mutations: [] },

    drugs: [

      { name: "Trametinib", mechanism: "inhibitor", ic50_nM: 0.92, approval_status: "approved" },

    ],

  }),

  ERK: proteinCard({

    card_type: "protein",

    title: "MAPK1",

    subtitle: "Mitogen-activated protein kinase 1",

    identity: {

      gene_symbol: "MAPK1",

      full_name: "Mitogen-activated protein kinase 1",

      uniprot_id: "P28482",

      aliases: ["ERK", "ERK2"],

      species: "Homo sapiens",

    },

    biology: {

      is_enzyme: true,

      cellular_localization: "Cytosol / Nucleus",

      domains: [{ name: "kinase", start: 23, end: 313, domain_type: "kinase", active: true }],

      ptm_sites: [

        {

          name: "Thr202",

          residue: "Thr202",

          modification: "phosphorylation",

          stoichiometry: 1,

          occupancy: 0.7,

          active: true,

        },

        {

          name: "Tyr204",

          residue: "Tyr204",

          modification: "phosphorylation",

          stoichiometry: 1,

          occupancy: 0.7,

          active: true,

        },

      ],

      pathway_membership: ["MAPK"],

    },

    structure: { pdb_id: "4QTB", alphafold_plddt_score: 92.4 },

    clinical: { diseases: [], somatic_mutations: [] },

    drugs: [],

  }),

  PI3K: proteinCard({

    card_type: "protein",

    title: "PIK3CA",

    subtitle: "PI3K catalytic subunit alpha",

    identity: {

      gene_symbol: "PIK3CA",

      full_name: "Phosphatidylinositol 4,5-bisphosphate 3-kinase catalytic subunit alpha",

      uniprot_id: "P42336",

      aliases: ["PI3K", "p110α"],

      species: "Homo sapiens",

    },

    biology: {

      is_enzyme: true,

      cellular_localization: "Plasma Membrane",

      domains: [{ name: "kinase", start: 696, end: 1068, domain_type: "kinase", active: true }],

      pathway_membership: ["PI3K-AKT"],

    },

    structure: { pdb_id: "4L2Y", alphafold_plddt_score: 80.5 },

    clinical: { diseases: ["breast cancer"], somatic_mutations: [], oncogene: true },

    drugs: [{ name: "Wortmannin", mechanism: "inhibitor", ic50_nM: 5.0, approval_status: "research" }],

  }),

  AKT: proteinCard({

    card_type: "protein",

    title: "AKT1",

    subtitle: "RAC-alpha serine/threonine-protein kinase",

    identity: {

      gene_symbol: "AKT1",

      full_name: "RAC-alpha serine/threonine-protein kinase",

      uniprot_id: "P31749",

      aliases: ["AKT", "PKB"],

      species: "Homo sapiens",

    },

    biology: {

      is_enzyme: true,

      cellular_localization: "Cytosol",

      pathway_membership: ["PI3K-AKT"],

    },

    structure: { pdb_id: "3O96", alphafold_plddt_score: 87.0 },

    clinical: { diseases: [], somatic_mutations: [] },

    drugs: [],

  }),

  JAK: proteinCard({

    card_type: "protein",

    title: "JAK2",

    subtitle: "Tyrosine-protein kinase JAK2",

    identity: {

      gene_symbol: "JAK2",

      full_name: "Tyrosine-protein kinase JAK2",

      uniprot_id: "O60674",

      aliases: ["JAK"],

      species: "Homo sapiens",

    },

    biology: {

      is_enzyme: true,

      cellular_localization: "Cytosol",

      pathway_membership: ["JAK-STAT"],

    },

    structure: { pdb_id: "3KRR", alphafold_plddt_score: 79.0 },

    clinical: { diseases: ["MPN"], somatic_mutations: [], oncogene: true },

    drugs: [{ name: "Ruxolitinib", mechanism: "inhibitor", ic50_nM: 3.3, approval_status: "approved" }],

  }),

  STAT: proteinCard({

    card_type: "protein",

    title: "STAT3",

    subtitle: "Signal transducer and activator of transcription 3",

    identity: {

      gene_symbol: "STAT3",

      full_name: "Signal transducer and activator of transcription 3",

      uniprot_id: "P40763",

      aliases: ["STAT"],

      species: "Homo sapiens",

    },

    biology: {

      cellular_localization: "Nucleus",

      pathway_membership: ["JAK-STAT"],

    },

    structure: { pdb_id: "6NJS", alphafold_plddt_score: 82.0 },

    clinical: { diseases: [], somatic_mutations: [] },

    drugs: [],

  }),

  TP53: proteinCard({

    card_type: "gene",

    title: "TP53",

    subtitle: "Tumor protein p53",

    identity: {

      gene_symbol: "TP53",

      full_name: "Tumor protein p53",

      uniprot_id: "P04637",

      kegg_id: "hsa:7157",

      aliases: ["p53"],

      species: "Homo sapiens",

      chromosomal_locus: "chr17:7661779-7687550",

    },

    biology: {

      cellular_localization: "Nucleus",

      pathway_membership: ["JAK-STAT"],

    },

    clinical: {

      diseases: ["Li-Fraumeni"],

      somatic_mutations: ["TP53 p.R213*"],

      tumor_suppressor: true,

    },

    drugs: [],

  }),

  EGF: proteinCard({

    card_type: "protein",

    title: "EGF",

    subtitle: "Pro-epidermal growth factor",

    identity: {

      gene_symbol: "EGF",

      full_name: "Pro-epidermal growth factor",

      uniprot_id: "P01133",

      species: "Homo sapiens",

    },

    biology: {

      cellular_localization: "Extracellular",

      pathway_membership: ["MAPK"],

    },

    clinical: { diseases: [], somatic_mutations: [] },

    drugs: [],

  }),

};



export const MOCK_HEALTH: SystemHealth = {

  status: "online",

  odeSolver: "MassActionRHS / RK4",

  workers: 4,

  version: "0.19.0",

  uptimeSec: 12_480,

};



export const MOCK_PATIENT: PatientBadge = {

  patientId: "CLIN_MULTIHIT_01",

  vcfName: "multihit_clinical.vcf",

  variants: [

    { gene: "EGFR", hgvs: "p.L858R", delta: 1.0 },

    { gene: "KRAS", hgvs: "p.G12D", delta: 1.0 },

    { gene: "TP53", hgvs: "p.R213*", delta: 1.0 },

  ],

  pathwayId: "hsa04010",

};



export const DEFAULT_DOSES: DoseParams[] = [

  {

    agentId: "agent:MEK",

    target: "MEK",

    enabled: true,

    c0: 2.5,

    tStart: 2,

    tEnd: 15,

    ki: 1.2e-9,

  },

  {

    agentId: "agent:RAF",

    target: "RAF",

    enabled: true,

    c0: 2.125,

    tStart: 2,

    tEnd: 15,

    ki: 3.4e-9,

  },

  {

    agentId: "agent:EGFR",

    target: "EGFR",

    enabled: false,

    c0: 1.0,

    tStart: 2,

    tEnd: 12,

  },

];



export function mockMetrics(doses: DoseParams[]): MetricSnapshot {

  const active = doses.filter((d) => d.enabled);

  const pressure = active.reduce((s, d) => s + d.c0, 0);

  const hsi = Math.max(0.18, 0.73 - pressure * 0.07);

  const pds = Math.max(0.12, 0.68 - pressure * 0.06);

  const las = Math.min(0.92, 0.42 + active.length * 0.05 + pressure * 0.02);

  return {

    hsi,

    pds,

    las,

    toxicity: Math.min(10, pressure * 0.9),

    readout: "ERK",

    readoutValue: Math.max(0.08, 1.35 - pressure * 0.18),

  };

}



function mockCausal(doses: DoseParams[], crosstalk: boolean): CausalNarrativePayload {

  const mekOn = doses.some((d) => d.enabled && d.target === "MEK");

  const pi3kBlocked = crosstalk;

  const cascade = crosstalk

    ? ["EGF", "EGFR", "RAS", "RAF", "MEK", "ERK"]

    : ["EGF", "EGFR", "RAS", "RAF", "MEK", "ERK"];



  const activated = [

    {

      node_id: "ERK",

      node_name: "ERK",

      kind: "activation" as const,

      percent_change: mekOn ? 42 : 112,

      control_final: 0.4,

      perturbed_final: mekOn ? 0.57 : 0.85,

      narrative: mekOn

        ? "ERK remained partially elevated (+42%) because oncogenic KRAS p.G12D continued to drive RAF → MEK flux despite MEK inhibitor pressure."

        : "ERK became hyperactive (+112%) because an oncogenic KRAS p.G12D mutation locked RAS in a GTP-bound state, continuously driving RAF → MEK → ERK phosphorylation.",

      chain: [

        {

          source_name: "RAS",

          target_name: "RAF",

          interaction: "activation",

          evidence: "KRAS G12D locks GTP-bound RAS, elevating RAF recruitment.",

          attribution: 0.9,

        },

        {

          source_name: "RAF",

          target_name: "MEK",

          interaction: "phosphorylation",

          evidence: "RAF phosphorylates MEK, amplifying cascade flux.",

          attribution: 0.7,

        },

        {

          source_name: "MEK",

          target_name: "ERK",

          interaction: "phosphorylation",

          evidence: "MEK dual-phosphorylates ERK at Thr202/Tyr204.",

          attribution: 0.85,

        },

      ],

      mutations: ["KRAS p.G12D", "EGFR p.L858R"],

      drugs: mekOn ? ["Trametinib"] : [],

      pathways: ["MAPK"],

      confidence: 0.88,

    },

  ];



  const inactivated = pi3kBlocked

    ? [

        {

          node_id: "AKT",

          node_name: "AKT",

          kind: "inactivation" as const,

          percent_change: -90,

          control_final: 0.5,

          perturbed_final: 0.05,

          narrative:

            "AKT remained inactive because PI3K was competitively blocked by Wortmannin.",

          chain: [

            {

              source_name: "PI3K",

              target_name: "AKT",

              interaction: "activation",

              evidence: "Loss of PI3K lipid kinase activity starves AKT of PIP3.",

              attribution: 0.8,

            },

          ],

          mutations: [],

          drugs: ["Wortmannin"],

          pathways: ["PI3K-AKT"],

          confidence: 0.84,

        },

      ]

    : mekOn

      ? [

          {

            node_id: "MEK",

            node_name: "MEK",

            kind: "inactivation" as const,

            percent_change: -55,

            control_final: 0.9,

            perturbed_final: 0.4,

            narrative:

              "MEK was suppressed (-55%) because MEK was competitively blocked by Trametinib.",

            chain: [

              {

                source_name: "RAF",

                target_name: "MEK",

                interaction: "phosphorylation",

                evidence: "Drug occupancy at the MEK allosteric pocket dampens catalytic output.",

                attribution: 0.75,

              },

            ],

            mutations: [],

            drugs: ["Trametinib"],

            pathways: ["MAPK"],

            confidence: 0.81,

          },

        ]

      : [];



  return {

    control_label: "Control (Healthy)",

    perturbed_label: "Perturbed (Mutant/Treated)",

    overview_narrative: crosstalk

      ? "Comparing Control (Healthy) vs Perturbed (Mutant/Treated): hyperactivated nodes include RAS, MEK, ERK. suppressed nodes include AKT, PI3K. Crosstalk hubs EGFR/RAS bridge MAPK and PI3K-AKT."

      : "Comparing Control (Healthy) vs Perturbed (Mutant/Treated): MAPK cascade shows oncogenic drive at RAS→ERK with optional MEK/RAF pharmacologic suppression.",

    cascade,

    activated,

    inactivated,

    stable: crosstalk ? ["EGFR", "JAK"] : ["EGF", "EGFR"],

  };

}



export function mockSimulation(request: SimulationRequest): SimulationRun {

  const crosstalk = request.pathwayId === "crosstalk_multi";

  const species = crosstalk ? CROSSTALK_SPECIES : MAPK_SPECIES;

  const n = Math.max(20, Math.round(request.tHorizon / request.dt) + 1);

  const t = linspace(n, 0, request.tHorizon);

  const amps: Record<string, number> = {

    EGF: 1.0,

    EGFR: 1.15,

    RAS: 1.05,

    RAF: 1.1,

    MEK: 1.2,

    ERK: 1.35,

    PI3K: 0.95,

    AKT: 1.0,

    JAK: 0.7,

    STAT: 0.75,

    TP53: 0.55,

  };

  const series = species.map((name, i) =>

    synthSeries(name, COLORS[i % COLORS.length]!, t, request.doses, amps[name] ?? 1),

  );

  const wash = request.doses.find((d) => d.enabled);

  return {

    runId: `run_${Date.now().toString(36)}`,

    status: "complete",

    request,

    series,

    washout: wash ? { tStart: wash.tStart, tEnd: wash.tEnd } : undefined,

    metrics: mockMetrics(request.doses),

    causal: mockCausal(request.doses, crosstalk),

  };

}



function withCard(

  node: PatientNetwork["nodes"][number],

): PatientNetwork["nodes"][number] {

  const card = ENCYCLOPEDIA[node.label] ?? ENCYCLOPEDIA[node.id];

  return card ? { ...node, encyclopedia: card } : node;

}



export const MOCK_NETWORK: PatientNetwork = {

  patientId: MOCK_PATIENT.patientId,

  pathwayId: MOCK_PATIENT.pathwayId,

  pathway_mode: "single",

  nodes: [

    { id: "EGF", label: "EGF", x: 80, y: 160, centrality: 0.22, attribution: 0.1, pathways: ["MAPK"] },

    {

      id: "EGFR",

      label: "EGFR",

      x: 200,

      y: 160,

      centrality: 0.71,

      attribution: 0.82,

      mutated: true,

      crosstalk_hub: true,

      pathways: ["MAPK", "PI3K-AKT"],

    },

    {

      id: "RAS",

      label: "RAS",

      x: 320,

      y: 100,

      centrality: 0.55,

      attribution: 0.48,

      mutated: true,

      crosstalk_hub: true,

      pathways: ["MAPK", "PI3K-AKT"],

    },

    { id: "RAF", label: "RAF", x: 440, y: 100, centrality: 0.61, attribution: 0.55, pathways: ["MAPK"] },

    { id: "MEK", label: "MEK", x: 560, y: 160, centrality: 0.66, attribution: 0.7, pathways: ["MAPK"] },

    { id: "ERK", label: "ERK", x: 680, y: 160, centrality: 0.8, attribution: 0.91, pathways: ["MAPK"] },

    { id: "TP53", label: "TP53", x: 440, y: 260, centrality: 0.4, attribution: 0.35, mutated: true, pathways: ["JAK-STAT"] },

  ].map(withCard),

  edges: [

    { id: "e1", source: "EGF", target: "EGFR", kind: "activation", weight: 1.0 },

    { id: "e2", source: "EGFR", target: "RAS", kind: "activation", weight: 0.9 },

    { id: "e3", source: "RAS", target: "RAF", kind: "activation", weight: 0.85 },

    { id: "e4", source: "RAF", target: "MEK", kind: "phosphorylation", weight: 0.95 },

    { id: "e5", source: "MEK", target: "ERK", kind: "phosphorylation", weight: 1.0 },

    { id: "e6", source: "ERK", target: "TP53", kind: "activation", weight: 0.4 },

    { id: "e7", source: "TP53", target: "EGFR", kind: "inhibition", weight: 0.35 },

  ],

  crosstalk_hubs: [

    { entity_id: "EGFR", name: "EGFR", gene_symbol: "EGFR", pathways: ["MAPK", "PI3K-AKT"], degree: 3, switch_kind: "shared_hub" },

    { entity_id: "RAS", name: "RAS", gene_symbol: "KRAS", pathways: ["MAPK", "PI3K-AKT"], degree: 3, switch_kind: "shared_hub" },

  ],

};



export const MOCK_CROSSTALK_NETWORK: PatientNetwork = {

  patientId: MOCK_PATIENT.patientId,

  pathwayId: "crosstalk_multi",

  pathway_mode: "crosstalk",

  nodes: [

    { id: "EGF", label: "EGF", x: 60, y: 180, centrality: 0.2, attribution: 0.1, pathways: ["MAPK"] },

    {

      id: "EGFR",

      label: "EGFR",

      x: 160,

      y: 180,

      centrality: 0.85,

      attribution: 0.9,

      mutated: true,

      crosstalk_hub: true,

      pathways: ["MAPK", "PI3K-AKT"],

    },

    {

      id: "RAS",

      label: "RAS",

      x: 280,

      y: 120,

      centrality: 0.8,

      attribution: 0.88,

      mutated: true,

      crosstalk_hub: true,

      pathways: ["MAPK", "PI3K-AKT"],

    },

    { id: "RAF", label: "RAF", x: 400, y: 80, centrality: 0.55, attribution: 0.5, pathways: ["MAPK"] },

    { id: "MEK", label: "MEK", x: 520, y: 80, centrality: 0.6, attribution: 0.65, pathways: ["MAPK"] },

    { id: "ERK", label: "ERK", x: 640, y: 80, centrality: 0.75, attribution: 0.9, pathways: ["MAPK"] },

    { id: "PI3K", label: "PI3K", x: 400, y: 200, centrality: 0.58, attribution: 0.55, pathways: ["PI3K-AKT"] },

    { id: "AKT", label: "AKT", x: 520, y: 200, centrality: 0.62, attribution: 0.5, pathways: ["PI3K-AKT"] },

    { id: "JAK", label: "JAK", x: 280, y: 300, centrality: 0.4, attribution: 0.3, pathways: ["JAK-STAT"] },

    { id: "STAT", label: "STAT", x: 400, y: 300, centrality: 0.45, attribution: 0.35, pathways: ["JAK-STAT"] },

    {

      id: "TP53",

      label: "TP53",

      x: 560,

      y: 300,

      centrality: 0.5,

      attribution: 0.4,

      mutated: true,

      crosstalk_hub: true,

      pathways: ["JAK-STAT", "MAPK"],

    },

  ].map(withCard),

  edges: [

    { id: "c1", source: "EGF", target: "EGFR", kind: "activation", weight: 1 },

    { id: "c2", source: "EGFR", target: "RAS", kind: "activation", weight: 0.95 },

    { id: "c3", source: "RAS", target: "RAF", kind: "activation", weight: 0.9 },

    { id: "c4", source: "RAF", target: "MEK", kind: "phosphorylation", weight: 0.95 },

    { id: "c5", source: "MEK", target: "ERK", kind: "phosphorylation", weight: 1 },

    { id: "c6", source: "EGFR", target: "PI3K", kind: "activation", weight: 0.85 },

    { id: "c7", source: "RAS", target: "PI3K", kind: "activation", weight: 0.8 },

    { id: "c8", source: "PI3K", target: "AKT", kind: "activation", weight: 0.9 },

    { id: "c9", source: "JAK", target: "STAT", kind: "phosphorylation", weight: 0.85 },

    { id: "c10", source: "ERK", target: "TP53", kind: "activation", weight: 0.45 },

    { id: "c11", source: "STAT", target: "TP53", kind: "activation", weight: 0.4 },

  ],

  crosstalk_hubs: [

    { entity_id: "EGFR", name: "EGFR", gene_symbol: "EGFR", pathways: ["MAPK", "PI3K-AKT"], degree: 4, switch_kind: "shared_hub" },

    { entity_id: "RAS", name: "RAS", gene_symbol: "KRAS", pathways: ["MAPK", "PI3K-AKT"], degree: 4, switch_kind: "shared_hub" },

    { entity_id: "TP53", name: "TP53", gene_symbol: "TP53", pathways: ["JAK-STAT", "MAPK"], degree: 2, switch_kind: "bridge_endpoint" },

  ],

};



export function networkForPathway(pathwayId: string, patientId: string): PatientNetwork {

  if (pathwayId === "crosstalk_multi") {

    return { ...MOCK_CROSSTALK_NETWORK, patientId, pathwayId };

  }

  if (pathwayId === "hsa04151") {

    const nodes = MOCK_CROSSTALK_NETWORK.nodes.filter((n) =>

      (n.pathways ?? []).includes("PI3K-AKT") || n.id === "EGFR" || n.id === "RAS",

    );

    const ids = new Set(nodes.map((n) => n.id));

    return {

      patientId,

      pathwayId,

      pathway_mode: "single",

      nodes,

      edges: MOCK_CROSSTALK_NETWORK.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),

      crosstalk_hubs: MOCK_CROSSTALK_NETWORK.crosstalk_hubs?.filter((h) => ids.has(h.entity_id)),

    };

  }

  return { ...MOCK_NETWORK, patientId, pathwayId };

}



export const MOCK_DOCKING: DockingPose = {
  ligandId: "Erlotinib",
  receptorId: "1M17",
  deltaG: -9.4,
  ki: 1.2e-9,
  contacts: 38,
  hbonds: 3,
  atoms: [
    { serial: 1, name: "N1", element: "N", x: 3, y: 0, z: 0, role: "receptor" },
    { serial: 2, name: "O1", element: "O", x: 0, y: 3, z: 0, role: "receptor" },
    { serial: 3, name: "O2", element: "O", x: -3, y: 0, z: 0, role: "receptor" },
    { serial: 4, name: "N2", element: "N", x: 0, y: -3, z: 0, role: "receptor" },
    { serial: 5, name: "C1", element: "C", x: 2.2, y: 2.2, z: 0.5, role: "receptor" },
    { serial: 6, name: "C2", element: "C", x: -2.2, y: 2.2, z: -0.5, role: "receptor" },
    { serial: 7, name: "C3", element: "C", x: -2.2, y: -2.2, z: 0.4, role: "receptor" },
    { serial: 8, name: "C4", element: "C", x: 2.2, y: -2.2, z: -0.4, role: "receptor" },
    { serial: 101, name: "C1", element: "C", x: 0, y: 0, z: 0, role: "ligand" },
    { serial: 102, name: "N1", element: "N", x: 0, y: 1.35, z: 0, role: "ligand" },
    { serial: 103, name: "H1", element: "H", x: 0, y: 2.15, z: 0, role: "ligand" },
    { serial: 104, name: "O1", element: "O", x: 1.35, y: 0, z: 0, role: "ligand" },
    { serial: 105, name: "C2", element: "C", x: -1.2, y: -0.3, z: 0.2, role: "ligand" },
  ],
  bonds: [
    { a: 101, b: 102, role: "ligand" },
    { a: 102, b: 103, role: "ligand" },
    { a: 101, b: 104, role: "ligand" },
    { a: 101, b: 105, role: "ligand" },
    { a: 5, b: 1, role: "receptor" },
    { a: 5, b: 2, role: "receptor" },
    { a: 6, b: 2, role: "receptor" },
    { a: 6, b: 3, role: "receptor" },
    { a: 7, b: 3, role: "receptor" },
    { a: 7, b: 4, role: "receptor" },
    { a: 8, b: 4, role: "receptor" },
    { a: 8, b: 1, role: "receptor" },
    { a: 103, b: 2, role: "hbond" },
    { a: 104, b: 1, role: "hbond" },
  ],
};



const BRIEF = `# Clinical Discovery Brief — Multi-Hit Oncology



**VOIDSIGNAL** Research Studio · patient \`CLIN_MULTIHIT_01\`



## Profile

- VCF: \`multihit_clinical.vcf\` (EGFR p.L858R, KRAS p.G12D, TP53 p.R213*)

- Pathway: hsa04010 (MAPK)

- Pre-treatment HSI: **0.730**

- Post-treatment HSI: **0.353**

- LAS: **0.521**



## Hypothesis

Dual MEK/RAF inhibition suppresses ERK over-activation in an EGFR-driven background while respecting toxicity constraints.



## Selected regimen

| Agent | Target | C₀ | Window |

| --- | --- | --- | --- |

| agent:MEK | MEK | 2.50 | [2, 15] |

| agent:RAF | RAF | 2.125 | [2, 15] |



## Outcome

Objective met. Readout ERK reduced ~50% under combo; HSI restored toward homeostasis.

`;



export function mockAgentPlan(req: AgentPlanRequest): AgentPlanResult {

  const now = Date.now();

  return {

    planId: `plan_${now.toString(36)}`,

    status: "complete",

    las: 0.5206,

    briefMarkdown: BRIEF,

    selectedDoses: DEFAULT_DOSES.filter((d) => d.enabled),

    metrics: mockMetrics(DEFAULT_DOSES),

    logs: [

      {

        id: "1",

        t: now - 8000,

        level: "info",

        message: `Parsing goal: "${req.goal}"`,

      },

      {

        id: "2",

        t: now - 6500,

        level: "hypothesis",

        message: "Hypothesis: dual MEK/RAF block halts ERK over-activation (EGFR background).",

      },

      {

        id: "3",

        t: now - 4800,

        level: "experiment",

        message: "Ensemble n=4 · candidates EGFR, MEK, RAF · tox threshold=8",

      },

      {

        id: "4",

        t: now - 2400,

        level: "result",

        message: "Best combo agent:MEK (C0=2.5) + agent:RAF (C0=2.125) · HSI=0.353 · LAS=0.521",

      },

      {

        id: "5",

        t: now - 800,

        level: "info",

        message: "Discovery brief synthesized. Objective met = true.",

      },

    ],

  };

}



export function lookupEncyclopedia(nodeId: string): EncyclopediaCard | null {

  return ENCYCLOPEDIA[nodeId] ?? null;

}

