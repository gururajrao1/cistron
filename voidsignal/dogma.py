"""
Central-dogma process engine for VOIDSIGNAL Phase 3.

Introduces deterministic transcriptional / translational latency and distinct
RNA vs protein clearance kinetics. Delay times τ scale with structural sequence
length from FASTA/GFF (nucleotides or amino acids).

Coupling
--------
:class:`CentralDogmaEngine` attaches to :class:`~voidsignal.simulation.MassActionRHS`.
On each RHS evaluation it:

1. Records instantaneous transcription / translation *intent* signals.
2. Injects production fluxes that were enqueued τ time units earlier.
3. Applies type-specific first-order degradation for RNA and protein pools.

Boolean mode uses a step-quantised delay (``ceil(τ / dt)``) before a Gene ON
state is allowed to force the downstream Protein Boolean ON.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import logging
import math

from voidsignal.components import EntityType, Gene, Protein, RNA
from voidsignal.topology import SignalingNetwork

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DogmaChain:
    """One Gene → RNA → Protein expression chain."""

    gene_id: str
    rna_id: str
    protein_id: str
    transcript_length_nt: int = 1000
    protein_length_aa: int = 333
    transcription_delay: float = 0.0
    translation_delay: float = 0.0
    rna_half_life: float = 2.0
    protein_half_life: float = 8.0

    def __post_init__(self) -> None:
        if self.transcript_length_nt < 1 or self.protein_length_aa < 1:
            raise ValueError("sequence lengths must be ≥ 1")
        if self.rna_half_life <= 0.0 or self.protein_half_life <= 0.0:
            raise ValueError("half-lives must be positive")


def delay_from_length(
    length: int,
    *,
    rate_per_unit: float,
    basal_delay: float = 0.05,
    max_delay: float = 50.0,
) -> float:
    """
    Deterministic latency τ = basal + length / polymerisation_rate.

    Parameters
    ----------
    rate_per_unit :
        Nucleotides (or amino acids) processed per simulation time unit.
    """
    if rate_per_unit <= 0.0:
        raise ValueError("rate_per_unit must be positive")
    tau = basal_delay + float(length) / rate_per_unit
    return min(max_delay, max(0.0, tau))


def degradation_rate_from_half_life(half_life: float) -> float:
    """First-order clearance ``k_deg = ln(2) / t½``."""
    if half_life <= 0.0:
        raise ValueError("half_life must be positive")
    return math.log(2.0) / half_life


class DelayLine:
    """
    Piecewise-constant delay buffer.

    Samples ``(t, value)`` are stored newest-last. Querying at time ``t``
    returns the value whose timestamp is the latest with ``timestamp ≤ t − τ``.
    """

    def __init__(self, delay: float, *, maxlen: int = 100_000) -> None:
        if delay < 0.0:
            raise ValueError("delay must be non-negative")
        self.delay = float(delay)
        self._buf: Deque[Tuple[float, float]] = deque(maxlen=maxlen)

    def push(self, t: float, value: float) -> None:
        if self._buf and t < self._buf[-1][0] - 1e-15:
            # Integrator stage re-entry at earlier t — do not corrupt history
            return
        if self._buf and abs(self._buf[-1][0] - t) < 1e-15:
            self._buf[-1] = (t, float(value))
        else:
            self._buf.append((t, float(value)))
        # Drop samples older than 2τ (+ margin) to bound memory
        horizon = t - max(2.0 * self.delay, 1.0) - 1.0
        while len(self._buf) > 2 and self._buf[0][0] < horizon:
            self._buf.popleft()

    def get(self, t: float, default: float = 0.0) -> float:
        if self.delay <= 0.0:
            return self._buf[-1][1] if self._buf else default
        target = t - self.delay
        if not self._buf or self._buf[0][0] > target:
            return default
        # Linear scan from the right (buffers are modest)
        value = default
        for ts, val in self._buf:
            if ts <= target + 1e-15:
                value = val
            else:
                break
        return value

    def clear(self) -> None:
        self._buf.clear()


@dataclass
class BooleanDelayState:
    """Step-quantised dogma delay for the Boolean engine."""

    protein_id: str
    remaining_steps: int = 0
    armed: bool = False


class CentralDogmaEngine:
    """
    Transcription / translation delay + type-specific degradation manager.
    """

    def __init__(
        self,
        network: SignalingNetwork,
        *,
        nt_per_time: float = 200.0,
        aa_per_time: float = 20.0,
        basal_transcription_delay: float = 0.1,
        basal_translation_delay: float = 0.05,
        default_rna_half_life: float = 2.0,
        default_protein_half_life: float = 10.0,
    ) -> None:
        self.network = network
        self.nt_per_time = nt_per_time
        self.aa_per_time = aa_per_time
        self.basal_transcription_delay = basal_transcription_delay
        self.basal_translation_delay = basal_translation_delay
        self.default_rna_half_life = default_rna_half_life
        self.default_protein_half_life = default_protein_half_life
        self.chains: List[DogmaChain] = []
        self._tx_lines: Dict[str, DelayLine] = {}
        self._tl_lines: Dict[str, DelayLine] = {}
        self._boolean_timers: Dict[str, BooleanDelayState] = {}
        self._suppress_direct_expression = True

    def discover_chains(self) -> List[DogmaChain]:
        """
        Auto-wire Gene↔RNA↔Protein links from registry cross-references and
        sequence lengths in metadata / typed fields.
        """
        chains: List[DogmaChain] = []
        genes = {e.entity_id: e for e in self.network.registry.entities() if isinstance(e, Gene)}
        rnas = {e.entity_id: e for e in self.network.registry.entities() if isinstance(e, RNA)}
        proteins = {e.entity_id: e for e in self.network.registry.entities() if isinstance(e, Protein)}

        for rna_id, rna in rnas.items():
            gene_id = rna.source_gene_id
            protein_id = rna.product_protein_id
            if gene_id is None or gene_id not in genes:
                continue
            if protein_id is None:
                # Infer protein by matching source_rna_id
                for pid, prot in proteins.items():
                    if getattr(prot, "source_rna_id", None) == rna_id:
                        protein_id = pid
                        break
            if protein_id is None or protein_id not in proteins:
                continue
            gene = genes[gene_id]
            prot = proteins[protein_id]
            nt = int(
                rna.metadata.get("linked_sequence_length")
                or rna.metadata.get("sequence_length")
                or max(3 * (prot.sequence_length or 300), 300)
            )
            aa = int(prot.sequence_length or max(nt // 3, 50))
            rna_hl = float(rna.metadata.get("half_life", getattr(rna, "half_life", self.default_rna_half_life)))
            prot_hl = float(
                prot.metadata.get("half_life", self.default_protein_half_life)
            )
            tx_delay = delay_from_length(
                nt, rate_per_unit=self.nt_per_time, basal_delay=self.basal_transcription_delay
            )
            tl_delay = delay_from_length(
                aa, rate_per_unit=self.aa_per_time, basal_delay=self.basal_translation_delay
            )
            chain = DogmaChain(
                gene_id=gene_id,
                rna_id=rna_id,
                protein_id=protein_id,
                transcript_length_nt=nt,
                protein_length_aa=aa,
                transcription_delay=tx_delay,
                translation_delay=tl_delay,
                rna_half_life=rna_hl,
                protein_half_life=prot_hl,
            )
            chains.append(chain)
            # Stamp derived delays onto entities for introspection
            gene.metadata["transcription_delay"] = tx_delay
            rna.metadata["transcription_delay"] = tx_delay
            rna.metadata["translation_delay"] = tl_delay
            prot.metadata["translation_delay"] = tl_delay
        self.chains = chains
        self._rebuild_buffers()
        self._apply_clearance_kinetics()
        logger.info("CentralDogmaEngine discovered %d expression chains", len(chains))
        return chains

    def add_chain(self, chain: DogmaChain) -> None:
        self.chains.append(chain)
        self._rebuild_buffers()
        self._apply_clearance_kinetics()

    def _rebuild_buffers(self) -> None:
        self._tx_lines = {
            c.rna_id: DelayLine(c.transcription_delay) for c in self.chains
        }
        self._tl_lines = {
            c.protein_id: DelayLine(c.translation_delay) for c in self.chains
        }
        self._boolean_timers = {
            c.protein_id: BooleanDelayState(protein_id=c.protein_id) for c in self.chains
        }

    def _apply_clearance_kinetics(self) -> None:
        """Set distinct RNA / protein degradation rates from half-lives."""
        for chain in self.chains:
            rna = self.network.registry.get(chain.rna_id)
            prot = self.network.registry.get(chain.protein_id)
            if isinstance(rna, RNA):
                rna.kinetics = rna.kinetics.with_updates(
                    degradation_rate=degradation_rate_from_half_life(chain.rna_half_life)
                )
            if isinstance(prot, Protein):
                prot.kinetics = prot.kinetics.with_updates(
                    degradation_rate=degradation_rate_from_half_life(chain.protein_half_life)
                )

    def reset(self) -> None:
        for line in self._tx_lines.values():
            line.clear()
        for line in self._tl_lines.values():
            line.clear()
        for timer in self._boolean_timers.values():
            timer.remaining_steps = 0
            timer.armed = False

    def chain_ids(self) -> Dict[str, Tuple[str, str, str]]:
        return {c.gene_id: (c.gene_id, c.rna_id, c.protein_id) for c in self.chains}

    def instantaneous_transcription_intent(
        self, chain: DogmaChain, conc: Mapping[str, float]
    ) -> float:
        gene = self.network.registry.get(chain.gene_id)
        if not isinstance(gene, Gene):
            return 0.0
        gate = 1.0 if gene.is_active else gene.kinetics.basal_activity
        gene_level = conc.get(chain.gene_id, gene.concentration)
        return (
            gene.transcription_rate
            * gene.promoter_strength
            * gate
            * (gene_level / (gene_level + 0.5))
        )

    def instantaneous_translation_intent(
        self, chain: DogmaChain, conc: Mapping[str, float]
    ) -> float:
        rna = self.network.registry.get(chain.rna_id)
        if not isinstance(rna, RNA) or not rna.is_coding:
            return 0.0
        return rna.translation_rate * max(conc.get(chain.rna_id, 0.0), 0.0)

    def apply_ode_contributions(
        self,
        t: float,
        conc: Mapping[str, float],
        dydt: Dict[str, float],
    ) -> None:
        """
        Record intents and inject delayed production into ``dydt``.

        Degradation is left to the baseline MassActionRHS first-order term that
        already reads ``entity.kinetics.degradation_rate`` (set from half-lives).
        """
        for chain in self.chains:
            tx_intent = self.instantaneous_transcription_intent(chain, conc)
            tl_intent = self.instantaneous_translation_intent(chain, conc)
            self._tx_lines[chain.rna_id].push(t, tx_intent)
            self._tl_lines[chain.protein_id].push(t, tl_intent)

            delayed_tx = self._tx_lines[chain.rna_id].get(t, 0.0)
            delayed_tl = self._tl_lines[chain.protein_id].get(t, 0.0)

            rna = self.network.registry.get(chain.rna_id)
            prot = self.network.registry.get(chain.protein_id)
            if chain.rna_id in dydt and not rna.locked:
                dydt[chain.rna_id] += max(0.0, delayed_tx)
            if chain.protein_id in dydt and not prot.locked:
                dydt[chain.protein_id] += max(0.0, delayed_tl)

    def skips_direct_expression(self, entity_id: str) -> bool:
        """True when MassActionRHS should not also apply immediate Gene→RNA/Protein."""
        if not self._suppress_direct_expression:
            return False
        for chain in self.chains:
            if entity_id in {chain.rna_id, chain.protein_id}:
                return True
        return False

    def boolean_step(self, dt: float) -> None:
        """
        Advance Boolean dogma timers by one simulation step of width ``dt``.

        When a Gene is ON, arm the delay for its Protein; after
        ``ceil((τ_tx + τ_tl) / dt)`` steps the Protein Boolean flips ON.
        """
        if dt <= 0.0:
            raise ValueError("dt must be positive")
        for chain in self.chains:
            gene = self.network.registry.get(chain.gene_id)
            prot = self.network.registry.get(chain.protein_id)
            timer = self._boolean_timers[chain.protein_id]
            total_delay = chain.transcription_delay + chain.translation_delay
            steps_needed = max(1, int(math.ceil(total_delay / dt))) if total_delay > 0 else 0
            if gene.is_active:
                if not timer.armed:
                    timer.armed = True
                    timer.remaining_steps = steps_needed
                elif timer.remaining_steps > 0:
                    timer.remaining_steps -= 1
                if timer.remaining_steps <= 0 and not (
                    prot.locked and prot.metadata.get("lock_boolean")
                ):
                    prot.set_boolean(True)
            else:
                timer.armed = False
                timer.remaining_steps = 0


def build_dogma_from_lengths(
    network: SignalingNetwork,
    length_map: Mapping[str, int],
    *,
    gene_rna_protein: Sequence[Tuple[str, str, str]],
    **engine_kwargs: float,
) -> CentralDogmaEngine:
    """
    Convenience builder: ``length_map`` keyed by entity name/id supplies nt or aa.
    """
    engine = CentralDogmaEngine(network, **engine_kwargs)  # type: ignore[arg-type]
    name_to_id = {}
    for ent in network.registry.entities():
        name_to_id[ent.name] = ent.entity_id
        name_to_id[ent.entity_id] = ent.entity_id
    for gene_k, rna_k, prot_k in gene_rna_protein:
        gid = name_to_id[gene_k]
        rid = name_to_id[rna_k]
        pid = name_to_id[prot_k]
        rna = network.registry.get(rid)
        prot = network.registry.get(pid)
        nt = int(length_map.get(rna_k) or length_map.get(rid) or 1000)
        aa = int(length_map.get(prot_k) or length_map.get(pid) or max(nt // 3, 50))
        if isinstance(prot, Protein) and prot.sequence_length is None:
            prot.sequence_length = aa
        if isinstance(rna, RNA):
            rna.metadata["sequence_length"] = nt
            rna.source_gene_id = gid
            rna.product_protein_id = pid
        if isinstance(prot, Protein):
            prot.source_rna_id = rid
        if isinstance(network.registry.get(gid), Gene):
            getattr(network.registry.get(gid), "expressed_rna_id", None)
            gene = network.registry.get(gid)
            if isinstance(gene, Gene):
                gene.expressed_rna_id = rid
        engine.add_chain(
            DogmaChain(
                gene_id=gid,
                rna_id=rid,
                protein_id=pid,
                transcript_length_nt=nt,
                protein_length_aa=aa,
                transcription_delay=delay_from_length(nt, rate_per_unit=engine.nt_per_time),
                translation_delay=delay_from_length(aa, rate_per_unit=engine.aa_per_time),
            )
        )
    engine._apply_clearance_kinetics()
    return engine
