"""
VOIDSIGNAL research dashboard (Streamlit) — Phase 9 viz + Phase 10 agent.

Launch::

    streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import sys
import tempfile

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from voidsignal.agent.planner import BiologicalAgentPlanner, ResearchGoal  # noqa: E402
from voidsignal.visualization.session import (  # noqa: E402
    DashboardControls,
    DashboardSession,
    write_demo_vcf,
)

DEFAULT_AGENT_GOAL = (
    "Find a two-drug combination that "
    "halts ERK over-activation in a mutated EGFR background "
    "without exceeding the toxicity threshold"
)


def _require_streamlit() -> Any:
    try:
        import streamlit as st  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Streamlit is required for the interactive dashboard.\n"
            "Install with:  pip install 'voidsignal[ui]'   or   pip install streamlit plotly"
        ) from exc
    return st


def _chart_kwargs() -> dict:
    """Streamlit 1.58+ prefers width=; fall back for older builds."""
    return {"width": "stretch"}


def _render_figure(st: Any, fig_spec: Any, *, key: str) -> None:
    plotly_fig = fig_spec.to_plotly()
    if plotly_fig is not None:
        try:
            st.plotly_chart(plotly_fig, key=key, **_chart_kwargs())
        except TypeError:
            st.plotly_chart(plotly_fig, use_container_width=True, key=key)
    else:
        st.markdown(fig_spec.to_svg(), unsafe_allow_html=True)
        with st.expander(f"ASCII preview ({key})"):
            st.code(fig_spec.to_ascii())


def _dataframe(st: Any, data: Any) -> None:
    try:
        st.dataframe(data, **_chart_kwargs())
    except TypeError:
        st.dataframe(data, use_container_width=True)


def _render_agent_tab(st: Any) -> None:
    st.subheader("BiologicalAgentPlanner")
    st.caption(
        "Phase 10 — NL goal → disease preset → GAT targets → combo PD → "
        "ensemble → tox → LAS → Markdown report (no API key required)."
    )

    goal_text = st.text_area(
        "Research objective",
        value=DEFAULT_AGENT_GOAL,
        height=100,
        key="agent_goal_text",
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        dose = st.number_input(
            "Initial Drug Concentration (uM)",
            min_value=0.1,
            max_value=10.0,
            value=2.0,
            step=0.1,
        )
    with c2:
        t_sim = st.number_input("Horizon", min_value=8.0, max_value=80.0, value=16.0, step=2.0)
    with c3:
        tox_thr = st.number_input("Tox threshold", min_value=0.5, max_value=20.0, value=8.0, step=0.5)
    with c4:
        n_ens = st.number_input("Ensemble n", min_value=3, max_value=12, value=4, step=1)

    run_agent = st.button("Run autonomous campaign", type="primary", key="run_agent_btn")

    if not run_agent and "agent_result" not in st.session_state:
        st.info("Enter a goal and click **Run autonomous campaign**.")
        return

    if run_agent:
        defaults = ResearchGoal(
            text=goal_text.strip(),
            t_sim=float(t_sim),
            dt=0.5,
            t_start=max(1.0, float(t_sim) * 0.15),
            t_end=max(2.0, float(t_sim) * 0.75),
            dose=float(dose),
            ensemble_members=int(n_ens),
            tox_threshold=float(tox_thr),
            drug_candidates=("MEK", "EGFR", "RAF"),
        )
        with st.spinner("Autonomous agent running experiment loop…"):
            planner = BiologicalAgentPlanner()
            plan = planner.plan(goal_text.strip(), defaults=defaults)
            result = planner.run(goal_text.strip(), defaults=defaults, plan=plan)
        st.session_state["agent_result"] = result
        st.session_state["agent_plan"] = plan

    result = st.session_state.get("agent_result")
    plan = st.session_state.get("agent_plan")
    if result is None or plan is None:
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Objective met", "YES" if result.objective_met else "NO")
    m2.metric("LAS", f"{result.literature.las:.3f}" if result.literature else "n/a")
    m3.metric("HSI", f"{result.hsi.hsi:.3f}" if result.hsi else "n/a")
    m4.metric("Tox events", str(len(result.tox_events)))

    st.markdown(f"**Hypothesis:** {plan.hypothesis}")
    st.caption(
        f"Parse confidence {plan.parse.confidence:.2f} · "
        f"rules: {', '.join(plan.parse.matched_rules)}"
    )

    st.write("### Workflow steps")
    _dataframe(
        st,
        [
            {
                "step": s.kind.value,
                "status": s.status,
                "summary": s.result_summary,
            }
            for s in plan.steps
        ],
    )

    if result.best_agents:
        st.write("### Selected regimen")
        for a in result.best_agents:
            st.write(
                f"- `{a.name}` · C₀={a.plateau_concentration or a.pk.dose:g} · "
                f"window=[{a.t_start:g}, {a.t_end}] · {a.mechanism.value}"
            )
    if result.synergy is not None:
        syn = result.synergy
        st.write(
            f"**Synergy:** effect_ab={syn.effect_ab:.3f}, "
            f"Bliss excess={syn.bliss_score:.3f} → *{syn.interpretation}*"
        )
    if result.literature is not None:
        st.write("### Literature alignment")
        st.write(result.literature.summary)
        _dataframe(
            st,
            [
                {
                    "symbol": t.symbol,
                    "LASᵢ": round(t.las_component, 3),
                    "pathway": t.pathway_hit,
                    "drug_target": t.drug_target_hit,
                    "ppi": t.ppi_hit,
                }
                for t in result.literature.target_alignments[:8]
            ],
        )

    st.write("### Research brief")
    st.markdown(result.report_markdown)

    with st.expander("Machine-readable agent payload"):
        st.json(result.as_dict())


def _render_manual_tabs(st: Any, result: Any) -> None:
    tab_traj, tab_net, tab_ai, tab_tox = st.tabs(
        ["Trajectories & PK", "Network map", "AI explanation", "Toxicology"]
    )

    with tab_traj:
        left, right = st.columns(2)
        with left:
            st.subheader("Concentration profiles")
            _render_figure(st, result.trajectory_figure, key="traj")
        with right:
            st.subheader("Pharmacokinetics")
            _render_figure(st, result.pk_figure, key="pk")
            st.subheader("Homeostatic Shift Index")
            _render_figure(st, result.hsi_figure, key="hsi")
            if result.hsi.node_shifts:
                st.write("Top node shifts")
                rows = [
                    {
                        "name": s.name,
                        "Δrel": round(s.relative_delta, 3),
                        "contrib": round(s.contribution, 3),
                    }
                    for s in result.hsi.node_shifts[:8]
                ]
                _dataframe(st, rows)

    with tab_net:
        st.subheader("Pathway topology")
        st.caption("Gold stroke = hub · green stroke = feedback · badges = GNN rank")
        st.markdown(result.network_svg, unsafe_allow_html=True)
        with st.expander("Network view model (JSON)"):
            st.json(
                {
                    "n_nodes": len(result.network_view.nodes),
                    "n_edges": len(result.network_view.edges),
                    "loops": result.network_view.feedback_loops,
                    "metadata": result.network_view.metadata,
                }
            )

    with tab_ai:
        st.subheader("AIScientistReasoner")
        recs = result.ai_panel.get("recommendations") or []
        if not recs:
            st.write("No recommendations (unsupervised ranks still shown on the network).")
        for rec in recs:
            name = rec.get("name") or rec.get("entity_id") or "target"
            score = rec.get("score")
            st.markdown(f"**{name}** — score `{score}`")
            summary = rec.get("summary")
            if summary:
                st.write(summary)
            attrs = rec.get("feature_attributions") or []
            if attrs:
                st.caption("Feature importance")
                _dataframe(st, attrs)
            edges = rec.get("edge_attributions") or []
            if edges:
                st.caption("Edge occlusion / attribution")
                _dataframe(st, edges[:12])
        ranks = result.ai_panel.get("ranks") or {}
        if ranks:
            ranked = sorted(ranks.items(), key=lambda kv: kv[1], reverse=True)[:8]
            st.write("Target prioritization ranks")
            _dataframe(
                st,
                [
                    {
                        "entity_id": eid,
                        "name": result.entity_names.get(eid, eid),
                        "score": round(sc, 4),
                    }
                    for eid, sc in ranked
                ],
            )

    with tab_tox:
        st.subheader("Live toxicology monitor")
        if not result.tox_events:
            st.success("No safety-threshold breaches during the treated run.")
        else:
            st.error(f"{len(result.tox_events)} adverse event(s) flagged")
            _dataframe(st, result.tox_events)


def _render_encyclopedia_card(st: Any, card: Dict[str, Any]) -> None:
    """Rich UniProt-style protein/gene card (no raw JSON dumps)."""
    if not card:
        st.info("Select a biological entity to inspect.")
        return
    ident = card.get("identity") or {}
    bio = card.get("biology") or {}
    clinical = card.get("clinical") or {}
    structure = card.get("structure") or {}
    drugs = card.get("drugs") or []

    title = ident.get("gene_symbol") or card.get("title") or "Entity"
    full_name = ident.get("full_name") or card.get("subtitle") or ""
    uniprot = ident.get("uniprot_id") or ""
    loc = bio.get("cellular_localization") or ""

    st.markdown(f"### {title}")
    if full_name:
        st.caption(full_name)

    badges = []
    if uniprot:
        badges.append(f"`UniProt {uniprot}`")
    if loc:
        badges.append(f"`{loc}`")
    if ident.get("kegg_id"):
        badges.append(f"`KEGG {ident.get('kegg_id')}`")
    if clinical.get("oncogene"):
        badges.append("`oncogene`")
    if clinical.get("tumor_suppressor"):
        badges.append("`tumor suppressor`")
    if badges:
        st.markdown(" · ".join(badges))

    st.markdown("#### Domains")
    domains = bio.get("domains") or []
    if domains:
        chips = []
        for d in domains:
            name = d.get("name") or "domain"
            start, end = d.get("start"), d.get("end")
            if start is not None and end is not None:
                chips.append(f"`[{name} {start}-{end}]`")
            else:
                chips.append(f"`[{name}]`")
        st.markdown(" ".join(chips))
    else:
        st.caption("No domain annotations.")

    ptms = bio.get("ptm_sites") or []
    if ptms:
        st.markdown("#### PTM sites")
        st.markdown(
            " ".join(
                f"`{p.get('residue') or p.get('name')}`"
                for p in ptms
            )
        )

    muts = clinical.get("somatic_mutations") or []
    diseases = clinical.get("diseases") or []
    if muts or diseases:
        st.markdown("#### Clinical variants")
        for m in muts:
            st.error(f"Somatic variant: {m}")
        if diseases:
            st.warning("Diseases: " + ", ".join(str(d) for d in diseases))

    st.markdown("#### 3D structure")
    pdb = structure.get("pdb_id")
    plddt = structure.get("alphafold_plddt_score")
    if plddt is not None:
        try:
            st.caption(f"AlphaFold pLDDT {float(plddt):.1f}")
        except (TypeError, ValueError):
            st.caption(f"AlphaFold pLDDT {plddt}")
    if pdb:
        st.link_button(
            f"View 3D Structure ({pdb})",
            f"https://www.rcsb.org/structure/{pdb}",
            use_container_width=True,
        )
    elif uniprot:
        st.link_button(
            "View AlphaFold Structure",
            f"https://alphafold.ebi.ac.uk/entry/{uniprot}",
            use_container_width=True,
        )
    else:
        st.caption("No structure metadata.")

    if drugs:
        st.markdown("#### Targetable inhibitors")
        _dataframe(
            st,
            [
                {
                    "drug": d.get("name"),
                    "mechanism": d.get("mechanism"),
                    "IC50_nM": d.get("ic50_nM"),
                    "status": d.get("approval_status"),
                }
                for d in drugs
            ],
        )


def _render_causal_banner(st: Any, causal: Dict[str, Any]) -> None:
    """Causal Narrative Panel — plain-English Why? explanations."""
    if not causal:
        st.info("Select a biological entity / run a perturbation to populate causal narratives.")
        return
    st.markdown("### Causal narrative")
    st.info(causal.get("overview_narrative") or "No narrative available.")
    cascade = causal.get("cascade") or []
    if cascade:
        st.markdown("**Cascade:** " + " → ".join(f"`{n}`" for n in cascade))
    for section, key in (("Why activated", "activated"), ("Why suppressed", "inactivated")):
        items = causal.get(key) or []
        if not items:
            continue
        st.markdown(f"#### {section}")
        for ex in items:
            pct = float(ex.get("percent_change") or 0.0)
            if pct != pct:  # NaN guard
                pct = 0.0
            st.markdown(
                f"**{ex.get('node_name') or 'node'}** ({pct:+.0f}%) — {ex.get('narrative') or ''}"
            )
            chain = ex.get("chain") or []
            if chain:
                with st.expander(f"Causal chain · {ex.get('node_name')}", expanded=False):
                    for step in chain:
                        st.write(
                            f"- `{step.get('source_name')}` → `{step.get('target_name')}` "
                            f"({step.get('interaction')}): {step.get('evidence')}"
                        )


def _render_biology_lab_tab(st: Any) -> None:
    """Virtual Cellular Laboratory: encyclopedia + crosstalk + causal reasoner."""
    from voidsignal.components import ClinicalAnnotation, DrugAssociation, Protein
    from voidsignal.simulation import SimulatorBackend, TrajectoryResult
    from voidsignal.topology import InteractionType, SignalingNetwork
    from voidsignal.ui.studio_cards import (
        build_causal_payload,
        crosstalk_viewport_payload,
        demo_rich_mapk_entities,
        encyclopedia_card_for,
    )

    st.subheader("Virtual Cellular Laboratory")
    st.caption(
        "Rich encyclopedia cards · multi-pathway crosstalk hubs · CausalBioReasoner narratives"
    )

    mode = st.selectbox(
        "Pathway viewport",
        [
            "MAPK (hsa04010)",
            "PI3K-AKT (hsa04151)",
            "Multi-Pathway Crosstalk (MAPK + PI3K-AKT + JAK-STAT)",
        ],
        index=2,
        key="biolab_pathway_mode",
    )

    entities = {e.name: e for e in demo_rich_mapk_entities()}
    # Expand demo set for JAK-STAT nodes used in crosstalk mode
    if "JAK" not in entities:
        entities["JAK"] = Protein(
            name="JAK",
            gene_symbol="JAK2",
            pathway_membership=["JAK-STAT"],
            cellular_localization="Cytosol",
        )
    if "STAT" not in entities:
        entities["STAT"] = Protein(
            name="STAT",
            gene_symbol="STAT3",
            pathway_membership=["JAK-STAT"],
            cellular_localization="Nucleus",
        )
    if "RAF" not in entities:
        entities["RAF"] = Protein(name="RAF", gene_symbol="BRAF", pathway_membership=["MAPK"])

    net = SignalingNetwork(name="biolab")
    ids: Dict[str, str] = {}
    for name, ent in entities.items():
        net.add_node(ent)
        ids[name] = ent.entity_id

    edges = [
        ("EGFR", "RAS", InteractionType.ACTIVATION),
        ("RAS", "RAF", InteractionType.ACTIVATION),
        ("RAF", "MEK", InteractionType.PHOSPHORYLATION),
        ("MEK", "ERK", InteractionType.PHOSPHORYLATION),
        ("EGFR", "PI3K", InteractionType.ACTIVATION),
        ("RAS", "PI3K", InteractionType.ACTIVATION),
        ("PI3K", "AKT", InteractionType.ACTIVATION),
        ("JAK", "STAT", InteractionType.PHOSPHORYLATION),
        ("ERK", "TP53", InteractionType.ACTIVATION),
        ("STAT", "TP53", InteractionType.ACTIVATION),
    ]
    for src, tgt, itype in edges:
        if src in ids and tgt in ids:
            net.connect(ids[src], ids[tgt], itype, rate_constant=1.0)

    net.auto_annotate_canonical_pathways()
    viewport = crosstalk_viewport_payload(net)

    if "Crosstalk" in mode:
        st.success(
            "Crosstalk hubs (amber): "
            + ", ".join(
                f"{s['name']} [{'/'.join(s['pathways'])}]"
                for s in viewport["crosstalk_switches"][:6]
            )
        )
    else:
        st.info(f"Single-pathway mode: {mode}")

    pick = st.selectbox(
        "Inspect node (encyclopedia)",
        sorted(entities.keys()),
        index=sorted(entities.keys()).index("EGFR") if "EGFR" in entities else 0,
        key="biolab_node_pick",
    )
    card = encyclopedia_card_for(entities[pick])
    _render_encyclopedia_card(st, card)

    # Synthetic control vs perturbed trajectories for causal panel
    node_ids = list(ids.values())
    control_final = {nid: 0.35 for nid in node_ids}
    pert_final = {nid: 0.35 for nid in node_ids}
    if "ERK" in ids:
        control_final[ids["ERK"]] = 0.4
        pert_final[ids["ERK"]] = 0.85
    if "AKT" in ids:
        control_final[ids["AKT"]] = 0.5
        pert_final[ids["AKT"]] = 0.05
    if "RAS" in ids:
        control_final[ids["RAS"]] = 0.3
        pert_final[ids["RAS"]] = 0.9
        ras = entities["RAS"]
        ras.clinical = ClinicalAnnotation(somatic_mutations=["KRAS p.G12D"], oncogene=True)
    if "PI3K" in ids:
        control_final[ids["PI3K"]] = 0.4
        pert_final[ids["PI3K"]] = 0.05
        entities["PI3K"].drugs = [
            DrugAssociation(name="Wortmannin", mechanism="inhibitor", ic50_nM=5.0)
        ]
    if "MEK" in ids:
        control_final[ids["MEK"]] = 0.3
        pert_final[ids["MEK"]] = 0.7

    def _traj(finals: Dict[str, float]) -> TrajectoryResult:
        return TrajectoryResult(
            times=[0.0, 1.0],
            concentrations=[{k: 0.1 for k in finals}, dict(finals)],
            boolean_states=[{k: 0 for k in finals}, {k: 1 for k in finals}],
            backend=SimulatorBackend.ODE,
        )

    causal = build_causal_payload(
        net,
        _traj(control_final),
        _traj(pert_final),
        cascade=["EGF", "EGFR", "RAS", "RAF", "MEK", "ERK"],
    )
    _render_causal_banner(st, causal)

    with st.expander("Developer telemetry (optional)", expanded=False):
        st.caption("Topology summary for debugging — not part of the lab card UI.")
        st.write(
            f"Hubs: {len(viewport.get('hubs') or [])} · "
            f"Bottlenecks: {len(viewport.get('bottlenecks') or [])} · "
            f"Switches: {len(viewport.get('crosstalk_switches') or [])}"
        )


def _render_experiment_studio(st: Any) -> None:
    """Experiment Studio: pathway merge presets + VCF/RNA-style uploads."""
    from voidsignal.integrations import (
        BiologicalEnrichmentEngine,
        MultiPathwayMerger,
        list_pathway_catalog,
    )

    st.subheader("Experiment Studio")
    st.caption(
        "Structured biological experiments inside a virtual cell — "
        "knockouts, mutations, drug combos, hypoxia, Healthy vs Cancer."
    )

    presets = {
        "CRISPR Knockout EGFR": ["hsa04010"],
        "Point Mutation KRAS G12D": ["hsa04010"],
        "Drug Combo MEK+PI3K": ["MAPK", "PI3K-Akt"],
        "Hypoxia / mTOR stress": ["hsa04151"],
        "Healthy vs Cancer (crosstalk)": ["MAPK", "PI3K-Akt", "hsa04630"],
    }
    pick = st.selectbox("Experiment preset", list(presets.keys()), index=2)
    catalog = list_pathway_catalog(domain="Pathways")
    st.multiselect(
        "Pathway catalog (multi-select for crosstalk)",
        options=[f"{e.pathway_id} · {e.name}" for e in catalog],
        default=[f"{e.pathway_id} · {e.name}" for e in catalog[:2]],
        key="exp_pathway_multi",
    )
    uploaded = st.file_uploader("Upload patient VCF / expression table", type=["vcf", "vcf.gz", "txt", "tsv"])
    if uploaded is not None:
        st.success(f"Loaded experiment input: {uploaded.name}")

    if st.button("Launch experiment", type="primary"):
        merger = MultiPathwayMerger()
        result = merger.merge(presets[pick])
        engine = BiologicalEnrichmentEngine()
        reports = engine.enrich_network(result.network)
        st.metric("Merged nodes", result.n_nodes)
        st.metric("Merged edges", result.n_edges)
        st.write("Crosstalk hubs:", ", ".join(result.hub_symbols) or "(none)")
        st.write("Enriched genes:", ", ".join(sorted(reports.keys())[:12]))
        with st.expander("Merge metadata"):
            st.json(result.as_dict())


def _render_protein_explorer(st: Any) -> None:
    from voidsignal.integrations import BiologicalEnrichmentEngine, LabUniProtClient
    from voidsignal.ui.studio_cards import demo_rich_mapk_entities, encyclopedia_card_for

    st.subheader("Protein Explorer")
    st.caption("UniProt search · styled encyclopedia cards — never raw JSON.")
    q = st.text_input("Search gene / protein", value="EGFR")
    client = LabUniProtClient()
    hits = client.search(q, limit=8) if q.strip() else []
    labels = [
        f"{h.get('gene_symbol')} · {h.get('accession') or 'offline'}"
        for h in hits
    ] or ["EGFR · P00533"]
    pick_label = st.selectbox("Results", labels)
    pick = pick_label.split(" · ")[0].strip() if pick_label else "EGFR"

    engine = BiologicalEnrichmentEngine()
    report = engine.enrich_symbol(pick)
    demos = {e.gene_symbol or e.name: e for e in demo_rich_mapk_entities()}
    if pick in demos:
        card = encyclopedia_card_for(demos[pick])
    else:
        card = report.encyclopedia_card or {}
        if hits:
            # Prefer first search hit fields when enrichment card is sparse
            hit = next((h for h in hits if str(h.get("gene_symbol")) == pick), hits[0])
            if not card.get("identity", {}).get("uniprot_id") and hit.get("accession"):
                card = report.encyclopedia_card or {
                    "title": hit.get("gene_symbol"),
                    "subtitle": hit.get("full_name"),
                    "identity": {
                        "gene_symbol": hit.get("gene_symbol"),
                        "full_name": hit.get("full_name"),
                        "uniprot_id": hit.get("accession"),
                    },
                    "biology": {
                        "cellular_localization": hit.get("localization"),
                        "domains": hit.get("domains") or [],
                        "ptm_sites": hit.get("ptm_sites") or [],
                    },
                    "structure": {
                        "pdb_id": (hit.get("pdb_ids") or [None])[0],
                    },
                    "clinical": {
                        "diseases": hit.get("diseases") or [],
                        "somatic_mutations": hit.get("mutations") or [],
                    },
                    "drugs": [],
                }

    _render_encyclopedia_card(st, card)

    if report.essentiality or report.chromatin or report.structure:
        st.markdown("#### Enrichment priors")
        cols = st.columns(3)
        if report.essentiality:
            ess = report.essentiality.as_dict()
            cols[0].metric(
                "DepMap gene effect",
                f"{ess['gene_effect']:.2f}",
                delta="essential" if ess.get("is_essential") else "non-essential",
            )
        if report.chromatin:
            chrom = report.chromatin.as_dict()
            cols[1].markdown(
                f"**ENCODE** `{chrom.get('chromatin_state')}` · {chrom.get('cell_type')}"
            )
        if report.structure and report.structure.mean_plddt is not None:
            cols[2].metric("AlphaFold pLDDT", f"{report.structure.mean_plddt:.1f}")


def _render_docking_stage(st: Any) -> None:
    st.subheader("3D Structural Docking")
    st.caption("Pocket geometry · ligand pose · binding free energy HUD")
    try:
        from voidsignal.docking import delta_g_to_ki, make_demo_receptor_ligand
        from voidsignal.integrations import StructureClient

        receptor, ligand = make_demo_receptor_ligand()
        dg = -9.4
        ki = delta_g_to_ki(dg)
        struct = StructureClient().lookup_pdb("1M17")
        st.info(
            f"Target Protein (PDB: {struct.pdb_id or '1M17'}) · "
            f"Ligand (Erlotinib) · "
            f"ΔG = {dg:.1f} kcal/mol · "
            f"Ki = {ki:.2e} M"
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Receptor atoms", str(len(receptor.atoms)))
        c2.metric("Binding Free Energy (kcal/mol)", f"{dg:.2f}")
        c3.metric("Inhibition Constant Ki (M)", f"{ki:.2e}")
        st.write(f"Ligand atoms: {len(ligand.atoms)} · receptor: {receptor.name}")
    except Exception as exc:
        st.info(f"Docking module summary unavailable ({exc}). Use the React studio WebGL viewport.")


def run_dashboard() -> None:
    st = _require_streamlit()
    st.set_page_config(
        page_title="VOIDSIGNAL Virtual Cellular Laboratory",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("VOIDSIGNAL Virtual Cellular Laboratory")
    st.caption(
        "V1 Core Virtual Cellular Laboratory · UniProt / KEGG / STRING / AlphaFold · "
        "4-stage sidebar workspace"
    )

    with st.sidebar:
        st.header("Lab stages")
        stage = st.radio(
            "Workspace",
            [
                "Experiment Studio",
                "Visual Pathway Canvas",
                "3D Structural Docking",
                "Protein Explorer",
                "AI Scientist (drawer)",
                "Manual ODE (Phase 9)",
            ],
            index=0,
            key="lab_stage",
        )
        st.caption("v0.21 · Core Virtual Cellular Laboratory")

    if stage == "Experiment Studio":
        _render_experiment_studio(st)
        return

    if stage == "Visual Pathway Canvas":
        _render_biology_lab_tab(st)
        return

    if stage == "3D Structural Docking":
        _render_docking_stage(st)
        return

    if stage == "Protein Explorer":
        _render_protein_explorer(st)
        return

    if stage.startswith("AI Scientist"):
        _render_agent_tab(st)
        return

    with st.sidebar:
        st.header("Simulation controls")
        dose = st.slider(
            "Initial Drug Concentration (uM)",
            min_value=0.0,
            max_value=10.0,
            value=2.0,
            step=0.1,
        )
        t_start = st.slider("Dosing Window Start (s)", 0.0, 40.0, 5.0, 0.5)
        t_end = st.slider("Dosing Window End (s)", 5.0, 60.0, 35.0, 0.5)
        if t_end <= t_start:
            st.warning("Dosing window end should be greater than start")
            t_end = t_start + 1.0
        t_sim = st.slider("Simulation Duration (s)", 20.0, 120.0, 50.0, 5.0)
        kel = st.slider("PK elimination rate (kel)", 0.01, 1.0, 0.12, 0.01)
        ki = st.slider("Inhibition Constant (Ki)", 0.05, 5.0, 0.5, 0.05)
        drug_target = st.selectbox("Drug target", ["MEK", "RAF", "EGFR", "RAS", "ERK"], index=0)

        st.subheader("Disease phenotype")
        cancer = st.toggle("Cancer signaling", value=True)
        storm = st.toggle("Cytokine storm (inflammation)", value=False)

        st.subheader("Patient VCF")
        uploaded = st.file_uploader("Upload patient VCF", type=["vcf", "vcf.gz", "txt"])
        use_demo_vcf = st.checkbox("Use demo VCF (RAS locus)", value=False)

        run_btn = st.button("Run simulation", type="primary", use_container_width=True)
        auto = st.checkbox("Auto-run on control change", value=False)

    vcf_path: Optional[str] = None
    if uploaded is not None:
        tmp = Path(tempfile.gettempdir()) / f"voidsignal_upload_{uploaded.name}"
        tmp.write_bytes(uploaded.getvalue())
        vcf_path = str(tmp)
    elif use_demo_vcf:
        vcf_path = str(write_demo_vcf())

    controls = DashboardControls(
        dose_c0=float(dose),
        t_start=float(t_start),
        t_end=float(t_end),
        t_sim=float(t_sim),
        cancer=bool(cancer),
        cytokine_storm=bool(storm),
        drug_target=str(drug_target),
        ki=float(ki),
        kel=float(kel),
        vcf_path=vcf_path,
        expression={"RAS": 1.5} if vcf_path else {},
    )

    should_run = run_btn or auto
    if not should_run:
        st.info("Adjust controls and click **Run simulation**, or enable auto-run.")
        return

    with st.spinner("Running DualEngineSimulator ensemble (baseline / disease / treated)…"):
        session = DashboardSession()
        result = session.run(controls)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("HSI", f"{result.hsi.hsi:.3f}", delta="collapse" if result.hsi.collapse_flag else "stable")
    c2.metric("Tox flags", str(len(result.tox_events)))
    c3.metric("Network nodes", str(len(result.network_view.nodes)))
    # Prefer causal-friendly readout label over raw float-only caption
    erk_id = result.ids.get("ERK", "")
    erk_val = result.treated.final_concentrations().get(erk_id, float("nan"))
    c4.metric("Treated ERK", f"{erk_val:.3f}")

    # Causal banner above legacy tabs when both trajectories exist
    try:
        from voidsignal.ui.studio_cards import build_causal_payload
        from voidsignal.visualization.session import build_demo_mapk

        net, ids_map = build_demo_mapk()
        # Align entity IDs with the run when possible (silent mismatch → skip, no crash)
        cascade_names = ["EGFR", "RAS", "RAF", "MEK", "ERK"]
        cascade = [n for n in cascade_names if n in ids_map or n in result.ids]
        if result.baseline is not None and result.treated is not None:
            causal = build_causal_payload(
                net,
                result.baseline,
                result.treated,
                cascade=cascade or cascade_names,
            )
            _render_causal_banner(st, causal)
        else:
            st.info("Select a biological entity / complete a run to populate causal narratives.")
    except Exception as exc:
        st.warning(f"Causal narrative unavailable: {exc}")

    _render_manual_tabs(st, result)

    with st.expander("Raw dashboard payload"):
        st.json(result.as_dict())


if __name__ == "__main__":
    run_dashboard()
