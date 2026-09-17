# Benchmark contract

No benchmarks have been implemented or run. **MEASURED RESULT: NOT RUN.** The [initial targets](../docs/requirements/slo-sli.md) are provisional requirements, not benchmark numbers.

## Required future measurements

| Measurement | Required observation |
| --- | --- |
| Source update → searchable | Source upsert commit to first query returning the exact latest tenant/document/version; report p50/p95/p99, count, and timeouts |
| Deletion → no longer retrievable | Source delete commit to absence from all exposed retrieval paths; verify continued absence after duplicate and stale replay unless a legitimate strictly newer upsert restores it |
| Retrieval latency | Request acceptance to complete ranked result; p50/p95/p99, errors, query count, and result count |
| Duplicate ingestion behavior | Compare state and retrieval against a single-delivery control, including duplicate deletes and restart/replay |
| Tenant-isolation violations | Count foreign-tenant results, citations, and payloads; exercise tenant ID collisions, adversarial queries, and missing context |
| Retrieval correctness | Recall@5 against versioned relevance labels, precision over returned results (up to 5; returned-count denominator), and no-evidence query behavior |
| End-to-end investigation latency | Accepted investigation request to final response, including retrieval, workflow, mock inference, and citation construction |

Precision over returned results is the number of relevant results among the first up to five returned results divided by the number of results in that set, rather than a fixed denominator of five. Empty-result scoring remains unspecified for a future ticket.

Correctness labels must identify expected tenant, document, and version plus required evidence relationships. For no-evidence queries, score abstention separately rather than assigning an undefined recall. Flag citations to deleted, stale, or foreign documents as correctness failures. No numerical quality target is set yet; establish and review the first labeled baseline before proposing one.

## Reproducible run record

Each future run must preserve:

- Git revision and dirty-state patch, dataset/schema version, file checksums, seed, event sequence, and expected-results manifest.
- OS, CPU, available RAM, Python and uv versions, dependency lock identity if dependencies are later introduced, and resource limits.
- Corpus bytes and counts by tenant/type, event counts, query set, concurrency, retrieval settings, and mock version.
- A complete invocation, configuration, storage reset procedure, warm-up policy, cold/warm designation, and repeat count.
- Raw timing samples and probe observations, errors/timeouts, correctness failures, and CPU/peak-memory observations alongside the summary.
- Target version, percentile calculation method, sample counts, and limitations. Use nearest-rank percentiles consistently and flag insufficient tail samples.

Use monotonic timestamps for the local live replay, not the historical `occurred_at` values. Disclose probe intervals/deadlines and visibility uncertainty. Report failures separately and count timed-out operations as target failures; never present a success-only percentile as the complete result. Define percentile treatment of incomplete samples in the run record and mark a percentile censored when those samples prevent a finite estimate.

Start from empty persisted state for independent runs. Run restart/replay cases as explicitly separate scenarios. Freeze the query set, fixture snapshot, seed, and load when comparing changes. Disclose warm-up exclusions before collecting results; do not discard slow samples after seeing them. Record deviations rather than silently changing the workload to meet a target.

An isolation pass means zero violations in the named tests, not proof of complete security. Mock inference timing does not predict real model serving. Local synthetic measurements do not establish production capacity or availability. Store future raw artifacts and summaries with a run identifier once a benchmark runner exists; NORTH-001 creates no empty result folders or invented results.
