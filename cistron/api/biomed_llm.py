"""Optional biomedical LLM narrative via Hugging Face Inference Providers.

``microsoft/biogpt`` is no longer hosted on HF serverless Inference, so we use
the OpenAI-compatible router (``router.huggingface.co/v1``) with a small
instruct model and a biomedical education prompt grounded in retrieved facts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import hashlib
import logging
import os
import re

from cistron.integrations.cache_store import IntegrationCache
from cistron.integrations.http_sync import http_post_json

logger = logging.getLogger(__name__)

# Default: small instruct model on HF Inference Providers (not BioGPT weights —
# BioGPT is not deployed on serverless providers as of 2026).
DEFAULT_HF_MODEL = "HuggingFaceTB/SmolLM3-3B-Instruct"
DEFAULT_HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions"


def llm_available() -> bool:
    return bool(os.environ.get("HF_TOKEN") or os.environ.get("BIOMED_LLM_URL"))


def _neighbor_hash(
    upstream: Sequence[str],
    downstream: Sequence[str],
    condition: str,
) -> str:
    raw = f"{condition}|{'/'.join(upstream)}|{'/'.join(downstream)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _build_prompt(
    knowledge: Dict[str, Any],
    *,
    condition_query: str,
    upstream: Sequence[str],
    downstream: Sequence[str],
) -> str:
    sym = knowledge.get("gene_symbol") or "GENE"
    facts = [
        f"Gene symbol: {sym}",
        f"Full name: {knowledge.get('full_name') or 'unknown'}",
        f"Localization: {knowledge.get('localization') or 'unknown'}",
        f"Type: {knowledge.get('type_of_gene') or 'protein-coding (assumed)'}",
        f"UniProt: {knowledge.get('uniprot_id') or knowledge.get('accession') or 'none'}",
        f"Entrez: {knowledge.get('entrezgene') or 'none'}",
    ]
    summary = knowledge.get("summary") or knowledge.get("function") or ""
    if summary:
        facts.append(f"Curated summary: {str(summary)[:700]}")
    diseases = knowledge.get("diseases") or []
    if diseases:
        facts.append("Diseases: " + ", ".join(str(d) for d in diseases[:8]))
    if condition_query.strip():
        facts.append(f"User experiment / disease context: {condition_query.strip()}")
    if upstream:
        facts.append("Upstream neighbors in network: " + ", ".join(list(upstream)[:8]))
    if downstream:
        facts.append("Downstream neighbors in network: " + ", ".join(list(downstream)[:8]))

    return (
        "Explain this gene/protein to a curious non-biologist.\n"
        "Use ONLY the facts below. Do not invent UniProt IDs, drugs, or clinical claims.\n"
        "Write exactly three short paragraphs labeled WHAT:, WHY:, NETWORK:.\n"
        "- WHAT: what the molecule is / does in plain English\n"
        "- WHY: why disease or systems biologists care\n"
        "- NETWORK: how it fits the listed neighbors and experiment context\n\n"
        "FACTS:\n- "
        + "\n- ".join(facts)
    )


def _extract_generated_text(payload: Any) -> Optional[str]:
    if payload is None:
        return None
    if isinstance(payload, dict) and payload.get("error"):
        logger.warning("HF LLM error: %s", payload.get("error"))
        return None
    if isinstance(payload, str):
        return payload.strip() or None
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            for key in ("generated_text", "summary_text", "text"):
                if first.get(key):
                    return str(first[key]).strip()
        if isinstance(first, str):
            return first.strip()
    if isinstance(payload, dict):
        for key in ("generated_text", "summary_text", "text", "content"):
            if payload.get(key):
                return str(payload[key]).strip()
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict) and msg.get("content"):
                return str(msg["content"]).strip()
            if isinstance(choices[0], dict) and choices[0].get("text"):
                return str(choices[0]["text"]).strip()
    return None


def _parse_labeled_sections(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    cleaned = text.strip()
    if "Answer:" in cleaned:
        cleaned = cleaned.split("Answer:")[-1].strip()

    pattern = re.compile(
        r"(?:^|\n)\s*(WHAT|WHY|NETWORK)\s*:\s*(.+?)(?=(?:\n\s*(?:WHAT|WHY|NETWORK)\s*:)|$)",
        re.IGNORECASE | re.DOTALL,
    )
    found = {m.group(1).upper(): " ".join(m.group(2).split()) for m in pattern.finditer(cleaned)}
    if found:
        return found.get("WHAT"), found.get("WHY"), found.get("NETWORK")

    paras = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    if len(paras) >= 3:
        return paras[0], paras[1], paras[2]
    if len(paras) == 2:
        return paras[0], paras[1], None
    if len(paras) == 1:
        return paras[0], None, None
    return None, None, None


def _call_hf_chat(prompt: str, token: str) -> Optional[str]:
    """Hugging Face Inference Providers — OpenAI-compatible chat API."""
    url = os.environ.get("HF_CHAT_URL") or DEFAULT_HF_CHAT_URL
    model = os.environ.get("HF_BIOMED_MODEL") or DEFAULT_HF_MODEL
    data = http_post_json(
        url,
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a biomedical educator. Explain genes plainly. "
                        "Never invent accession IDs or unsupported medical claims."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 360,
            "temperature": 0.35,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=45.0,
    )
    return _extract_generated_text(data)


def _call_custom_endpoint(prompt: str, endpoint: str) -> Optional[str]:
    """POST to BIOMED_LLM_URL — OpenAI chat or HF-style inputs."""
    token = os.environ.get("HF_TOKEN") or os.environ.get("BIOMED_LLM_TOKEN") or ""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    model = os.environ.get("BIOMED_LLM_MODEL") or os.environ.get("HF_BIOMED_MODEL") or DEFAULT_HF_MODEL

    chat_url = endpoint
    if not endpoint.endswith("chat/completions"):
        if endpoint.rstrip("/").endswith("v1"):
            chat_url = endpoint.rstrip("/") + "/chat/completions"
        elif "chat/completions" not in endpoint:
            # try as chat base
            chat_url = endpoint.rstrip("/") + "/v1/chat/completions"

    data = http_post_json(
        chat_url,
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Explain genes plainly; never invent accessions.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 360,
            "temperature": 0.35,
        },
        headers=headers,
        timeout=45.0,
    )
    text = _extract_generated_text(data)
    if text:
        return text

    data = http_post_json(
        endpoint,
        {"inputs": prompt, "parameters": {"max_new_tokens": 280, "return_full_text": False}},
        headers=headers,
        timeout=45.0,
    )
    return _extract_generated_text(data)


def generate_biomed_narrative(
    knowledge: Dict[str, Any],
    *,
    condition_query: str = "",
    upstream: Optional[Sequence[str]] = None,
    downstream: Optional[Sequence[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Return ``{plain_english, why_it_matters, in_this_network, narrative_mode}``
    or None if LLM unavailable / failed (caller should keep template text).
    """
    if not llm_available():
        return None

    up = [u for u in (upstream or []) if u]
    down = [d for d in (downstream or []) if d]
    sym = str(knowledge.get("gene_symbol") or "").upper()
    cache = IntegrationCache()
    cache_key = f"{sym}:{_neighbor_hash(up, down, condition_query)}"
    cached = cache.get_json("biomed_narrative", cache_key)
    if isinstance(cached, dict) and cached.get("plain_english"):
        out = dict(cached)
        out["narrative_mode"] = "cached"
        return out

    prompt = _build_prompt(
        knowledge,
        condition_query=condition_query,
        upstream=up,
        downstream=down,
    )

    text: Optional[str] = None
    mode = "hf_llm"
    custom = os.environ.get("BIOMED_LLM_URL", "").strip()
    try:
        if custom:
            mode = "custom_llm"
            text = _call_custom_endpoint(prompt, custom)
        else:
            token = os.environ.get("HF_TOKEN", "").strip()
            if token:
                text = _call_hf_chat(prompt, token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Biomed LLM call failed: %s", exc)
        return None

    if not text:
        logger.warning("Biomed LLM returned empty text for %s", sym)
        return None

    what, why, network = _parse_labeled_sections(text)
    if not what:
        # Still surface raw model text as WHAT if labels missing
        what = " ".join(text.split())[:500]

    result = {
        "plain_english": what,
        "why_it_matters": why or what,
        "in_this_network": network
        or (
            f"In the current graph, {sym} connects to "
            f"{', '.join((list(up) + list(down))[:6]) or 'no listed neighbors'}."
        ),
        "narrative_mode": mode,
        "raw_excerpt": text[:1200],
    }
    cache.set_json("biomed_narrative", cache_key, result, ttl=3 * 86_400.0)
    return result


def _build_disease_impact_prompt(
    knowledge: Dict[str, Any],
    *,
    condition_query: str,
    upstream: Sequence[str],
    downstream: Sequence[str],
    delta_y: Optional[float],
    role: str,
) -> str:
    sym = knowledge.get("gene_symbol") or "GENE"
    disease = condition_query.strip() or "the mapped pathway disease"
    facts = [
        f"Gene: {sym}",
        f"Full name: {knowledge.get('full_name') or 'unknown'}",
        f"Disease / pathway context: {disease}",
        f"Network role guess: {role}",
        f"Upstream: {', '.join(list(upstream)[:8]) or 'none listed'}",
        f"Downstream: {', '.join(list(downstream)[:8]) or 'none listed'}",
    ]
    summary = knowledge.get("summary") or knowledge.get("function") or ""
    if summary:
        facts.append(f"Curated summary: {str(summary)[:500]}")
    if delta_y is not None:
        facts.append(f"Latest simulation Δy: {float(delta_y):+.3f}")

    return (
        "You explain how changing this protein could matter in a disease pathway.\n"
        "Use ONLY the facts. No invented drugs, clinical advice, or accessions.\n"
        "Write exactly four short paragraphs labeled OVERVIEW:, UP:, DOWN:, STRUCTURE:.\n"
        f"- OVERVIEW: how {sym} sits in «{disease}» (1-2 sentences)\n"
        "- UP: if activity/expression goes up, what likely happens to the network\n"
        "- DOWN: if activity is reduced or knocked out, what likely happens\n"
        "- STRUCTURE: if structure or protein–protein interactions change "
        "(mutation, binding, PTM), how that could rewire the same edges\n\n"
        "FACTS:\n- "
        + "\n- ".join(facts)
    )


def _parse_disease_impact_sections(text: str) -> Dict[str, Optional[str]]:
    cleaned = text.strip()
    if "Answer:" in cleaned:
        cleaned = cleaned.split("Answer:")[-1].strip()
    pattern = re.compile(
        r"(?:^|\n)\s*(OVERVIEW|UP|DOWN|STRUCTURE)\s*:\s*(.+?)(?=(?:\n\s*(?:OVERVIEW|UP|DOWN|STRUCTURE)\s*:)|$)",
        re.IGNORECASE | re.DOTALL,
    )
    found = {
        m.group(1).upper(): " ".join(m.group(2).split()) for m in pattern.finditer(cleaned)
    }
    if found:
        return {
            "overview": found.get("OVERVIEW"),
            "if_activity_up": found.get("UP"),
            "if_activity_down": found.get("DOWN"),
            "structure_or_interaction": found.get("STRUCTURE"),
        }
    paras = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    keys = ["overview", "if_activity_up", "if_activity_down", "structure_or_interaction"]
    out: Dict[str, Optional[str]] = {k: None for k in keys}
    for i, k in enumerate(keys):
        if i < len(paras):
            out[k] = paras[i]
    return out


def generate_disease_impact_narrative(
    knowledge: Dict[str, Any],
    *,
    condition_query: str = "",
    upstream: Optional[Sequence[str]] = None,
    downstream: Optional[Sequence[str]] = None,
    delta_y: Optional[float] = None,
    role: str = "connector",
) -> Optional[Dict[str, Any]]:
    """
    LLM polish for disease-context impact paragraphs.
    Returns keys matching ``build_disease_impact`` or None on failure.
    """
    if not llm_available():
        return None

    up = [u for u in (upstream or []) if u]
    down = [d for d in (downstream or []) if d]
    sym = str(knowledge.get("gene_symbol") or "").upper()
    dy = "" if delta_y is None else f"{float(delta_y):.3f}"
    cache = IntegrationCache()
    cache_key = f"impact:{sym}:{_neighbor_hash(up, down, condition_query)}:{role}:{dy}"
    cached = cache.get_json("disease_impact", cache_key)
    if isinstance(cached, dict) and cached.get("overview"):
        out = dict(cached)
        out["mode"] = "cached"
        return out

    prompt = _build_disease_impact_prompt(
        knowledge,
        condition_query=condition_query,
        upstream=up,
        downstream=down,
        delta_y=delta_y,
        role=role,
    )

    text: Optional[str] = None
    mode = "hf_llm"
    custom = os.environ.get("BIOMED_LLM_URL", "").strip()
    try:
        if custom:
            mode = "custom_llm"
            text = _call_custom_endpoint(prompt, custom)
        else:
            token = os.environ.get("HF_TOKEN", "").strip()
            if token:
                text = _call_hf_chat(prompt, token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Disease-impact LLM call failed: %s", exc)
        return None

    if not text:
        return None

    sections = _parse_disease_impact_sections(text)
    if not sections.get("overview"):
        sections["overview"] = " ".join(text.split())[:420]

    result = {
        "overview": sections.get("overview") or "",
        "if_activity_up": sections.get("if_activity_up") or "",
        "if_activity_down": sections.get("if_activity_down") or "",
        "structure_or_interaction": sections.get("structure_or_interaction") or "",
        "mode": mode,
        "raw_excerpt": text[:1200],
    }
    # Require at least overview + one change scenario
    if not result["overview"] or not (
        result["if_activity_up"] or result["if_activity_down"] or result["structure_or_interaction"]
    ):
        return None

    cache.set_json("disease_impact", cache_key, result, ttl=3 * 86_400.0)
    return result
