"""Free-tier Literature Copilot — retrieve-only (no Redis / vector DB).

Fetches short Reactome + PubMed snippets for a gene / edge / disease query.
Does not invent kinetics; returns empty citations when upstream APIs fail.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging
import re

import httpx

logger = logging.getLogger(__name__)

PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
REACTOME_SEARCH = "https://reactome.org/ContentService/search/query"


def _clean_symbol(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9\-]", "", (raw or "").strip().upper())[:24]


def retrieve_literature(
    *,
    gene: str = "",
    partner: str = "",
    disease: str = "",
    max_hits: int = 5,
) -> Dict[str, Any]:
    """Retrieve PubMed + Reactome snippets. Always returns a stable shape."""
    g = _clean_symbol(gene)
    p = _clean_symbol(partner)
    d = (disease or "").strip()[:80]
    query_bits = [b for b in (g, p, d) if b]
    if not query_bits:
        return {
            "mode": "retrieve",
            "query": "",
            "citations": [],
            "reactome": [],
            "summary": "Provide a gene or disease to retrieve literature.",
            "ok": False,
        }

    pubmed_q = " AND ".join(query_bits)
    if g and p:
        pubmed_q = f"({g}[Title/Abstract] AND {p}[Title/Abstract])"
        if d:
            pubmed_q += f" AND ({d})"
    elif g:
        pubmed_q = f"{g}[Title/Abstract]"
        if d:
            pubmed_q += f" AND ({d})"

    citations: List[Dict[str, str]] = []
    reactome: List[Dict[str, str]] = []
    errors: List[str] = []

    try:
        with httpx.Client(timeout=4.0, follow_redirects=True) as client:
            er = client.get(
                PUBMED_SEARCH,
                params={
                    "db": "pubmed",
                    "retmode": "json",
                    "retmax": max(1, min(8, max_hits)),
                    "term": pubmed_q,
                },
            )
            if er.status_code == 200:
                ids = (er.json().get("esearchresult") or {}).get("idlist") or []
                if ids:
                    sr = client.get(
                        PUBMED_SUMMARY,
                        params={
                            "db": "pubmed",
                            "retmode": "json",
                            "id": ",".join(ids[:max_hits]),
                        },
                    )
                    if sr.status_code == 200:
                        result = (sr.json().get("result") or {})
                        for pmid in ids[:max_hits]:
                            row = result.get(pmid) or {}
                            title = str(row.get("title") or "").strip()
                            if not title:
                                continue
                            citations.append(
                                {
                                    "source": "pubmed",
                                    "id": str(pmid),
                                    "title": title[:240],
                                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                                }
                            )
            else:
                errors.append(f"pubmed_search:{er.status_code}")

            # Reactome free-text search (gene or disease)
            rq = g or d or p
            if rq:
                rr = client.get(
                    REACTOME_SEARCH,
                    params={
                        "query": rq,
                        "species": "Homo sapiens",
                        "types": "Pathway",
                        "cluster": "true",
                    },
                    headers={"Accept": "application/json"},
                )
                if rr.status_code == 200:
                    body = rr.json()
                    entries = []
                    if isinstance(body, dict):
                        entries = body.get("results") or body.get("entries") or []
                        if not entries and isinstance(body.get("rows"), list):
                            entries = body["rows"]
                    if isinstance(entries, list):
                        for ent in entries[:max_hits]:
                            if not isinstance(ent, dict):
                                continue
                            name = str(
                                ent.get("name")
                                or ent.get("stId")
                                or ent.get("displayName")
                                or ""
                            ).strip()
                            st = str(ent.get("stId") or ent.get("id") or "").strip()
                            if not name:
                                continue
                            reactome.append(
                                {
                                    "source": "reactome",
                                    "id": st or name[:32],
                                    "title": name[:240],
                                    "url": (
                                        f"https://reactome.org/content/detail/{st}"
                                        if st.startswith("R-")
                                        else "https://reactome.org/"
                                    ),
                                }
                            )
                else:
                    errors.append(f"reactome_search:{rr.status_code}")
    except Exception as exc:  # noqa: BLE001
        logger.info("literature retrieve failed: %s", exc)
        errors.append(type(exc).__name__)

    ok = bool(citations or reactome)
    summary = (
        f"Retrieved {len(citations)} PubMed + {len(reactome)} Reactome hits for «{' · '.join(query_bits)}»."
        if ok
        else f"No literature hits for «{' · '.join(query_bits)}» (APIs empty or unreachable)."
    )
    return {
        "mode": "retrieve",
        "query": " · ".join(query_bits),
        "citations": citations,
        "reactome": reactome,
        "summary": summary,
        "ok": ok,
        "errors": errors,
    }
