"""
nouse.field.resonance_engine — FAISS-backed structural resonance search
=======================================================================

Bottleneck före: decompose() gör N × K KuzuDB-queries per resonanssökning.
  - 21k noder × 60 kandidater = 1 260 queries PER LEVEL
  - depth=3 × 10 principer × 3 levels = ~113 000 queries → ~336s i selftrain

Lösning (3 lager):
  1. build_index()  — EN batch-query hämtar alla signaturer till RAM
  2. query()        — FAISS ANN-sökning (sub-linjär) → top-K kandidater
  3. Exakt re-ranking — fullständig _resonance_score på top-K (inte hela grafen)

Backend-prioritering (automatisk):
  faiss-gpu  → CUDA tillgänglig + GPU-paket installerat
  faiss-cpu  → FAISS installerat, ingen GPU
  numpy      → alltid tillgänglig, ~10x långsammare men funkar alltid

Speedup (21k noder, K=20 resultat):
  Innan: 1 260 KuzuDB-queries ≈ 12–30s per sökning
  Efter: 1 batch build (3s en gång) + FAISS-sökning (< 1ms)
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from nouse.field.surface import FieldSurface

_log = logging.getLogger("nouse.resonance_engine")


# ── Resonans-helpers (samma logik som axon_growth_cone._resonance_score) ──────

def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _exact_resonance(
    q_sig: set[str],
    q_nb: set[str],
    c_sig: set[str],
    c_nb: set[str],
) -> tuple[float, list[str], list[str]]:
    """Exakt resonans: 0.65 × rel-typ Jaccard + 0.35 × grann-Jaccard."""
    score = round(0.65 * _jaccard(q_sig, c_sig) + 0.35 * _jaccard(q_nb, c_nb), 4)
    shared_rels = sorted(q_sig & c_sig)
    shared_nb = sorted(q_nb & c_nb)
    return score, shared_rels, shared_nb


# ── ResonanceEngine ────────────────────────────────────────────────────────────

class ResonanceEngine:
    """
    FAISS-baserad resonansskanner för NoUse-kunskapsgrafer.

    Användning::

        engine = ResonanceEngine(field)
        engine.build_index()          # bygg en gång (eller efter stora uppdateringar)

        results = engine.query(
            sig={"orsakar", "reglerar"},
            neighbors={"NMDA", "dopamin"},
            k=10,
            cross_domain_only=True,
            query_domain="neurovetenskap",
        )
        # → [(name, score, shared_rels, shared_neighbors), ...]
    """

    def __init__(self, field: "FieldSurface") -> None:
        self._field = field
        self._index = None                        # FAISS-index eller None
        self._node_names: list[str] = []
        self._node_sigs: list[set[str]] = []      # för exakt re-ranking
        self._node_neighbors: list[set[str]] = [] # för exakt re-ranking
        self._node_domains: list[str] = []
        self._rel_vocab: dict[str, int] = {}      # relationstyp → vektordimension
        self._dim: int = 0
        self._dirty: bool = True
        self._vectors: np.ndarray | None = None   # kopia för numpy-fallback
        self._backend: str = self._detect_backend()
        _log.info("ResonanceEngine initierad: backend=%s", self._backend)

    # ── Backend-detektering ────────────────────────────────────────────────

    @staticmethod
    def _detect_backend() -> str:
        try:
            import faiss  # noqa: F401
            return "faiss-gpu" if faiss.get_num_gpus() > 0 else "faiss-cpu"
        except ImportError:
            return "numpy"

    # ── Indexbygge ─────────────────────────────────────────────────────────

    def build_index(self) -> dict:
        """
        Batch-hämta alla nodsignaturer och bygg FAISS-index.

        EN KuzuDB-query ersätter N × K individuella queries.
        Returnerar stats-dict: {nodes, dim, relation_types, backend, build_ms}
        """
        t0 = time.monotonic()

        # 1. Batch-fetch: alla relationer i en KuzuDB-query
        rows = self._batch_fetch_all_relations()

        # 2. Bygg per-nod signaturmappar
        sigs: dict[str, set[str]] = {}
        neighbors: dict[str, set[str]] = {}
        domains: dict[str, str] = {}

        for row in rows:
            src = str(row.get("src") or "").strip()
            rel = str(row.get("rel_type") or "").strip().lower()
            tgt = str(row.get("tgt") or "").strip()
            dom = str(row.get("src_domain") or "external").strip()
            if not src or not rel:
                continue
            sigs.setdefault(src, set()).add(rel)
            neighbors.setdefault(src, set()).add(tgt)
            domains[src] = dom

        # Inkludera isolerade noder (inga utgående relationer)
        try:
            all_concepts = self._field.concepts()
            for row in all_concepts:
                name = str(row.get("name") or "").strip()
                dom = str(row.get("domain") or "external").strip()
                if name:
                    sigs.setdefault(name, set())
                    neighbors.setdefault(name, set())
                    domains.setdefault(name, dom)
        except Exception:
            pass

        if not sigs:
            _log.warning("ResonanceEngine: inga noder funna i grafen")
            self._dirty = False
            return {"nodes": 0, "dim": 0, "backend": self._backend, "build_ms": 0}

        # 3. Bygg relationstyp-vokabulär (sorterat för stabilitet)
        all_rel_types: set[str] = set()
        for sig in sigs.values():
            all_rel_types.update(sig)
        vocab = {rel: i for i, rel in enumerate(sorted(all_rel_types))}
        dim = max(1, len(vocab))

        # 4. Koda varje nod som float32-vektor (one-hot av relationstyper)
        node_names = sorted(sigs.keys())
        n = len(node_names)
        vecs = np.zeros((n, dim), dtype=np.float32)
        for i, name in enumerate(node_names):
            for rel in sigs[name]:
                j = vocab.get(rel)
                if j is not None:
                    vecs[i, j] = 1.0

        # L2-normalisera → inner product = cosine similarity
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs /= norms

        # 5. Bygg FAISS-index
        index = self._build_faiss_index(vecs)

        # 6. Lagra allt
        self._node_names = node_names
        self._node_sigs = [sigs[name] for name in node_names]
        self._node_neighbors = [neighbors[name] for name in node_names]
        self._node_domains = [domains.get(name, "external") for name in node_names]
        self._rel_vocab = vocab
        self._dim = dim
        self._index = index
        self._vectors = vecs
        self._dirty = False

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        stats = {
            "nodes": n,
            "relation_types": len(vocab),
            "dim": dim,
            "backend": self._backend,
            "build_ms": elapsed_ms,
        }
        _log.info(
            "ResonanceEngine index byggt: noder=%d dim=%d backend=%s tid=%dms",
            n, dim, self._backend, elapsed_ms,
        )
        return stats

    def _batch_fetch_all_relations(self) -> list[dict]:
        """Hämtar alla src→rel_type→tgt-tripplar."""
        try:
            return self._field.query_all_relations(include_domain=True)
        except Exception as e:
            _log.warning("Batch-fetch misslyckades: %s — faller tillbaka på per-nod", e)
            return self._per_node_fetch_fallback()

    def _per_node_fetch_fallback(self) -> list[dict]:
        """Per-nod fallback om batch-query misslyckas."""
        rows = []
        try:
            all_c = self._field.concepts()
            for c in all_c:
                name = str(c.get("name") or "").strip()
                dom = str(c.get("domain") or "external").strip()
                if not name:
                    continue
                try:
                    rels = self._field.out_relations(name)
                    for r in rels:
                        rows.append({
                            "src": name,
                            "rel_type": r.get("type", ""),
                            "tgt": r.get("target", ""),
                            "src_domain": dom,
                        })
                except Exception:
                    continue
        except Exception:
            pass
        return rows

    def _build_faiss_index(self, vecs: np.ndarray):
        """Välj och bygg bästa FAISS-index för given vektormatris."""
        if self._backend == "numpy":
            return None

        import faiss

        n, d = vecs.shape

        if n <= 2_000:
            # Brute force exakt: bäst för små grafer
            index = faiss.IndexFlatIP(d)
            index.add(vecs)

        elif n <= 100_000:
            # IVF med sqrt(n) centroids — bra balans hastighet/recall
            nlist = max(8, int(n ** 0.5))
            quantizer = faiss.IndexFlatIP(d)
            index = faiss.IndexIVFFlat(quantizer, d, nlist, faiss.METRIC_INNER_PRODUCT)
            # Träna på hela datamängden (eller subset om för stor)
            train_n = min(n, max(nlist * 40, 10_000))
            index.train(vecs[:train_n])
            index.nprobe = max(1, nlist // 4)
            index.add(vecs)

        else:
            # PQ-komprimering för mycket stora grafer (>100k noder)
            nlist = 256
            m = min(32, d // 2) if d >= 4 else 1
            quantizer = faiss.IndexFlatIP(d)
            index = faiss.IndexIVFPQ(quantizer, d, nlist, m, 8)
            index.train(vecs[:min(n, 50_000)])
            index.nprobe = 32
            index.add(vecs)

        # Flytta till GPU om tillgänglig
        if self._backend == "faiss-gpu":
            try:
                res = faiss.StandardGpuResources()
                index = faiss.index_cpu_to_gpu(res, 0, index)
                _log.info("FAISS-index flyttat till GPU")
            except Exception as e:
                _log.warning("GPU-flytt misslyckades (%s), använder CPU", e)
                self._backend = "faiss-cpu"

        return index

    # ── Sökning ────────────────────────────────────────────────────────────

    def query(
        self,
        sig: set[str],
        neighbors: set[str],
        *,
        k: int = 20,
        min_score: float = 0.0,
        exclude_names: set[str] | None = None,
        cross_domain_only: bool = False,
        query_domain: str | None = None,
        oversample: int = 5,
    ) -> list[tuple[str, float, list[str], list[str]]]:
        """
        Hitta top-k resonanta noder för en given signatur.

        Returnerar lista av (name, score, shared_rel_types, shared_neighbors)
        sorterad efter score fallande.

        Args:
            sig:               Relationstyp-signatur för frågenoden
            neighbors:         Grannkoncept för frågenoden
            k:                 Antal resultat att returnera
            min_score:         Lägsta resonanspoäng
            exclude_names:     Koncept att exkludera från resultat
            cross_domain_only: Returnera bara noder från annan domän
            query_domain:      Frågnodens domän (används med cross_domain_only)
            oversample:        FAISS hämtar k×oversample kandidater för re-ranking
        """
        if self._dirty or (self._index is None and self._backend != "numpy"):
            self.build_index()

        if not self._node_names:
            return []

        exclude = exclude_names or set()
        # Hämta fler kandidater för att kompensera för filtrering
        n_fetch = min(len(self._node_names), k * oversample + len(exclude) + 20)

        # FAISS- eller numpy-sökning (bara relationstyp-dimension)
        if self._backend != "numpy" and self._index is not None:
            candidate_indices = self._faiss_query(sig, n_fetch)
        else:
            candidate_indices = self._numpy_query(sig, n_fetch)

        # Exakt re-ranking med fullständig resonans (inkl. grann-Jaccard)
        results: list[tuple[str, float, list[str], list[str]]] = []
        for idx in candidate_indices:
            name = self._node_names[idx]
            if name in exclude:
                continue
            if cross_domain_only and query_domain:
                if self._node_domains[idx] == query_domain:
                    continue
            c_sig = self._node_sigs[idx]
            c_nb = self._node_neighbors[idx]
            score, shared_rels, shared_nb = _exact_resonance(sig, neighbors, c_sig, c_nb)
            if score < min_score:
                continue
            results.append((name, score, shared_rels, shared_nb))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]

    def _faiss_query(self, sig: set[str], k: int) -> list[int]:
        """FAISS-sökning: returnerar kandidatindex."""
        if not sig:
            # Tom signatur → returnera slumpmässiga kandidater
            return list(range(min(k, len(self._node_names))))

        vec = np.zeros((1, self._dim), dtype=np.float32)
        for rel in sig:
            j = self._rel_vocab.get(rel)
            if j is not None:
                vec[0, j] = 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm

        k_clamped = min(k, len(self._node_names))
        _D, I = self._index.search(vec, k_clamped)
        return [int(i) for i in I[0] if i >= 0]

    def _numpy_query(self, sig: set[str], k: int) -> list[int]:
        """Pure numpy-fallback: cosine similarity via matmul."""
        if self._vectors is None:
            return list(range(min(k, len(self._node_names))))

        vec = np.zeros(self._dim, dtype=np.float32)
        for rel in sig:
            j = self._rel_vocab.get(rel)
            if j is not None:
                vec[j] = 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm

        scores = self._vectors @ vec
        top_k = min(k, len(scores))
        top_indices = np.argpartition(scores, -top_k)[-top_k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        return [int(i) for i in top_indices]

    # ── Livscykel ──────────────────────────────────────────────────────────

    def invalidate(self) -> None:
        """Markera index som inaktuellt. Byggs om vid nästa query()."""
        self._dirty = True

    def is_built(self) -> bool:
        """True om index är byggt och aktuellt."""
        return not self._dirty and bool(self._node_names)

    def stats(self) -> dict:
        return {
            "nodes": len(self._node_names),
            "dim": self._dim,
            "backend": self._backend,
            "dirty": self._dirty,
        }
