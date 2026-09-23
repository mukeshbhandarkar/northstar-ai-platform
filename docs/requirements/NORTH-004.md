# NORTH-004: Deterministic Lexical Retrieval Baseline

## Problem and scope

Measure how much labeled evidence a simple lexical retriever recovers from the
NORTH-003 materialized state before considering embeddings. Implement local,
sequential, CPU-only Python 3.12 code using the standard library, regression
tests, and a reproducible JSON evaluation command. Preserve NORTH-002 revision
`north-002-v2`, its checksums, and all eight ground-truth cases unchanged.

No embeddings, vector database, LLM, Jev, external service, dependency installation,
HTTP API, investigation workflow, historical query API, or persistent search index.
No numerical quality acceptance threshold. Retrieval is evidence selection, not
causal reasoning or an answer-generation system.

## Retrieval interface

`Retriever(store).search(tenant_id, query)` returns a list of at most five objects
with `tenant_id`, `document_id`, `source_version`, `title`, integer `score`, and
sorted `matched_tokens`. Tenant context must be a nonempty string; a non-string
query raises `ValueError`. Empty, whitespace-only, and punctuation-only queries
return `[]`, after tenant validation. Unknown tenants and zero-overlap searches
also return `[]`. Storage errors propagate.

For nonempty tokenized queries, read `Store.documents(tenant_id)` once per call.
Its SQL predicates select the tenant and active current documents before scoring.
Parse each row's stored `payload_json`; never read historical payload files or
labels for retrieval. Text and returned identity/version come from that same row
snapshot. There is no cache to invalidate after updates, deletion, or restoration.
The existing single-process consistency boundary applies; tenant predicates do
not implement authentication or document-level authorization.

Tokenization applies Python `str.casefold()` then Unicode regular expression
`[^\W_]+`: letters and numbers form tokens; punctuation, hyphens, and underscores
separate them. Repeated tokens count once. Score is the cardinality of the
intersection of query tokens with the union of title and body tokens. Fields have
equal weight; no stopword removal, stemming, phrase matching, term-frequency or
inverse-document-frequency weighting. Return only positive scores, descending by
score and then ascending by document ID using Python Unicode string ordering.
Metadata is not independently searched; IDs present in title/body can match.

## Evaluation methodology

Validate the fixture inventory and labels, replay into a new temporary SQLite
database, and require exact manifest snapshot agreement before querying. All cases
use the fixed labeled snapshot; `as_of` is evaluation metadata, not a runtime
historical filter. Pass only tenant and question to the retriever.

Match labels by exact `(tenant_id, document_id, source_version)`:

- Required-evidence Recall@5: required references retrieved / required references.
- Precision@returned-count: returned references in required OR acceptable supporting
  evidence / actual returned count (at most five). Unlabeled results receive no
  credit, without claiming exhaustive irrelevance judgments. Empty precision is
  JSON `null` (N/A), excluded from the macro precision with its denominator reported.
- Complete required-evidence coverage: every required reference was retrieved.
  Optional evidence cannot substitute for required evidence.
- Known-distractor hits: exact matching references, reported per case and counted.
  Distractor lists are not exhaustive.
- No-evidence cases: recall and complete coverage are `null`; report empty-result
  behavior separately from positive-case aggregates. Precision is zero for nonempty
  output and `null` for empty output. Empty results are only a retrieval abstention
  proxy; positive lexical overlap does not establish answerability.

Report per-case ranked results, matched tokens, missing required references,
metrics, and every timing sample. Aggregate quality once per case, not once per
repeat. Positive-case recall and precision are macro averages with counts.
Foreign, stale, deleted or unknown result references and changed rankings across
repeats are correctness failures, distinct from ordinary relevance misses.

Measure `time.perf_counter_ns()` immediately around the complete search call,
including SQL access, JSON parsing, scoring, sorting and result construction.
Ingestion, label scoring, and report generation are outside retrieval latency.
Default: ten sequential passes over all eight cases, no warm-up queries, no
excluded samples. State is post-replay; OS caches are uncontrolled. No cold-cache
claim. Nearest-rank p50/p95/p99 use all attempts, with errored attempts occupying
infinity; estimates at infinity are `null` and explicitly censored. Preserve errors
and their elapsed times. No timeout deadline is enforced for synchronous calls.
Repeated queries do not create independent quality observations or substantiate
production tail latency. Compare the observed retrieval p95 to the existing
250 ms target; do not invent a quality gate. Freshness/deletion durations and
end-to-end investigation latency remain NOT RUN.

## Reproduction and artifacts

```bash
.venv/bin/python -m unittest tests.test_retrieval tests.test_evaluation -v
.venv/bin/python scripts/evaluate_retrieval.py --repeats 10 --output /tmp/north-004-run.json
```

Use an existing Python 3.12 interpreter if `.venv` is unavailable. The output must
be a new file outside the dataset; its parent must exist. Omit `--output` to emit
JSON on stdout. Validation messages go to stderr. A run automatically creates and
cleans a dedicated temporary database, without resetting user state. Output files
are never overwritten. Invalid input, replay failure, query errors or correctness
violations return nonzero; measured relevance misses are findings, not runner
errors. The report records latency target comparison without using it as a quality
gate or claiming a service-level guarantee.

Preserve invocation, run ID, Git revision/status/patch, untracked source contents,
manifest and hashes, event sequence, labels, corpus bytes/counts, algorithm settings,
repeat count, Python/SQLite/uv/OS/CPU/RAM information, process resource limits,
measurement CPU/wall durations, peak process RSS, raw samples and limitations.
Generated benchmark artifacts are excluded from provenance snapshots to avoid
recursive reports. Untracked source capture is limited to Python/Markdown under
services, scripts, tests and docs. Unknown environment information is null;
container limits are not inferred. Peak RSS covers the whole process, not just
retrieval. Results are local synthetic measurements, not enterprise capacity claims.

## Acceptance criteria

- Tenant filtering occurs before scoring; only active current rows are searchable.
- Ranking is deterministic, capped at five, positive-score only, with exact versions.
- Tests cover colliding tenant IDs, missing tenant context, ties, updates, deletion,
  restoration, duplicate/stale events, persistent restart, empty and zero-result
  queries, and independent hand-calculated metric cases.
- The eight unchanged cases produce an inspectable JSON report with misses,
  distractors, no-evidence behavior, raw timings and environment/provenance.
- Dataset validation, targeted tests, full existing suite and whitespace checks pass.
- Record measured lexical failures; do not modify labels or tune acceptance
  thresholds to make the baseline appear successful. Stop after validation.
