"""Plain-language protein cards for non-biologist Studio viewers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from cistron.api.biomed_llm import generate_biomed_narrative
from cistron.api.disease_impact import build_disease_impact


# Short lay explanations for frequent cancer / signaling genes (boosters only).
_LAY: Dict[str, Dict[str, str]] = {
    "HMGA1": {
        "plain": (
            "HMGA1 is a tiny DNA-packing protein that helps open chromatin so many "
            "growth and stress genes can turn on."
        ),
        "why": (
            "Tumors often overproduce HMGA1, which can make cells grow faster, "
            "invade tissue, and resist some treatments. Researchers study it as a "
            "possible cancer vulnerability."
        ),
        "analogy": "Think of it as a volume knob on a mixing board for growth genes.",
    },
    "HIF1A": {
        "plain": (
            "HIF1A is the cell’s low-oxygen alarm. When oxygen drops, it switches on "
            "genes for new blood vessels and sugar uptake."
        ),
        "why": (
            "Solid tumors are often oxygen-starved. HIF1A helps them survive that "
            "stress — so it is central in hypoxia and many cancer models."
        ),
        "analogy": "Like a fire alarm that also calls for more fuel and exits.",
    },
    "EGFR": {
        "plain": (
            "EGFR is a antenna on the cell surface that listens for growth signals "
            "and tells the inside of the cell to divide."
        ),
        "why": (
            "Mutated or overactive EGFR drives several cancers (lung, brain, others). "
            "Many drugs try to block this antenna."
        ),
        "analogy": "A doorbell that, when pressed too often, keeps ordering more cells.",
    },
    "KRAS": {
        "plain": (
            "KRAS is a molecular switch that passes ‘grow’ messages from the cell "
            "surface into the MAPK pathway."
        ),
        "why": (
            "KRAS mutations lock the switch ON and are among the most common drivers "
            "in pancreatic, lung, and colorectal cancer."
        ),
        "analogy": "A light switch glued in the ON position.",
    },
    "TP53": {
        "plain": (
            "TP53 (p53) is a guardian of the genome — it can pause the cell cycle or "
            "trigger cell death when DNA is damaged."
        ),
        "why": (
            "When TP53 is broken, damaged cells keep dividing. Loss of p53 is extremely "
            "common across human cancers."
        ),
        "analogy": "A quality-control inspector that can shut the factory line.",
    },
    "VEGFA": {
        "plain": (
            "VEGFA is a signal protein that tells blood vessels to grow toward a tissue."
        ),
        "why": (
            "Tumors release VEGFA to recruit a blood supply (angiogenesis). Blocking it "
            "is a classic anti-cancer strategy."
        ),
        "analogy": "A ‘build roads here’ flyer sent to nearby blood vessels.",
    },
    "EGLN1": {
        "plain": (
            "EGLN1 (PHD2) is an oxygen sensor enzyme that marks HIF1A for destruction "
            "when oxygen is plentiful."
        ),
        "why": (
            "When oxygen falls, EGLN1 slows down, HIF1A survives, and hypoxia programs "
            "turn on — key for ischemia and tumor hypoxia."
        ),
        "analogy": "A security guard that only works when the lights (oxygen) are on.",
    },
    "GLUT1": {
        "plain": (
            "GLUT1 is a sugar door in the cell membrane — it lets glucose in for fuel."
        ),
        "why": (
            "Stressed or hypoxic cells often open more GLUT1 doors so they can burn "
            "sugar even with little oxygen."
        ),
        "analogy": "Extra loading docks when the factory needs more raw material.",
    },
    "PSIP1": {
        "plain": (
            "PSIP1 (LEDGF) helps tether other proteins to chromatin and can influence "
            "which genes stay active."
        ),
        "why": (
            "It shows up in transcriptional and DNA-related networks; in disease graphs "
            "it often acts as a connector rather than the main driver."
        ),
        "analogy": "A clip that holds paperwork onto a clipboard so other workers can find it.",
    },
    "MYC": {
        "plain": "MYC is a master growth transcription factor that pushes cells to proliferate.",
        "why": "Many cancers amp up MYC to keep dividing. It is powerful but hard to drug directly.",
        "analogy": "A CEO memo saying ‘hire more workers, expand production.’",
    },
    "AKT1": {
        "plain": "AKT1 is a survival kinase — it tells the cell to grow and avoid dying.",
        "why": "Overactive AKT signaling is common in cancer and metabolic disease pathways.",
        "analogy": "A ‘keep going’ text message to the cell’s machinery.",
    },
    "MTOR": {
        "plain": "mTOR is a nutrient-sensing hub that decides whether the cell should build or conserve.",
        "why": "Drugs targeting mTOR are used in cancer and transplant medicine.",
        "analogy": "The factory’s power-and-budget manager.",
    },
    "O2": {
        "plain": "O₂ here is not a gene — it is the oxygen level we clamp in the virtual experiment.",
        "why": "Lowering O₂ models hypoxia, which rewires signaling through sensors like EGLN1/HIF1A.",
        "analogy": "The air supply dial on a lab incubator.",
    },
}


def _clean_sentences(text: str, *, max_chars: int = 420) -> str:
    t = " ".join((text or "").split())
    if len(t) <= max_chars:
        return t
    cut = t[: max_chars - 1].rsplit(" ", 1)[0]
    return (cut or t[: max_chars - 1]) + "…"


def _normalize_diseases(diseases_raw: Any) -> List[str]:
    diseases: List[str] = []
    for d in diseases_raw or []:
        if isinstance(d, str) and d.strip():
            diseases.append(d.strip())
        elif isinstance(d, dict):
            name = d.get("disease") or d.get("name") or d.get("value")
            if name:
                diseases.append(str(name))
    return diseases[:12]


def build_protein_card(
    symbol: str,
    meta: Dict[str, Any],
    *,
    condition_query: str = "",
    upstream: Optional[Sequence[str]] = None,
    downstream: Optional[Sequence[str]] = None,
    delta_y: Optional[float] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Assemble identifiers + fact-grounded explanations for the node inspector."""
    sym = symbol.strip().upper() or symbol
    up = [u for u in (upstream or []) if u]
    down = [d for d in (downstream or []) if d]
    lay = _LAY.get(sym, {})

    full_name = str(meta.get("full_name") or "") or None
    localization = str(meta.get("localization") or "") or None
    function = str(meta.get("function") or "") or None
    summary = str(meta.get("summary") or "") or None
    diseases = _normalize_diseases(meta.get("diseases"))
    sources_used = [str(s) for s in (meta.get("sources_used") or []) if s]
    entrezgene = meta.get("entrezgene")
    type_of_gene = meta.get("type_of_gene")

    accession = meta.get("uniprot_id") or meta.get("accession")
    accession_s = str(accession) if accession else None

    prose_src = summary or function

    # --- Template narrative (always available) ---
    if lay.get("plain"):
        plain = lay["plain"]
        narrative_mode = "template_curated"
    else:
        bits = [f"{sym} is a human"]
        if type_of_gene and str(type_of_gene).lower() not in {"", "unknown"}:
            bits.append(f" {type_of_gene.replace('_', ' ')}")
        else:
            bits.append(" gene/protein")
        if full_name:
            bits.append(f" ({full_name})")
        bits.append(".")
        if localization and localization.lower() != "unknown":
            bits.append(f" It is typically found in the {localization.lower()}.")
        if prose_src:
            bits.append(f" {_clean_sentences(prose_src, max_chars=320)}")
        else:
            bits.append(
                " Public databases did not return a long summary yet — "
                "identifiers and network neighbors below still place it in your experiment."
            )
        plain = "".join(bits)
        narrative_mode = "template"

    if lay.get("why"):
        why = lay["why"]
    else:
        why_parts: List[str] = []
        if diseases:
            why_parts.append("Associated conditions include " + ", ".join(diseases[:5]) + ".")
        if condition_query.strip():
            why_parts.append(
                f"In your current experiment («{condition_query.strip()}»), "
                f"{sym} appears in the mapped disease network, so changing it can reshape the simulated outcome."
            )
        elif prose_src:
            why_parts.append(
                "Systems biologists track this molecule because shifts in its activity "
                "can ripple through pathways that control growth, stress responses, or metabolism."
            )
        else:
            why_parts.append(
                f"In this network view, {sym} is a node whose activity (y) we can simulate, "
                "knock out, or clamp — useful for asking ‘what if this protein goes up or down?’"
            )
        why = " ".join(why_parts)

    net_parts: List[str] = []
    if up:
        net_parts.append(
            f"Signals arrive from {', '.join(up[:4])}"
            + ("…" if len(up) > 4 else "")
            + "."
        )
    if down:
        net_parts.append(
            f"{sym} influences {', '.join(down[:4])}"
            + ("…" if len(down) > 4 else "")
            + " downstream."
        )
    if not net_parts:
        net_parts.append(
            f"No local edges were passed for {sym} yet — open it from a built graph to see neighbors."
        )
    if delta_y is not None and abs(float(delta_y)) >= 0.05:
        direction = "rising" if float(delta_y) > 0 else "falling"
        net_parts.append(
            f"In the latest run its activity is {direction} (Δy={float(delta_y):+.2f}), "
            "so it is actively changing during the simulation."
        )
    in_network = " ".join(net_parts)

    # Optional BioGPT / hosted LLM polish (never invents if call fails)
    if use_llm:
        llm = generate_biomed_narrative(
            meta,
            condition_query=condition_query,
            upstream=up,
            downstream=down,
        )
        if llm and llm.get("plain_english"):
            plain = str(llm["plain_english"])
            why = str(llm.get("why_it_matters") or why)
            in_network = str(llm.get("in_this_network") or in_network)
            narrative_mode = str(llm.get("narrative_mode") or "biogpt")
            if narrative_mode in {"biogpt", "hf_llm", "cached", "custom_llm"}:
                if narrative_mode not in sources_used:
                    sources_used.append(narrative_mode)

    entrez_url = (
        f"https://www.ncbi.nlm.nih.gov/gene/{entrezgene}" if entrezgene else None
    )

    disease_impact = build_disease_impact(
        sym,
        meta,
        condition_query=condition_query,
        upstream=up,
        downstream=down,
        delta_y=delta_y,
        use_llm=use_llm,
    )
    if disease_impact.get("mode") in {"hf_llm", "cached", "custom_llm"}:
        tag = f"disease_impact_{disease_impact['mode']}"
        if tag not in sources_used:
            sources_used.append(tag)

    return {
        "gene_symbol": sym,
        "uniprot_id": accession_s,
        "full_name": full_name,
        "localization": localization or "Unknown",
        "function": function or summary,
        "diseases": diseases[:8],
        "plain_english": plain,
        "why_it_matters": why,
        "in_this_network": in_network,
        "analogy": lay.get("analogy"),
        "uniprot_url": (
            f"https://www.uniprot.org/uniprotkb/{accession_s}/entry" if accession_s else None
        ),
        "alphafold_url": meta.get("alphafold_url")
        or (f"https://alphafold.ebi.ac.uk/entry/{accession_s}" if accession_s else None),
        "entrez_url": entrez_url,
        "sources_used": sources_used,
        "narrative_mode": narrative_mode,
        "summary": summary,
        "type_of_gene": type_of_gene,
        "entrezgene": str(entrezgene) if entrezgene else None,
        "disease_impact": disease_impact,
    }
