"""Small, snapshot-reconciled CPU dense index; no optional imports at import time."""
from collections import OrderedDict
import json
import math
import time
from typing import Protocol

from services.processor.store import required_text
from .lexical import tokens

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'


class Encoder(Protocol):
    """One finite, nonzero, fixed-dimensional vector per input text."""
    def encode(self, texts: list[str]): ...


def validate_top_k(top_k):
    if type(top_k) is not int or top_k < 0:
        raise ValueError('top_k must be a nonnegative integer')


class SentenceTransformerEncoder:
    """Lazy pinned local-only model. Missing cache fails rather than downloading."""
    def __init__(self, model_id=MODEL, revision=REVISION):
        self.model_id, self.revision = model_id, revision
        self.model = None
        self.load_ns = 0

    def load(self):
        if self.model is None:
            started = time.perf_counter_ns()
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_id, revision=self.revision,
                                             device='cpu', local_files_only=True)
            self.load_ns = time.perf_counter_ns() - started

    def encode(self, texts):
        self.load()
        return self.model.encode(texts, normalize_embeddings=True,
                                 show_progress_bar=False, convert_to_numpy=True)


class SemanticRetriever:
    """Cache up to two requested tenants, each bounded by its active snapshot.

    Each index/search reconciles exact version and payload against one SQL
    snapshot. Changed rows are encoded in a batch; deleted rows are evicted.
    Least-recently-used tenants are evicted. Restart means an empty index.
    Calls are synchronous and intended for the Store's single-thread owner.
    """
    def __init__(self, store, encoder=None):
        self.store = store
        self.encoder = encoder if encoder is not None else SentenceTransformerEncoder()
        self._tenant = None
        self._cache = OrderedDict()
        self._entries = {}
        self._dimension = None
        self.last_timings = {}

    def _encode(self, texts):
        vectors = list(self.encoder.encode(texts))
        if len(vectors) != len(texts):
            raise ValueError('Encoder returned wrong batch size')
        normalized = []
        dimension = self._dimension
        for vector in vectors:
            values = tuple(float(v) for v in vector)
            if not values or not all(math.isfinite(v) for v in values):
                raise ValueError('Embedding must be finite and nonempty')
            if dimension is None:
                dimension = len(values)
            if len(values) != dimension:
                raise ValueError('Embedding dimension changed')
            norm = math.hypot(*values)
            if not math.isfinite(norm) or norm == 0:
                raise ValueError('Embedding must have finite nonzero norm')
            normalized.append(tuple(v / norm for v in values))
        self._dimension = dimension
        return normalized

    def index(self, tenant_id):
        required_text(tenant_id)
        started = time.perf_counter_ns()
        rows = self.store.documents(tenant_id)
        previous = self._cache.get(tenant_id, {})
        # Build separately: failed encoding must not change the published cache.
        valid = {r['document_id']: previous[r['document_id']] for r in rows
                 if r['document_id'] in previous and
                 previous[r['document_id']][0] == (r['source_version'], r['payload_json'])}
        changed = [r for r in rows if r['document_id'] not in valid]
        texts = []
        for row in changed:
            payload = json.loads(row['payload_json'])
            texts.append(payload['title'] + ' ' + payload['body'])
        vectors = self._encode(texts) if texts else []
        for row, vector in zip(changed, vectors):
            valid[row['document_id']] = ((row['source_version'], row['payload_json']), vector)
        cache = self._cache.copy()
        cache.pop(tenant_id, None)
        cache[tenant_id] = valid
        while len(cache) > 2:
            cache.popitem(last=False)
        self._cache, self._tenant, self._entries = cache, tenant_id, valid
        self.last_timings = {'index_update_ns': time.perf_counter_ns() - started,
                             'encoded_documents': len(changed)}
        return rows

    def search(self, tenant_id, query, *, top_k=5):
        required_text(tenant_id)
        validate_top_k(top_k)
        if not isinstance(query, str):
            raise ValueError('Query must be a string')
        self.last_timings = {}
        if not tokens(query) or top_k == 0:
            return []
        rows = self.index(tenant_id)
        if not rows:
            return []
        started = time.perf_counter_ns()
        vector = self._encode([query])[0]
        self.last_timings['query_embedding_ns'] = time.perf_counter_ns() - started
        started = time.perf_counter_ns()
        results = []
        for row in rows:
            embedding = self._entries[row['document_id']][1]
            results.append({'tenant_id': row['tenant_id'], 'document_id': row['document_id'],
                            'source_version': row['source_version'],
                            'title': json.loads(row['payload_json'])['title'],
                            'score': sum(a * b for a, b in zip(vector, embedding)),
                            'matched_tokens': []})
        results.sort(key=lambda r: (-r['score'], r['document_id']))
        self.last_timings['ranking_ns'] = time.perf_counter_ns() - started
        return results[:top_k]
