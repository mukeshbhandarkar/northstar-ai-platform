# Decision log

Record a decision when a requirement or measured failure justifies it. Include context, alternatives, consequences, evidence links, and the condition for revisiting it. This lightweight log is sufficient for the planning phase.

## D-001 — Start with the smallest measurable baseline; infrastructure must be justified by evidence.

- Status: accepted for NORTH-001 planning.
- Context: a fictional production simulation on a CPU-only, resource-limited development machine needs reproducible evidence before selecting infrastructure.
- Decision: document the contracts first, then propose a local sequential baseline with basic retrieval and mock inference in a separately scoped implementation ticket. Add infrastructure only in response to an observed requirement or failure.
- Alternative considered: build brokers, vector storage, distributed workflow orchestration, and model serving immediately. This introduces operational cost and multiple variables before a baseline exists.
- Consequences: smaller future experiments and zero required infrastructure spend; limited realism, concurrency, semantic retrieval, and inference capability. Those limitations must be stated with results.
- Evidence: the [NORTH-001 requirements](../requirements/NORTH-001.md) and development constraints motivate this decision. There is no runtime benchmark evidence yet.
- Revisit when: a reproducible benchmark or concrete requirement shows the baseline cannot meet an agreed target, and a proposed change can be compared under controlled conditions.

Future entries: identifier, decision, status, context, alternatives, consequences, evidence, and revisit condition.


## D-002 — Measure uncached token overlap over materialized current state

- Status: accepted for NORTH-004.
- Context: NORTH-003 provides tenant-filtered current documents and NORTH-002 supplies eight versioned evidence cases. Lesson 02 needs a reproducible retrieval measurement before embeddings.
- Decision: read active rows through `Store.documents(tenant_id)` per query; rank distinct title/body token overlap with stable document-ID ties and a five-result cap. Evaluate required coverage separately from supporting-evidence precision.
- Alternatives considered: persistent lexical index, BM25, embeddings and vector storage. These add synchronization or scoring choices before the simplest baseline has been measured.
- Consequences: no index invalidation path; linear scans, no semantic matching or answerability reasoning, common-token and document-length bias. Tenant predicates remain distinct from authorization.
- Evidence: [NORTH-004 contract](../requirements/NORTH-004.md), retrieval regression tests, and [baseline evaluation](../../benchmarks/results/north-004-baseline.json).
- Revisit when: recorded misses or latency at a disclosed workload justify a controlled comparison with a stronger retriever. Keep the query set, labels and snapshot fixed.
