"""
Knowledge-integration clients for CISTRON Phase 2.

Asynchronous, rate-limited wrappers around public biology APIs that materialise
Phase 1 :class:`~cistron.topology.SignalingNetwork` objects and enrich
:class:`~cistron.components.Protein` nodes with sequence / domain context.

Supported sources
-----------------
* **UniProt** — protein sequences, domains, active / binding sites
* **KEGG** — pathway maps via KGML (e.g. ``hsa04010`` MAPK)
* **Reactome** — ContentService pathway participants & reaction edges
* **STRING** — scored PPI neighbourhoods → edge weights
* **BioGRID** — tabulated physical / genetic interactions (API key optional)

All network I/O is failure-tolerant: HTTP errors, timeouts, and malformed
payloads are logged and return empty / partial structures rather than crashing
the ETL layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import asyncio
import json
import logging
import math
import re
import time
import xml.etree.ElementTree as ET

from cistron.cache import ResponseCache
from cistron.components import KineticParameters, Protein
from cistron.topology import InteractionType, SignalingNetwork

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiting + HTTP (cache-aware, exponential backoff)
# ---------------------------------------------------------------------------


class AsyncRateLimiter:
    """
    Token-bucket style limiter: at most ``rate`` acquisitions per ``per`` seconds.

    Safe for concurrent ``asyncio`` tasks via an internal lock.
    """

    def __init__(self, rate: float = 5.0, per: float = 1.0) -> None:
        if rate <= 0.0 or per <= 0.0:
            raise ValueError("rate and per must be positive")
        self.rate = float(rate)
        self.per = float(per)
        self._allowance = float(rate)
        self._last_check = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_check
                self._last_check = now
                self._allowance += elapsed * (self.rate / self.per)
                if self._allowance > self.rate:
                    self._allowance = self.rate
                if self._allowance >= 1.0:
                    self._allowance -= 1.0
                    return
                deficit = 1.0 - self._allowance
                sleep_for = deficit * (self.per / self.rate)
                await asyncio.sleep(max(sleep_for, 0.01))


@dataclass
class HTTPResponse:
    """Minimal response object returned by :class:`AsyncHTTPClient`."""

    url: str
    status: int
    body: bytes
    headers: Dict[str, str] = field(default_factory=dict)
    from_cache: bool = False

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def json(self) -> Any:
        return json.loads(self.text())


class AsyncHTTPClient:
    """
    Shared async HTTP GET helper with SQLite cache lookup and exponential backoff.

    Cache contract
    --------------
    On every GET the client checks ``(cache_namespace, url)`` first. Hits return
    immediately without consuming a rate-limit token. Successful network
    responses (2xx) are serialised into the cache with a configurable TTL.
    """

    def __init__(
        self,
        *,
        rate: float = 5.0,
        per: float = 1.0,
        timeout: float = 30.0,
        user_agent: str = "CISTRON/0.2 (+https://github.com/cistron)",
        max_retries: int = 4,
        backoff: float = 0.75,
        cache: Optional[ResponseCache] = None,
        cache_namespace: str = "http",
        cache_ttl: float = 86_400.0,
    ) -> None:
        self.limiter = AsyncRateLimiter(rate=rate, per=per)
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.backoff = backoff
        self.cache = cache
        self.cache_namespace = cache_namespace
        self.cache_ttl = cache_ttl
        self.cache_hits = 0
        self.cache_misses = 0

    def _blocking_get(self, url: str, headers: Optional[Mapping[str, str]] = None) -> HTTPResponse:
        hdrs = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if headers:
            hdrs.update(dict(headers))
        request = Request(url, headers=hdrs, method="GET")
        with urlopen(request, timeout=self.timeout) as resp:  # nosec B310
            status = getattr(resp, "status", 200) or 200
            body = resp.read()
            resp_headers = {k: v for k, v in resp.headers.items()}
            return HTTPResponse(url=url, status=int(status), body=body, headers=resp_headers)

    def _cache_lookup(self, url: str, namespace: Optional[str] = None) -> Optional[HTTPResponse]:
        if self.cache is None:
            return None
        ns = namespace or self.cache_namespace
        entry = self.cache.get(ns, url)
        if entry is None:
            self.cache_misses += 1
            return None
        self.cache_hits += 1
        payload = entry.payload
        if isinstance(payload, dict) and "body_text" in payload:
            body = str(payload["body_text"]).encode("utf-8")
            status = int(payload.get("status", entry.status))
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
            status = entry.status
        else:
            body = json.dumps(payload).encode("utf-8")
            status = entry.status
        logger.debug("Cache HIT %s/%s", ns, url[:80])
        return HTTPResponse(
            url=url,
            status=status,
            body=body,
            headers={"X-CISTRON-Cache": "HIT"},
            from_cache=True,
        )

    def _cache_store(
        self,
        url: str,
        response: HTTPResponse,
        namespace: Optional[str] = None,
    ) -> None:
        if self.cache is None or response.status < 200 or response.status >= 300:
            return
        ns = namespace or self.cache_namespace
        try:
            try:
                parsed = response.json()
                payload: Any = parsed
                content_type = "application/json"
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {"body_text": response.text(), "status": response.status}
                content_type = "text/plain+envelope"
            self.cache.set(
                ns,
                url,
                payload,
                ttl=self.cache_ttl,
                content_type=content_type,
                status=response.status,
            )
        except ValueError as exc:
            logger.warning("Could not cache %s: %s", url, exc)

    async def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        use_cache: bool = True,
        cache_namespace: Optional[str] = None,
    ) -> HTTPResponse:
        ns = cache_namespace or self.cache_namespace
        if use_cache:
            cached = self._cache_lookup(url, namespace=ns)
            if cached is not None:
                return cached

        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_retries + 1):
            await self.limiter.acquire()
            try:
                response = await asyncio.to_thread(self._blocking_get, url, headers)
                if use_cache:
                    self._cache_store(url, response, namespace=ns)
                return response
            except HTTPError as exc:
                last_error = exc
                status = exc.code
                body = exc.read() if hasattr(exc, "read") else b""
                if status == 404:
                    return HTTPResponse(url=url, status=404, body=body or b"")
                if status in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    delay = self.backoff * (2 ** (attempt - 1))
                    retry_after = exc.headers.get("Retry-After") if hasattr(exc, "headers") else None
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except (TypeError, ValueError):
                            pass
                    logger.warning(
                        "HTTP %s for %s (attempt %s/%s) — backoff %.2fs",
                        status,
                        url,
                        attempt,
                        self.max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("HTTP error %s for %s: %s", status, url, exc)
                return HTTPResponse(url=url, status=status, body=body or str(exc).encode())
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = self.backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Network error for %s (attempt %s/%s): %s — backoff %.2fs",
                        url,
                        attempt,
                        self.max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("Network failure for %s after retries: %s", url, exc)
                return HTTPResponse(url=url, status=0, body=str(exc).encode())
        raise RuntimeError(f"GET failed for {url}: {last_error}")


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class ProteinDomain:
    """UniProt topological / functional domain annotation."""

    name: str
    start: int
    end: int
    kind: str = "domain"
    description: str = ""


@dataclass
class UniProtRecord:
    """Subset of UniProtKB fields consumed by CISTRON."""

    accession: str
    gene_name: Optional[str]
    protein_name: Optional[str]
    organism: Optional[str]
    sequence: str
    length: int
    domains: List[ProteinDomain] = field(default_factory=list)
    active_sites: List[ProteinDomain] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_protein(self, *, concentration: float = 0.1) -> Protein:
        """Materialise a Phase 1 :class:`~cistron.components.Protein`."""
        name = self.gene_name or self.protein_name or self.accession
        protein = Protein(
            name=name,
            concentration=concentration,
            sequence_length=self.length if self.length > 0 else None,
            is_enzyme=any("Catalytic" in k or "Hydrolase" in k or "Kinase" in k for k in self.keywords),
            metadata={
                "uniprot_accession": self.accession,
                "protein_name": self.protein_name,
                "organism": self.organism,
                "domains": [d.__dict__ for d in self.domains],
                "active_sites": [d.__dict__ for d in self.active_sites],
                "sequence_preview": self.sequence[:50],
            },
        )
        return protein


@dataclass
class PathwayRelation:
    """Directed pathway edge prior to network insertion."""

    source: str
    target: str
    interaction_type: InteractionType
    weight: float = 1.0
    evidence: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    stoichiometry_source: float = 1.0
    stoichiometry_target: float = 1.0
    role: str = "interaction"
    """``interaction`` | ``substrate_to_product`` | ``catalysis`` | ``consumption``"""


@dataclass
class StoichiometricSpecies:
    """One participant in a reaction with a stoichiometric coefficient."""

    name: str
    coefficient: float = 1.0
    role: str = "substrate"
    """``substrate`` | ``product`` | ``catalyst``"""
    entry_id: str = ""
    entity_type: str = "gene"

    def __post_init__(self) -> None:
        if self.coefficient <= 0.0:
            raise ValueError(f"stoichiometric coefficient must be positive for {self.name}")
        if self.role not in {"substrate", "product", "catalyst"}:
            raise ValueError(f"invalid species role {self.role!r}")


@dataclass
class ReactionDefinition:
    """
    Stoichiometric reaction:

        Σ ν_s · S  —[enzyme]→  Σ ν_p · P
    """

    reaction_id: str
    name: str
    reversible: bool = False
    substrates: List[StoichiometricSpecies] = field(default_factory=list)
    products: List[StoichiometricSpecies] = field(default_factory=list)
    catalysts: List[StoichiometricSpecies] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def stoichiometry_matrix(
        self,
        species_order: Optional[Sequence[str]] = None,
    ) -> Tuple[List[str], List[float]]:
        """
        Return ``(species_names, coefficients)`` with substrates negative and
        products positive (catalysts omitted from net mass balance).
        """
        coeffs: Dict[str, float] = {}
        for s in self.substrates:
            coeffs[s.name] = coeffs.get(s.name, 0.0) - float(s.coefficient)
        for p in self.products:
            coeffs[p.name] = coeffs.get(p.name, 0.0) + float(p.coefficient)
        order = list(species_order) if species_order is not None else sorted(coeffs)
        for name in coeffs:
            if name not in order:
                order.append(name)
        return order, [coeffs.get(n, 0.0) for n in order]


@dataclass
class PathwayMap:
    """Normalised pathway payload from KEGG or Reactome."""

    pathway_id: str
    name: str
    source_db: str
    nodes: Dict[str, str]
    """display / gene name → preferred node label"""
    relations: List[PathwayRelation] = field(default_factory=list)
    reactions: List[ReactionDefinition] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PPIEdge:
    """Protein–protein interaction with a confidence score in ``[0, 1]``."""

    protein_a: str
    protein_b: str
    score: float
    evidence: str
    directed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = float(min(1.0, max(0.0, self.score)))


# ---------------------------------------------------------------------------
# UniProt
# ---------------------------------------------------------------------------


class UniProtClient:
    """UniProtKB REST client (JSON) with optional SQLite response cache."""

    BASE = "https://rest.uniprot.org"
    NAMESPACE = "uniprot"

    def __init__(
        self,
        http: Optional[AsyncHTTPClient] = None,
        *,
        cache: Optional[ResponseCache] = None,
    ) -> None:
        if http is None:
            self.http = AsyncHTTPClient(
                rate=5.0, per=1.0, cache=cache, cache_namespace=self.NAMESPACE
            )
        else:
            if cache is not None and http.cache is None:
                http.cache = cache
            self.http = http

    async def _get(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.http.get(url, cache_namespace=self.NAMESPACE, **kwargs)

    async def fetch_accession(self, accession: str) -> Optional[UniProtRecord]:
        acc = accession.strip()
        if not acc:
            raise ValueError("accession must be non-empty")
        url = f"{self.BASE}/uniprotkb/{quote(acc)}.json"
        try:
            resp = await self._get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("UniProt fetch failed for %s: %s", acc, exc)
            return None
        if resp.status != 200:
            logger.warning("UniProt %s returned HTTP %s", acc, resp.status)
            return None
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            logger.error("UniProt JSON decode failed for %s: %s", acc, exc)
            return None
        return self._parse_entry(payload)

    async def search_gene(
        self,
        gene_symbol: str,
        *,
        organism_id: int = 9606,
        limit: int = 1,
    ) -> List[UniProtRecord]:
        query = f'(gene_exact:{gene_symbol}) AND (organism_id:{organism_id})'
        params = urlencode(
            {
                "query": query,
                "format": "json",
                "size": str(max(1, limit)),
                "fields": "accession,gene_names,protein_name,organism_name,sequence,ft_domain,ft_act_site,ft_binding,keyword",
            }
        )
        url = f"{self.BASE}/uniprotkb/search?{params}"
        try:
            resp = await self._get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover
            logger.exception("UniProt search failed for %s: %s", gene_symbol, exc)
            return []
        if resp.status != 200:
            logger.warning("UniProt search %s → HTTP %s", gene_symbol, resp.status)
            return []
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            logger.error("UniProt search JSON decode failed: %s", exc)
            return []
        results: List[UniProtRecord] = []
        for entry in payload.get("results", []) or []:
            parsed = self._parse_entry(entry)
            if parsed is not None:
                results.append(parsed)
        return results

    def _parse_entry(self, payload: Mapping[str, Any]) -> Optional[UniProtRecord]:
        try:
            accession = str(payload.get("primaryAccession") or payload.get("uniProtkbId") or "")
            if not accession:
                return None
            genes = payload.get("genes") or []
            gene_name = None
            if genes:
                gene_name = (genes[0].get("geneName") or {}).get("value")
            desc = payload.get("proteinDescription") or {}
            recommended = (desc.get("recommendedName") or {}).get("fullName") or {}
            protein_name = recommended.get("value")
            organism = (payload.get("organism") or {}).get("scientificName")
            seq_block = payload.get("sequence") or {}
            sequence = str(seq_block.get("value") or "")
            length = int(seq_block.get("length") or len(sequence) or 0)
            domains: List[ProteinDomain] = []
            active_sites: List[ProteinDomain] = []
            for feature in payload.get("features") or []:
                ftype = str(feature.get("type") or "")
                location = feature.get("location") or {}
                start = int((location.get("start") or {}).get("value") or 0)
                end = int((location.get("end") or {}).get("value") or start)
                description = str(feature.get("description") or "")
                domain = ProteinDomain(
                    name=description or ftype,
                    start=start,
                    end=end,
                    kind=ftype,
                    description=description,
                )
                if ftype.lower() in {"domain", "topological domain", "region", "motif", "transmembrane"}:
                    domains.append(domain)
                elif ftype.lower() in {"active site", "binding site", "site"}:
                    active_sites.append(domain)
            keywords = [
                str(k.get("name") or k.get("id") or "")
                for k in (payload.get("keywords") or [])
                if isinstance(k, dict)
            ]
            return UniProtRecord(
                accession=accession,
                gene_name=gene_name,
                protein_name=protein_name,
                organism=organism,
                sequence=sequence,
                length=length,
                domains=domains,
                active_sites=active_sites,
                keywords=[k for k in keywords if k],
                raw=dict(payload),
            )
        except (TypeError, ValueError, KeyError) as exc:
            logger.error("Failed to parse UniProt entry: %s", exc)
            return None


# ---------------------------------------------------------------------------
# KEGG
# ---------------------------------------------------------------------------


_KEGG_RELATION_MAP = {
    "activation": InteractionType.ACTIVATION,
    "expression": InteractionType.ACTIVATION,
    "indirect effect": InteractionType.ACTIVATION,
    "binding/association": InteractionType.BINDING,
    "dissociation": InteractionType.DISSOCIATION,
    "missing interaction": InteractionType.BINDING,
    "phosphorylation": InteractionType.PHOSPHORYLATION,
    "dephosphorylation": InteractionType.DEPHOSPHORYLATION,
    "glycosylation": InteractionType.CATALYSIS,
    "ubiquitination": InteractionType.UBIQUITINATION,
    "methylation": InteractionType.CATALYSIS,
    "inhibition": InteractionType.INHIBITION,
    "repression": InteractionType.INHIBITION,
}


class KEGGClient:
    """KEGG REST + KGML pathway translator with stoichiometric reaction parsing."""

    BASE = "https://rest.kegg.jp"
    NAMESPACE = "kegg"

    def __init__(
        self,
        http: Optional[AsyncHTTPClient] = None,
        *,
        cache: Optional[ResponseCache] = None,
    ) -> None:
        if http is None:
            http = AsyncHTTPClient(rate=3.0, per=1.0, cache=cache, cache_namespace=self.NAMESPACE)
        else:
            if cache is not None and http.cache is None:
                http.cache = cache
        self.http = http

    async def _get(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.http.get(url, cache_namespace=self.NAMESPACE, **kwargs)

    async def fetch_pathway_kgml(self, pathway_id: str = "hsa04010") -> Optional[str]:
        pid = pathway_id.strip()
        url = f"{self.BASE}/get/{quote(pid)}/kgml"
        try:
            resp = await self._get(url)
        except Exception as excel:  # pragma: no cover
            logger.exception("KEGG KGML fetch failed for %s: %s", pid, excel)
            return None
        if resp.status != 200 or not resp.body:
            logger.warning("KEGG KGML %s → HTTP %s", pid, resp.status)
            return None
        # Cache stores JSON preferentially; text pathways may arrive as envelope or raw
        if resp.from_cache:
            try:
                parsed = resp.json()
                if isinstance(parsed, dict) and "body_text" in parsed:
                    return str(parsed["body_text"])
            except json.JSONDecodeError:
                pass
        return resp.text()

    async def fetch_pathway_map(self, pathway_id: str = "hsa04010") -> Optional[PathwayMap]:
        kgml = await self.fetch_pathway_kgml(pathway_id)
        if not kgml:
            # Air-gapped / cold-start fallback — never return None for MAPK if vendored
            try:
                from cistron.vendored import VendoredPathwayRepository

                repo = VendoredPathwayRepository()
                if repo.has(pathway_id):
                    logger.warning(
                        "KEGG API unavailable for %s — using VendoredPathwayRepository",
                        pathway_id,
                    )
                    return repo.load_map(pathway_id)
            except Exception as exc:
                logger.exception("Vendored pathway fallback failed for %s: %s", pathway_id, exc)
            return None
        return self.parse_kgml(kgml, pathway_id=pathway_id)

    def parse_kgml(self, kgml_text: str, *, pathway_id: str = "unknown") -> PathwayMap:
        """
        Parse KEGG KGML into a :class:`PathwayMap` with true reaction stoichiometry.

        Sources of directed structure
        -----------------------------
        1. ``<reaction>`` blocks → substrates / products (+ coefficients when present).
        2. Gene / enzyme ``entry`` nodes referencing ``reaction="rn:…"`` → catalysts.
        3. Legacy ``<relation>`` PPrel/GErel edges (activation, phospho, …) retained
           for signalling maps that omit explicit reaction XML.
        """
        try:
            root = ET.fromstring(kgml_text)
        except ET.ParseError as exc:
            logger.error("Invalid KGML for %s: %s", pathway_id, exc)
            return PathwayMap(
                pathway_id=pathway_id, name=pathway_id, source_db="KEGG", nodes={}, relations=[]
            )

        title = root.attrib.get("title") or pathway_id
        org = root.attrib.get("org") or ""
        entries: Dict[str, Dict[str, Any]] = {}
        nodes: Dict[str, str] = {}
        reaction_catalysts: Dict[str, List[str]] = {}

        for entry in root.findall("entry"):
            eid = entry.attrib.get("id", "")
            etype = entry.attrib.get("type", "")
            names = (entry.attrib.get("name") or "").split()
            graphics = entry.find("graphics")
            display = graphics.attrib.get("name") if graphics is not None else None
            label = None
            if display:
                label = display.split(",")[0].split("…")[0].split("...")[0].strip()
            if not label and names:
                label = names[0].split(":")[-1]
            if not label:
                label = f"entry_{eid}"
            rxn_attr = (entry.attrib.get("reaction") or "").strip()
            entries[eid] = {
                "type": etype,
                "names": names,
                "label": label,
                "raw_display": display,
                "reactions": rxn_attr.split() if rxn_attr else [],
            }
            if etype in {"gene", "ortholog", "compound", "enzyme", "group"}:
                nodes[label] = label
            for rn in entries[eid]["reactions"]:
                reaction_catalysts.setdefault(rn, []).append(label)

        # --- stoichiometric reactions ---
        reactions: List[ReactionDefinition] = []
        stoich_relations: List[PathwayRelation] = []
        for rxn in root.findall("reaction"):
            rid = rxn.attrib.get("id", "")
            rname = rxn.attrib.get("name", f"reaction_{rid}")
            reversible = (rxn.attrib.get("type") or "").lower() == "reversible"
            substrates: List[StoichiometricSpecies] = []
            products: List[StoichiometricSpecies] = []
            for tag, bucket, role in (
                ("substrate", substrates, "substrate"),
                ("product", products, "product"),
            ):
                for node in rxn.findall(tag):
                    ref_id = node.attrib.get("id", "")
                    coeff = _parse_coeff(node.attrib.get("stoichiometry") or node.attrib.get("coefficient"))
                    label = entries.get(ref_id, {}).get("label") or node.attrib.get("name") or ref_id
                    etype = entries.get(ref_id, {}).get("type", "compound")
                    if label:
                        nodes.setdefault(label, label)
                    bucket.append(
                        StoichiometricSpecies(
                            name=str(label),
                            coefficient=coeff,
                            role=role,
                            entry_id=ref_id,
                            entity_type=str(etype),
                        )
                    )
            catalysts: List[StoichiometricSpecies] = []
            # Match catalysts by reaction name tokens (rn:Rxxxxx)
            for token in rname.split():
                for enz in reaction_catalysts.get(token, []):
                    catalysts.append(
                        StoichiometricSpecies(
                            name=enz,
                            coefficient=1.0,
                            role="catalyst",
                            entity_type="gene",
                        )
                    )
                    nodes.setdefault(enz, enz)
            # Also: gene entries whose reaction list intersects
            for enz_list in reaction_catalysts.values():
                pass  # already handled via token map
            # Fallback: KGML sometimes links enzyme via same reaction id as entry id map
            for entry_id, meta in entries.items():
                if rid and rid in (meta.get("reactions") or []):
                    catalysts.append(
                        StoichiometricSpecies(
                            name=meta["label"],
                            coefficient=1.0,
                            role="catalyst",
                            entry_id=entry_id,
                            entity_type=meta.get("type", "gene"),
                        )
                    )
            # Deduplicate catalysts by name
            seen_c: Set[str] = set()
            uniq_catalysts: List[StoichiometricSpecies] = []
            for c in catalysts:
                if c.name in seen_c:
                    continue
                seen_c.add(c.name)
                uniq_catalysts.append(c)

            reaction = ReactionDefinition(
                reaction_id=rid or rname,
                name=rname,
                reversible=reversible,
                substrates=substrates,
                products=products,
                catalysts=uniq_catalysts,
                metadata={"source": "KEGG_KGML"},
            )
            reactions.append(reaction)
            stoich_relations.extend(reaction_to_relations(reaction, evidence_prefix="KEGG"))

        # --- classic PPrel relations (signalling) ---
        relations: List[PathwayRelation] = list(stoich_relations)
        for rel in root.findall("relation"):
            entry1 = rel.attrib.get("entry1", "")
            entry2 = rel.attrib.get("entry2", "")
            if entry1 not in entries or entry2 not in entries:
                continue
            src = entries[entry1]["label"]
            tgt = entries[entry2]["label"]
            subtypes = [st.attrib.get("name", "").lower() for st in rel.findall("subtype")]
            itype = InteractionType.ACTIVATION
            for st in subtypes:
                if st in _KEGG_RELATION_MAP:
                    itype = _KEGG_RELATION_MAP[st]
                    break
            weight = 0.5 if "indirect effect" in subtypes else 1.0
            relations.append(
                PathwayRelation(
                    source=src,
                    target=tgt,
                    interaction_type=itype,
                    weight=weight,
                    evidence="KEGG:" + (",".join(subtypes) if subtypes else rel.attrib.get("type", "")),
                    metadata={"entry1": entry1, "entry2": entry2, "subtypes": subtypes},
                    role="interaction",
                )
            )

        return PathwayMap(
            pathway_id=pathway_id,
            name=title,
            source_db="KEGG",
            nodes=nodes,
            relations=relations,
            reactions=reactions,
            metadata={
                "organism": org,
                "n_entries": len(entries),
                "n_reactions": len(reactions),
            },
        )


def _parse_coeff(raw: Optional[str]) -> float:
    if raw is None or raw == "":
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return value if value > 0.0 else 1.0


def reaction_to_relations(
    reaction: ReactionDefinition,
    *,
    evidence_prefix: str = "reaction",
) -> List[PathwayRelation]:
    """
    Expand a stoichiometric reaction into Phase-1-compatible directed edges.

    Edge policy
    -----------
    * substrate → product : ``CATALYSIS`` / transformation, coeffs on both ends
    * catalyst → product  : enzyme action (``CATALYSIS``), weight boosted
    * catalyst → substrate: binding / engagement (``BINDING``), weaker weight
    * If reversible, mirror substrate↔product edges at half weight
    """
    edges: List[PathwayRelation] = []
    evid = f"{evidence_prefix}:{reaction.name}"
    for sub in reaction.substrates:
        for prod in reaction.products:
            if sub.name == prod.name:
                continue
            edges.append(
                PathwayRelation(
                    source=sub.name,
                    target=prod.name,
                    interaction_type=InteractionType.CATALYSIS,
                    weight=1.0,
                    evidence=evid,
                    stoichiometry_source=sub.coefficient,
                    stoichiometry_target=prod.coefficient,
                    role="substrate_to_product",
                    metadata={
                        "reaction_id": reaction.reaction_id,
                        "reversible": reaction.reversible,
                        "matrix": dict(zip(*reaction.stoichiometry_matrix())),
                    },
                )
            )
            if reaction.reversible:
                edges.append(
                    PathwayRelation(
                        source=prod.name,
                        target=sub.name,
                        interaction_type=InteractionType.CATALYSIS,
                        weight=0.5,
                        evidence=evid + ":reverse",
                        stoichiometry_source=prod.coefficient,
                        stoichiometry_target=sub.coefficient,
                        role="substrate_to_product",
                        metadata={"reaction_id": reaction.reaction_id, "reverse": True},
                    )
                )
    for enz in reaction.catalysts:
        for prod in reaction.products:
            if enz.name == prod.name:
                continue
            edges.append(
                PathwayRelation(
                    source=enz.name,
                    target=prod.name,
                    interaction_type=InteractionType.CATALYSIS,
                    weight=1.2,
                    evidence=evid + ":enzyme",
                    stoichiometry_source=1.0,
                    stoichiometry_target=prod.coefficient,
                    role="catalysis",
                    metadata={
                        "reaction_id": reaction.reaction_id,
                        "enzyme_action": "produce",
                        "catalyst": enz.name,
                    },
                )
            )
        for sub in reaction.substrates:
            if enz.name == sub.name:
                continue
            edges.append(
                PathwayRelation(
                    source=enz.name,
                    target=sub.name,
                    interaction_type=InteractionType.BINDING,
                    weight=0.6,
                    evidence=evid + ":enzyme_substrate",
                    stoichiometry_source=1.0,
                    stoichiometry_target=sub.coefficient,
                    role="consumption",
                    metadata={
                        "reaction_id": reaction.reaction_id,
                        "enzyme_action": "engage_substrate",
                        "catalyst": enz.name,
                    },
                )
            )
    return edges


# ---------------------------------------------------------------------------
# Reactome
# ---------------------------------------------------------------------------


class ReactomeClient:
    """
    Reactome ContentService client with stoichiometric reaction expansion.

    Instead of chaining participants, reaction events are queried individually
    for ``input`` / ``output`` / ``catalystActivity`` sets and expanded via
    :func:`reaction_to_relations`.
    """

    BASE = "https://reactome.org/ContentService"
    NAMESPACE = "reactome"

    def __init__(
        self,
        http: Optional[AsyncHTTPClient] = None,
        *,
        cache: Optional[ResponseCache] = None,
        max_reactions: int = 40,
    ) -> None:
        if http is None:
            http = AsyncHTTPClient(rate=5.0, per=1.0, cache=cache, cache_namespace=self.NAMESPACE)
        else:
            if cache is not None and http.cache is None:
                http.cache = cache
        self.http = http
        self.max_reactions = max_reactions

    async def _get(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.http.get(url, cache_namespace=self.NAMESPACE, **kwargs)

    async def query_pathway(self, pathway_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE}/data/query/{quote(pathway_id)}"
        try:
            resp = await self._get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover
            logger.exception("Reactome query failed for %s: %s", pathway_id, exc)
            return None
        if resp.status != 200:
            logger.warning("Reactome %s → HTTP %s", pathway_id, resp.status)
            return None
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            logger.error("Reactome JSON decode failed: %s", exc)
            return None

    async def fetch_participants(self, pathway_id: str) -> List[str]:
        url = f"{self.BASE}/data/participants/{quote(pathway_id)}"
        try:
            resp = await self._get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover
            logger.exception("Reactome participants failed for %s: %s", pathway_id, exc)
            return []
        if resp.status != 200:
            logger.warning("Reactome participants %s → HTTP %s", pathway_id, resp.status)
            return []
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            return []
        names: List[str] = []
        if not isinstance(payload, list):
            return names
        for item in payload:
            if not isinstance(item, dict):
                continue
            display = item.get("displayName") or item.get("name")
            if isinstance(display, list):
                display = display[0] if display else None
            if display:
                cleaned = re.sub(r"^\d+x", "", str(display)).strip()
                token = cleaned.split()[0].split("[")[0]
                if token:
                    names.append(token)
        seen: Set[str] = set()
        ordered: List[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                ordered.append(n)
        return ordered

    async def fetch_pathway_events(self, pathway_id: str) -> List[Dict[str, Any]]:
        url = f"{self.BASE}/data/pathway/{quote(pathway_id)}/containedEvents"
        try:
            resp = await self._get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover
            logger.exception("Reactome events failed for %s: %s", pathway_id, exc)
            return []
        if resp.status != 200:
            logger.warning("Reactome events %s → HTTP %s", pathway_id, resp.status)
            return []
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    async def fetch_event_detail(self, st_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE}/data/query/{quote(st_id)}"
        try:
            resp = await self._get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover
            logger.exception("Reactome event detail failed for %s: %s", st_id, exc)
            return None
        if resp.status != 200:
            return None
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _entity_name(entity: Mapping[str, Any]) -> Optional[str]:
        display = entity.get("displayName") or entity.get("name")
        if isinstance(display, list):
            display = display[0] if display else None
        if not display:
            return None
        cleaned = re.sub(r"^\d+x", "", str(display)).strip()
        # Prefer gene name before compartment brackets: "EGFR [plasma membrane]"
        token = cleaned.split("[")[0].strip()
        # Multi-component complexes → keep first gene-like token
        token = token.split(":")[0].strip()
        return token or None

    @staticmethod
    def _entity_coeff(entity: Mapping[str, Any]) -> float:
        for key in ("stoichiometry", "coefficient", "stoichiometricCoefficient"):
            if key in entity:
                try:
                    value = float(entity[key])  # type: ignore[arg-type]
                    if value > 0:
                        return value
                except (TypeError, ValueError):
                    continue
        return 1.0

    def reaction_from_event(self, event: Mapping[str, Any]) -> Optional[ReactionDefinition]:
        """Convert a Reactome Reaction-like JSON object into stoichiometry."""
        schema = str(event.get("schemaClass") or "")
        if schema and "Reaction" not in schema and schema not in {"BlackBoxEvent", "Polymerisation", "Depolymerisation"}:
            # Still allow if inputs/outputs present
            if not (event.get("input") or event.get("output")):
                return None
        st_id = str(event.get("stId") or event.get("dbId") or event.get("displayName") or "")
        if not st_id:
            return None
        name = str(event.get("displayName") or st_id)
        substrates: List[StoichiometricSpecies] = []
        products: List[StoichiometricSpecies] = []
        for entity in event.get("input") or []:
            if not isinstance(entity, dict):
                continue
            label = self._entity_name(entity)
            if not label:
                continue
            substrates.append(
                StoichiometricSpecies(
                    name=label,
                    coefficient=self._entity_coeff(entity),
                    role="substrate",
                    entity_type=str(entity.get("schemaClass") or "Entity"),
                )
            )
        for entity in event.get("output") or []:
            if not isinstance(entity, dict):
                continue
            label = self._entity_name(entity)
            if not label:
                continue
            products.append(
                StoichiometricSpecies(
                    name=label,
                    coefficient=self._entity_coeff(entity),
                    role="product",
                    entity_type=str(entity.get("schemaClass") or "Entity"),
                )
            )
        catalysts: List[StoichiometricSpecies] = []
        for cat in event.get("catalystActivity") or []:
            if not isinstance(cat, dict):
                continue
            pe = cat.get("physicalEntity") or cat
            if not isinstance(pe, dict):
                continue
            label = self._entity_name(pe)
            if not label:
                continue
            catalysts.append(
                StoichiometricSpecies(
                    name=label,
                    coefficient=1.0,
                    role="catalyst",
                    entity_type="catalyst",
                )
            )
        if not substrates and not products:
            return None
        return ReactionDefinition(
            reaction_id=st_id,
            name=name,
            reversible=bool(event.get("isReversible") or False),
            substrates=substrates,
            products=products,
            catalysts=catalysts,
            metadata={"schemaClass": schema, "source": "Reactome"},
        )

    async def fetch_pathway_map(self, pathway_id: str) -> Optional[PathwayMap]:
        """
        Build a stoichiometry-aware Reactome pathway map.

        Falls back to participant listing (nodes only, no fake chain edges)
        when no reaction details are recoverable after retries/cache misses —
        leaving kinetic approximation to the ETL missingness layer.
        """
        meta = await self.query_pathway(pathway_id)
        events = await self.fetch_pathway_events(pathway_id)
        participants = await self.fetch_participants(pathway_id)

        reaction_events = [
            e
            for e in events
            if isinstance(e, dict)
            and (
                "Reaction" in str(e.get("schemaClass") or "")
                or e.get("input")
                or e.get("output")
            )
        ][: self.max_reactions]

        reactions: List[ReactionDefinition] = []
        relations: List[PathwayRelation] = []
        nodes: Dict[str, str] = {p: p for p in participants}

        for summary in reaction_events:
            st_id = str(summary.get("stId") or "")
            detail = summary
            # Contained-event payloads are often shallow — hydrate when needed
            if st_id and not (summary.get("input") or summary.get("output")):
                hydrated = await self.fetch_event_detail(st_id)
                if hydrated:
                    detail = hydrated
            reaction = self.reaction_from_event(detail)
            if reaction is None:
                continue
            reactions.append(reaction)
            for species in reaction.substrates + reaction.products + reaction.catalysts:
                nodes[species.name] = species.name
            relations.extend(reaction_to_relations(reaction, evidence_prefix="Reactome"))

        if not nodes and meta is None and not reactions:
            return None

        name = (meta or {}).get("displayName") or pathway_id
        return PathwayMap(
            pathway_id=pathway_id,
            name=str(name),
            source_db="Reactome",
            nodes=nodes,
            relations=relations,
            reactions=reactions,
            metadata={
                "n_events": len(events),
                "n_reactions_parsed": len(reactions),
                "event_names": [
                    str(e.get("displayName"))
                    for e in events[:50]
                    if isinstance(e, dict) and e.get("displayName")
                ],
                "stoichiometry": True,
            },
        )


# ---------------------------------------------------------------------------
# STRING
# ---------------------------------------------------------------------------


class STRINGClient:
    """STRING PPI client (JSON network endpoint) with SQLite caching."""

    BASE = "https://string-db.org/api"
    NAMESPACE = "string"

    def __init__(
        self,
        http: Optional[AsyncHTTPClient] = None,
        *,
        species: int = 9606,
        required_score: int = 400,
        cache: Optional[ResponseCache] = None,
    ) -> None:
        if http is None:
            http = AsyncHTTPClient(rate=5.0, per=1.0, cache=cache, cache_namespace=self.NAMESPACE)
        else:
            if cache is not None and http.cache is None:
                http.cache = cache
        self.http = http
        self.species = species
        self.required_score = required_score

    async def _get(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.http.get(url, cache_namespace=self.NAMESPACE, **kwargs)

    async def fetch_network(
        self,
        identifiers: Sequence[str],
        *,
        add_nodes: int = 0,
    ) -> List[PPIEdge]:
        if not identifiers:
            return []
        params = urlencode(
            {
                "identifiers": "%0d".join(identifiers),
                "species": str(self.species),
                "required_score": str(self.required_score),
                "add_nodes": str(max(0, add_nodes)),
                "caller_identity": "cistron",
            }
        )
        url = f"{self.BASE}/json/network?{params}"
        try:
            resp = await self._get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover
            logger.exception("STRING network fetch failed: %s", exc)
            return []
        if resp.status != 200:
            logger.warning("STRING network → HTTP %s", resp.status)
            return []
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            logger.error("STRING JSON decode failed: %s", exc)
            return []
        if not isinstance(payload, list):
            return []
        edges: List[PPIEdge] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            a = str(row.get("preferredName_A") or row.get("stringId_A") or "")
            b = str(row.get("preferredName_B") or row.get("stringId_B") or "")
            if not a or not b or a == b:
                continue
            # STRING scores are 0–1000
            raw_score = row.get("score")
            try:
                score = float(raw_score) / 1000.0 if raw_score is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            edges.append(
                PPIEdge(
                    protein_a=a,
                    protein_b=b,
                    score=score,
                    evidence="STRING",
                    directed=False,
                    metadata={k: row.get(k) for k in ("nscore", "fscore", "pscore", "ascore", "escore", "dscore", "tscore")},
                )
            )
        return edges

    def neighbourhood_weights(self, edges: Sequence[PPIEdge]) -> Dict[str, float]:
        """
        Mean incident STRING score per protein — used as a missingness prior.
        """
        buckets: Dict[str, List[float]] = {}
        for edge in edges:
            buckets.setdefault(edge.protein_a, []).append(edge.score)
            buckets.setdefault(edge.protein_b, []).append(edge.score)
        return {name: (sum(vals) / len(vals)) for name, vals in buckets.items() if vals}


# ---------------------------------------------------------------------------
# BioGRID
# ---------------------------------------------------------------------------


class BioGRIDClient:
    """
    BioGRID interaction client.

    When ``access_key`` is omitted the client operates in **offline / empty**
    mode and returns no edges (logged), so pipelines remain executable without
    credentials. Tab-delimited local exports can still be ingested via
    :meth:`parse_tab_export`.
    """

    BASE = "https://webservice.thebiogrid.org"

    def __init__(
        self,
        http: Optional[AsyncHTTPClient] = None,
        *,
        access_key: Optional[str] = None,
        organism: str = "9606",
    ) -> None:
        self.http = http or AsyncHTTPClient(rate=3.0, per=1.0)
        self.access_key = access_key
        self.organism = organism

    async def fetch_interactions(self, gene_list: Sequence[str]) -> List[PPIEdge]:
        if not gene_list:
            return []
        if not self.access_key:
            logger.info("BioGRID access_key not configured — returning no live edges")
            return []
        params = urlencode(
            {
                "accessKey": self.access_key,
                "format": "json",
                "geneList": "|".join(gene_list),
                "searchNames": "true",
                "includeInteractors": "true",
                "taxId": self.organism,
                "start": "0",
                "max": "10000",
            }
        )
        url = f"{self.BASE}/interactions/?{params}"
        try:
            resp = await self.http.get(url, headers={"Accept": "application/json"})
        except Exception as exc:  # pragma: no cover
            logger.exception("BioGRID fetch failed: %s", exc)
            return []
        if resp.status != 200:
            logger.warning("BioGRID → HTTP %s", resp.status)
            return []
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            logger.error("BioGRID JSON decode failed: %s", exc)
            return []
        edges: List[PPIEdge] = []
        if not isinstance(payload, dict):
            return edges
        for _, row in payload.items():
            if not isinstance(row, dict):
                continue
            a = str(row.get("OFFICIAL_SYMBOL_A") or "")
            b = str(row.get("OFFICIAL_SYMBOL_B") or "")
            if not a or not b or a == b:
                continue
            evid = str(row.get("EXPERIMENTAL_SYSTEM") or "BioGRID")
            # Map experimental systems onto soft confidence priors
            evid_l = evid.lower()
            if "affinity" in evid_l or "two-hybrid" in evid_l or "two hybrid" in evid_l:
                score = 0.7
            elif "genetic" in evid_l:
                score = 0.45
            else:
                score = 0.55
            edges.append(
                PPIEdge(
                    protein_a=a,
                    protein_b=b,
                    score=score,
                    evidence=f"BioGRID:{evid}",
                    directed=False,
                    metadata={"pubmed": row.get("PUBMED_ID"), "system": evid},
                )
            )
        return edges

    def parse_tab_export(self, text: str) -> List[PPIEdge]:
        """Parse a BioGRID TAB3 / MITAB-like local export (header required)."""
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        if not lines:
            return []
        header = lines[0].split("\t")
        idx = {name: i for i, name in enumerate(header)}
        # Flexible column resolution
        col_a = next((c for c in ("Official Symbol Interactor A", "OFFICIAL_SYMBOL_A", "BioGRID ID Interactor A") if c in idx), None)
        col_b = next((c for c in ("Official Symbol Interactor B", "OFFICIAL_SYMBOL_B", "BioGRID ID Interactor B") if c in idx), None)
        col_sys = next((c for c in ("Experimental System", "EXPERIMENTAL_SYSTEM") if c in idx), None)
        if col_a is None or col_b is None:
            logger.error("BioGRID tab export missing symbol columns")
            return []
        edges: List[PPIEdge] = []
        for line in lines[1:]:
            parts = line.split("\t")
            try:
                a = parts[idx[col_a]].strip()
                b = parts[idx[col_b]].strip()
            except IndexError:
                continue
            if not a or not b or a == b:
                continue
            evid = parts[idx[col_sys]].strip() if col_sys and idx[col_sys] < len(parts) else "BioGRID"
            edges.append(
                PPIEdge(
                    protein_a=a,
                    protein_b=b,
                    score=0.55,
                    evidence=f"BioGRID:{evid}",
                    directed=False,
                )
            )
        return edges


# ---------------------------------------------------------------------------
# Network materialisation
# ---------------------------------------------------------------------------


def pathway_map_to_network(
    pathway: PathwayMap,
    *,
    network: Optional[SignalingNetwork] = None,
    default_concentration: float = 0.1,
    min_weight: float = 0.05,
) -> SignalingNetwork:
    """
    Translate a :class:`PathwayMap` into a Phase 1 :class:`SignalingNetwork`.

    Edge metadata carries stoichiometric coefficients and enzyme roles when
    relations were produced by :func:`reaction_to_relations`:

    * ``stoichiometry_source`` / ``stoichiometry_target``
    * ``role`` ∈ {interaction, substrate_to_product, catalysis, consumption}
    * ``enzyme_action`` when applicable
    """
    net = network if network is not None else SignalingNetwork(name=pathway.name or pathway.pathway_id)
    name_to_id: Dict[str, str] = {}
    for entity in net.registry.entities():
        name_to_id[entity.name] = entity.entity_id
        name_to_id[entity.name.upper()] = entity.entity_id

    def ensure_node(label: str) -> str:
        if label in name_to_id:
            return name_to_id[label]
        upper = label.upper()
        if upper in name_to_id:
            return name_to_id[upper]
        protein = Protein(
            name=label,
            concentration=default_concentration,
            metadata={"source_db": pathway.source_db, "pathway_id": pathway.pathway_id},
        )
        net.add_node(protein)
        name_to_id[label] = protein.entity_id
        name_to_id[upper] = protein.entity_id
        return protein.entity_id

    for label in pathway.nodes:
        ensure_node(label)

    # Ensure reaction participants exist even if omitted from nodes dict
    for reaction in pathway.reactions:
        for species in reaction.substrates + reaction.products + reaction.catalysts:
            ensure_node(species.name)

    for rel in pathway.relations:
        if rel.weight < min_weight:
            continue
        src_id = ensure_node(rel.source)
        tgt_id = ensure_node(rel.target)
        if src_id == tgt_id:
            continue
        # Scale rate by stoichiometric magnitude (mass-action friendly prior)
        stoich_scale = max(rel.stoichiometry_source, rel.stoichiometry_target, 1.0)
        meta = {
            "evidence": rel.evidence,
            "role": rel.role,
            "stoichiometry_source": rel.stoichiometry_source,
            "stoichiometry_target": rel.stoichiometry_target,
            **rel.metadata,
        }
        net.connect(
            src_id,
            tgt_id,
            rel.interaction_type,
            weight=rel.weight * min(stoich_scale, 3.0),
            rate_constant=max(rel.weight * stoich_scale, 0.01),
            metadata=meta,
        )

    return net


def apply_ppi_edges(
    network: SignalingNetwork,
    edges: Sequence[PPIEdge],
    *,
    min_score: float = 0.4,
    interaction_type: InteractionType = InteractionType.BINDING,
    create_missing: bool = True,
) -> int:
    """
    Overlay PPI edges onto ``network``, using confidence scores as weights.

    Returns the number of edges added.
    """
    name_to_id: Dict[str, str] = {}
    for entity in network.registry.entities():
        name_to_id[entity.name] = entity.entity_id
        name_to_id[entity.name.upper()] = entity.entity_id

    def resolve(name: str) -> Optional[str]:
        if name in name_to_id:
            return name_to_id[name]
        if name.upper() in name_to_id:
            return name_to_id[name.upper()]
        if not create_missing:
            return None
        protein = Protein(name=name, concentration=0.1, metadata={"source": "PPI"})
        network.add_node(protein)
        name_to_id[name] = protein.entity_id
        name_to_id[name.upper()] = protein.entity_id
        return protein.entity_id

    added = 0
    for edge in edges:
        if edge.score < min_score:
            continue
        a = resolve(edge.protein_a)
        b = resolve(edge.protein_b)
        if a is None or b is None or a == b:
            continue
        network.connect(
            a,
            b,
            interaction_type,
            weight=edge.score,
            rate_constant=max(edge.score, 0.01),
            metadata={"evidence": edge.evidence, **edge.metadata},
        )
        added += 1
        if not edge.directed:
            network.connect(
                b,
                a,
                interaction_type,
                weight=edge.score,
                rate_constant=max(edge.score, 0.01),
                metadata={"evidence": edge.evidence, "mirror": True, **edge.metadata},
            )
            added += 1
    return added


def enrich_protein_from_uniprot(protein: Protein, record: UniProtRecord) -> Protein:
    """Copy UniProt annotations onto an existing Phase 1 protein (in-place)."""
    protein.sequence_length = record.length or protein.sequence_length
    protein.metadata["uniprot_accession"] = record.accession
    protein.metadata["domains"] = [d.__dict__ for d in record.domains]
    protein.metadata["active_sites"] = [d.__dict__ for d in record.active_sites]
    protein.metadata["sequence_preview"] = record.sequence[:50]
    if record.keywords:
        protein.is_enzyme = protein.is_enzyme or any(
            any(tok in k for tok in ("Kinase", "Hydrolase", "Catalytic", "Transferase"))
            for k in record.keywords
        )
    # Mild kinetic prior: longer proteins degrade slightly slower (very soft prior)
    if record.length and record.length > 0:
        deg = max(0.01, min(0.5, 50.0 / math.sqrt(float(record.length))))
        protein.kinetics = protein.kinetics.with_updates(degradation_rate=deg)
    return protein


class KnowledgeGraphService:
    """
    Facade composing all external clients for the ETL pipeline.

    A shared :class:`ResponseCache` backs UniProt / KEGG / STRING / Reactome
    lookups so repeated pathway builds do not thrash remote APIs.
    """

    def __init__(
        self,
        *,
        http: Optional[AsyncHTTPClient] = None,
        cache: Optional[ResponseCache] = None,
        biogrid_access_key: Optional[str] = None,
        string_species: int = 9606,
    ) -> None:
        self.cache = cache if cache is not None else ResponseCache()
        # Prefer per-client HTTP wrappers so cache namespaces stay isolated.
        # A caller-supplied ``http`` is reused only when it already carries a cache.
        if http is not None and http.cache is None:
            http.cache = self.cache
        self.http = http
        self.uniprot = UniProtClient(
            http if http is not None else None,
            cache=self.cache,
        )
        self.kegg = KEGGClient(
            http if http is not None else None,
            cache=self.cache,
        )
        self.reactome = ReactomeClient(
            http if http is not None else None,
            cache=self.cache,
        )
        self.string = STRINGClient(
            http if http is not None else None,
            species=string_species,
            cache=self.cache,
        )
        self.biogrid = BioGRIDClient(
            http if http is not None else AsyncHTTPClient(rate=3.0, per=1.0, cache=self.cache),
            access_key=biogrid_access_key,
        )

    async def build_kegg_network(self, pathway_id: str = "hsa04010") -> Optional[SignalingNetwork]:
        pathway = await self.kegg.fetch_pathway_map(pathway_id)
        if pathway is None:
            return None
        return pathway_map_to_network(pathway)

    async def build_reactome_network(self, pathway_id: str) -> Optional[SignalingNetwork]:
        pathway = await self.reactome.fetch_pathway_map(pathway_id)
        if pathway is None:
            return None
        return pathway_map_to_network(pathway)

    async def overlay_string(
        self,
        network: SignalingNetwork,
        gene_names: Optional[Sequence[str]] = None,
        *,
        min_score: float = 0.4,
    ) -> Tuple[SignalingNetwork, List[PPIEdge]]:
        if gene_names is None:
            gene_names = [e.name for e in network.registry.entities()]
        edges = await self.string.fetch_network(list(gene_names))
        apply_ppi_edges(network, edges, min_score=min_score, create_missing=False)
        return network, edges
