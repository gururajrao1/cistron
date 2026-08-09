"""Optional biomedical LLM narrative (HF Inference BioGPT or custom endpoint)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import hashlib
import logging
import os
import re

from cistron.integrations.cache_store import IntegrationCache
from cistron.integrations.http_sync import http_post_json

logger = logging.getLogger(__name__)

DEFAULT_HF_MODEL = "microsoft/biogpt"
# HF router inference (2025+); override with HF_INFERENCE_URL if needed.
DEFAULT_HF_URL = (
    "https://router.huggingface.co/hf-inference/models/" + DEFAULT_HF_MODEL
)


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
        "You are a biomedical educator explaining a gene/protein to a curious non-biologist.\n"
        "Use ONLY the facts below. Do not invent UniProt IDs, drugs, or clinical claims.\n"
        "Write exactly three short paragraphs labeled WHAT:, WHY:, NETWORK:.\n"
        "- WHAT: what the molecule is / does in plain English\n"
        "- WHY: why disease or systems biologists care\n"
        "- NETWORK: how it fits the listed neighbors and experiment context\n\n"
        "FACTS:\n- "
        + "\n- ".join(facts)
        + "\n\nAnswer:\n"
    )


def _extract_generated_text(payload: Any) -> Optional[str]:
    if payload is None:
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
        if payload.get("error"):
            logger.debug("LLM error payload: %s", payload.get("error"))
            return None
        for key in ("generated_text", "summary_text", "text", "content"):
            if payload.get(key):
                return str(payload[key]).strip()
        # OpenAI-ish
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict) and msg.get("content"):
                return str(msg["content"]).strip()
            if isinstance(choices[0], dict) and choices[0].get("text"):
                return str(choices[0]["text"]).strip()
    return None


def _parse_labeled_sections(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Pull WHAT / WHY / NETWORK sections when present."""
    cleaned = text.strip()
    # Strip echoed prompt if model returns full text
    if "Answer:" in cleaned:
        cleaned = cleaned.split("Answer:")[-1].strip()

    pattern = re.compile(
        r"(?:^|\n)\s*(WHAT|WHY|NETWORK)\s*:\s*(.+?)(?=(?:\n\s*(?:WHAT|WHY|NETWORK)\s*:)|$)",
        re.IGNORECASE | re.DOTALL,
    )
    found = {m.group(1).upper(): " ".join(m.group(2).split()) for m in pattern.finditer(cleaned)}
    if found:
        return found.get("WHAT"), found.get("WHY"), found.get("NETWORK")

    # Fallback: split into ~3 paragraphs
    paras = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    if len(paras) >= 3:
        return paras[0], paras[1], paras[2]
    if len(paras) == 2:
        return paras[0], paras[1], None
    if len(paras) == 1:
        return paras[0], None, None
    return None, None, None


def _call_hf(prompt: str, token: str) -> Optional[str]:
    url = os.environ.get("HF_INFERENCE_URL") or DEFAULT_HF_URL
    model = os.environ.get("HF_BIOMED_MODEL") or DEFAULT_HF_MODEL
    if "HF_INFERENCE_URL" not in os.environ and model != DEFAULT_HF_MODEL:
        url = f"https://router.huggingface.co/hf-inference/models/{model}"

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 280,
            "temperature": 0.4,
            "return_full_text": False,
        },
        "options": {"wait_for_model": True},
    }
    data = http_post_json(
        url,
        payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=28.0,
    )
    return _extract_generated_text(data)


def _call_custom_endpoint(prompt: str, endpoint: str) -> Optional[str]:
    """POST to BIOMED_LLM_URL — accepts HF-style or OpenAI chat completions shape."""
    token = os.environ.get("HF_TOKEN") or os.environ.get("BIOMED_LLM_TOKEN") or ""
    headers = {"Authorization": f"Bearer {token}"} if token else None

    # Try OpenAI chat first if URL looks like it
    if "chat/completions" in endpoint or endpoint.rstrip("/").endswith("v1"):
        chat_url = endpoint if endpoint.endswith("chat/completions") else endpoint.rstrip("/") + "/chat/completions"
        data = http_post_json(
            chat_url,
            {
                "model": os.environ.get("BIOMED_LLM_MODEL") or DEFAULT_HF_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "Explain genes plainly; never invent accessions.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 320,
                "temperature": 0.4,
            },
            headers=headers,
            timeout=28.0,
        )
        text = _extract_generated_text(data)
        if text:
            return text

    data = http_post_json(
        endpoint,
        {"inputs": prompt, "parameters": {"max_new_tokens": 280, "return_full_text": False}},
        headers=headers,
        timeout=28.0,
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
    mode = "biogpt"
    custom = os.environ.get("BIOMED_LLM_URL", "").strip()
    try:
        if custom:
            mode = "custom_llm"
            text = _call_custom_endpoint(prompt, custom)
        else:
            token = os.environ.get("HF_TOKEN", "").strip()
            if token:
                text = _call_hf(prompt, token)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Biomed LLM call failed: %s", exc)
        return None

    if not text:
        return None

    what, why, network = _parse_labeled_sections(text)
    if not what:
        return None

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
