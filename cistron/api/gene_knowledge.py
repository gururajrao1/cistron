"""Retrieve-grounded gene/protein knowledge (MyGene + UniProt + offline)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
import logging

from cistron.integrations.cache_store import IntegrationCache
from cistron.integrations.http_sync import http_get_json
from cistron.integrations.offline_data import OFFLINE_UNIPROT
from cistron.integrations.uniprot_client import LabUniProtClient

logger = logging.getLogger(__name__)

_MYGENE_QUERY = "https://mygene.info/v3/query"
_FIELDS = "symbol,name,summary,type_of_gene,taxid,entrezgene,uniprot,alias,go"


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                for key in ("id", "term", "name", "value"):
                    if item.get(key):
                        out.append(str(item[key]))
                        break
        return out
    if isinstance(value, dict):
        # UniProt Swiss-Prot / TrEMBL shape from MyGene
        for key in ("Swiss-Prot", "TrEMBL", "uniprot"):
            if key in value:
                return _as_list(value[key])
        return []
    return [str(value)]


def _first_uniprot(value: Any) -> Optional[str]:
    ids = _as_list(value)
    return ids[0] if ids else None


def _fetch_mygene(symbol: str, cache: IntegrationCache) -> Optional[Dict[str, Any]]:
    sym = symbol.strip()
    cache_key = sym.upper()
    hit = cache.get_json("mygene", cache_key)
    if isinstance(hit, dict):
        return hit

    params = urlencode(
        {
            "q": f"symbol:{sym} AND taxid:9606",
            "species": "human",
            "fields": _FIELDS,
            "size": "1",
        }
    )
    url = f"{_MYGENE_QUERY}?{params}"
    payload = http_get_json(url, timeout=12.0)
    if not isinstance(payload, dict):
        return None
    hits = payload.get("hits") or []
    if not hits:
        # retry without fielded symbol (aliases / case)
        params2 = urlencode(
            {
                "q": sym,
                "species": "human",
                "fields": _FIELDS,
                "size": "3",
            }
        )
        payload = http_get_json(f"{_MYGENE_QUERY}?{params2}", timeout=12.0)
        if not isinstance(payload, dict):
            return None
        hits = payload.get("hits") or []
        # prefer exact symbol match
        exact = [
            h
            for h in hits
            if str(h.get("symbol", "")).upper() == sym.upper() and h.get("taxid") == 9606
        ]
        hits = exact or [h for h in hits if h.get("taxid") == 9606] or hits
    if not hits:
        return None
    row = dict(hits[0])
    cache.set_json("mygene", cache_key, row)
    return row


def resolve_gene_knowledge(symbol: str) -> Dict[str, Any]:
    """
    Merge MyGene.info + UniProt (+ offline banks) into one fact bundle.

    Always returns a dict suitable for ``build_protein_card``; never raises.
    """
    sym = symbol.strip().upper() or symbol.strip()
    sources_used: List[str] = []
    cache = IntegrationCache()

    # Environmental / non-gene clamps used in Studio graphs
    if sym in {"O2", "O₂", "OXYGEN"}:
        return {
            "gene_symbol": "O2",
            "uniprot_id": None,
            "accession": None,
            "full_name": "Molecular oxygen (environmental clamp)",
            "localization": "Environment",
            "function": "Extracellular O₂ level controlling EGLN1 / HIF activity in the model.",
            "summary": (
                "Not a gene — an oxygen level we clamp in the virtual experiment to model hypoxia."
            ),
            "diseases": [],
            "entrezgene": None,
            "type_of_gene": "other",
            "alphafold_url": None,
            "sources_used": ["model_clamp"],
        }

    full_name: Optional[str] = None
    localization: Optional[str] = None
    function: Optional[str] = None
    summary: Optional[str] = None
    accession: Optional[str] = None
    diseases: List[str] = []
    entrezgene: Optional[str] = None
    type_of_gene: Optional[str] = None
    alphafold_url: Optional[str] = None
    aliases: List[str] = []

    offline = OFFLINE_UNIPROT.get(sym)
    if isinstance(offline, dict):
        sources_used.append("offline_uniprot")
        accession = str(offline.get("accession") or "") or None
        full_name = str(offline.get("full_name") or "") or None
        localization = str(offline.get("localization") or "") or None
        function = str(offline.get("function") or "") or None
        diseases = [str(d) for d in (offline.get("diseases") or []) if d]
        alphafold_url = offline.get("alphafold_url")

    mygene: Optional[Dict[str, Any]] = None
    try:
        mygene = _fetch_mygene(sym, cache)
    except Exception as exc:  # noqa: BLE001
        logger.debug("MyGene fetch failed for %s: %s", sym, exc)
    if mygene:
        sources_used.append("mygene")
        full_name = full_name or (str(mygene.get("name") or "") or None)
        summary = str(mygene.get("summary") or "") or None
        entrez = mygene.get("entrezgene")
        entrezgene = str(entrez) if entrez is not None else None
        type_of_gene = str(mygene.get("type_of_gene") or "") or None
        aliases = _as_list(mygene.get("alias"))[:12]
        mg_acc = _first_uniprot(mygene.get("uniprot"))
        if mg_acc and not accession:
            accession = mg_acc

    # Live UniProt fills function / diseases / localization when sparse
    need_uniprot = not function or not localization or not diseases or not accession
    if need_uniprot:
        try:
            live = LabUniProtClient(cache=cache).lookup(sym)
        except Exception as exc:  # noqa: BLE001
            logger.debug("UniProt lookup failed for %s: %s", sym, exc)
            live = None
        if isinstance(live, dict):
            sources_used.append("uniprot")
            acc = live.get("accession")
            if acc and not accession:
                accession = str(acc)
            full_name = full_name or (str(live.get("full_name") or "") or None)
            localization = localization or (str(live.get("localization") or "") or None)
            function = function or (str(live.get("function") or "") or None)
            if not diseases:
                diseases = [str(d) for d in (live.get("diseases") or []) if d]
            alphafold_url = alphafold_url or live.get("alphafold_url")

    if accession and not alphafold_url:
        alphafold_url = f"https://alphafold.ebi.ac.uk/entry/{accession}"

    # Prefer NCBI/MyGene summary as the long “function-like” prose when UniProt function empty
    if not function and summary:
        function = summary

    return {
        "gene_symbol": sym,
        "uniprot_id": accession,
        "accession": accession,
        "full_name": full_name,
        "localization": localization or "Unknown",
        "function": function,
        "summary": summary,
        "diseases": diseases[:12],
        "entrezgene": entrezgene,
        "type_of_gene": type_of_gene,
        "aliases": aliases,
        "alphafold_url": alphafold_url,
        "sources_used": sources_used or ["unresolved"],
    }
