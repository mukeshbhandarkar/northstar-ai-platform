"""Rank-only RRF over a shared tenant snapshot; missing ranks contribute zero."""
import math
import time
from .lexical import Retriever, tokens
from .semantic import SemanticRetriever, validate_top_k
from services.processor.store import required_text


def identity(row):
    return row['tenant_id'], row['document_id'], row['source_version']


def fuse(lists, *, rrf_k=60, top_k=5):
    validate_top_k(top_k)
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, (int, float)) or not math.isfinite(rrf_k) or rrf_k <= 0:
        raise ValueError('rrf_k must be finite and positive')
    rows, scores = {}, {}
    for results in lists:
        seen = set()
        for rank, row in enumerate(results, 1):
            key = identity(row)
            if key in seen:
                raise ValueError('Duplicate identity in candidate list')
            seen.add(key)
            rows.setdefault(key, row)
            scores[key] = scores.get(key, 0) + 1 / (rrf_k + rank)
    return [{**rows[key], 'score': scores[key]} for key in
            sorted(rows, key=lambda key: (-scores[key], key))[:top_k]]


class HybridRetriever:
    def __init__(self, store, encoder=None, *, rrf_k=60, candidate_depth=20):
        validate_top_k(candidate_depth)
        if candidate_depth == 0:
            raise ValueError('candidate_depth must be positive')
        fuse([], rrf_k=rrf_k)
        self.store = store
        self.semantic = SemanticRetriever(store, encoder)
        self.rrf_k, self.candidate_depth = rrf_k, candidate_depth
        self.last_timings = {}

    def search(self, tenant_id, query, *, top_k=5):
        required_text(tenant_id)
        validate_top_k(top_k)
        self.last_timings = {}
        if not isinstance(query, str):
            raise ValueError('Query must be a string')
        if not tokens(query) or top_k == 0:
            return []
        # Read both candidate lists within the same SQLite read transaction.
        # SAVEPOINT also supports callers already inside a transaction.
        self.store.connection.execute('SAVEPOINT retrieval_snapshot')
        try:
            snapshot = {identity(row) for row in self.store.documents(tenant_id)}
            started = time.perf_counter_ns()
            lexical = Retriever(self.store).search(tenant_id, query, top_k=self.candidate_depth)
            lexical_ns = time.perf_counter_ns() - started
            dense = self.semantic.search(tenant_id, query, top_k=self.candidate_depth)
            for candidates in (lexical, dense):
                if any(identity(row) not in snapshot for row in candidates):
                    raise ValueError('Candidate outside requested tenant active snapshot')
            started = time.perf_counter_ns()
            results = fuse([lexical, dense], rrf_k=self.rrf_k, top_k=top_k)
            self.last_timings = {**self.semantic.last_timings, 'lexical_ns': lexical_ns,
                                 'fusion_ns': time.perf_counter_ns() - started}
            return results
        finally:
            self.store.connection.execute('RELEASE SAVEPOINT retrieval_snapshot')
