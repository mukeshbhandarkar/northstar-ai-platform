# Lesson 03 measured retrieval comparison

## Original eight cases

| Mode | Recall@5 | Precision@5 | Complete | p50 / p95 / p99 ms | Load ms | Initial index ms |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| lexical | 0.7714 | 0.4857 | 4/7 | 2.551 / 3.194 / 9.323 | 0.0 | 0.0 |
| semantic | 0.9000 | 0.5429 | 5/7 | 27.027 / 35.327 / 246.755 | 12368.8 | 1271.3 |
| hybrid | 0.8286 | 0.5143 | 4/7 | 33.858 / 47.214 / 232.593 | 242.7 | 1262.1 |

## Exploratory paraphrases (three cases, inherited labels)

| Mode | Recall@5 | Precision@5 | Complete | p50 / p95 / p99 ms | Load ms | Initial index ms |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| lexical | 0.1667 | 0.2667 | 0/3 | 2.003 / 3.406 / 3.564 | 0.0 | 0.0 |
| semantic | 0.6333 | 0.4000 | 1/3 | 33.087 / 43.141 / 44.536 | 363.3 | 1411.0 |
| hybrid | 0.7333 | 0.4000 | 2/3 | 36.230 / 54.320 / 57.510 | 171.5 | 1162.3 |

Precision@5 uses five slots, including empty slots as zero credit. Recall and complete coverage use only positive cases. Legacy returned-count precision remains in JSON. Required labels and optional supporting labels are unchanged.

Each mode replays a fresh identical snapshot: 24 active versions. Ten repetitions are timing samples, not independent relevance cases. Nearest-rank p95/p99 from 80 original samples are descriptive, not a production tail estimate. First tenant (18 documents) is preindexed; second-tenant construction stays inside query latency. Model load includes library import in the first dense run; subsequent loads share process imports and OS caches.

## Ranked failure probes

### lexical
- ACME-001: SUP-301@1, ARCH-002@1, RB-001@1, SUP-303@4, ARCH-001@1; missing: DEP-470, PR-1842, INC-071
- ACME-003: DEP-470@1, SUP-301@1, DEP-460@1, INC-071@1, INC-090@1; missing: PR-1842
- ACME-004: RB-001@1, SUP-301@1, PR-1842@1, ARCH-001@1, ARCH-002@1; missing: RB-002
- ACME-006: DEP-201@1, DEP-470@1, DEP-460@1, SUP-301@1, ARCH-001@1; missing:
- Tenant/version or stability failures: 0; errors: 0; no-evidence empty results: 0/1.

### semantic
- ACME-001: SUP-301@1, INC-082@1, DEP-470@1, INC-071@1, RB-001@1; missing: PR-1842
- ACME-003: DEP-470@1, DEP-460@1, SUP-301@1, INC-071@1, PR-1830@1; missing: PR-1842
- ACME-004: RB-001@1, INC-071@1, RB-002@1, SUP-301@1, RB-003@1; missing:
- ACME-006: SUP-301@1, DEP-470@1, INC-082@1, DEP-201@1, DEP-460@1; missing:
- Tenant/version or stability failures: 0; errors: 0; no-evidence empty results: 0/1.

### hybrid
- ACME-001: SUP-301@1, RB-001@1, DEP-470@1, INC-082@1, INC-071@1; missing: PR-1842
- ACME-003: DEP-470@1, DEP-460@1, SUP-301@1, INC-071@1, PR-1830@1; missing: PR-1842
- ACME-004: RB-001@1, SUP-301@1, INC-071@1, PR-1842@1, ARCH-001@1; missing: RB-002
- ACME-006: DEP-470@1, DEP-201@1, SUP-301@1, DEP-460@1, INC-082@1; missing:
- Tenant/version or stability failures: 0; errors: 0; no-evidence empty results: 0/1.

## Stage timings (original samples)

| Mode | Stage | p50 ms | p95 ms | p99 ms |
| --- | --- | ---: | ---: | ---: |
| semantic | index_update_ns | 0.255 | 0.368 | 220.021 |
| semantic | query_embedding_ns | 25.356 | 33.086 | 39.715 |
| semantic | ranking_ns | 1.406 | 1.804 | 1.912 |
| hybrid | fusion_ns | 0.078 | 0.144 | 0.172 |
| hybrid | index_update_ns | 0.208 | 0.338 | 206.186 |
| hybrid | lexical_ns | 1.134 | 1.724 | 1.907 |
| hybrid | query_embedding_ns | 30.057 | 42.257 | 47.330 |
| hybrid | ranking_ns | 1.473 | 2.159 | 2.718 |

Raw samples, exact configuration, dependency versions, CPU, git status and source provenance accompany this report. No calibration, abstention policy, graph expansion or reranker is implemented.
