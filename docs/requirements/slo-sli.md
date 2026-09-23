# Initial SLO/SLI targets

Every threshold below is a **TARGET**, chosen provisionally for a future local baseline. NORTH-004 records retrieval latency in a [local run artifact](../../benchmarks/results/north-004-baseline.json); other timed measurements remain **NOT RUN**. These are not customer commitments or achieved service levels.

Assumed evaluation window: one complete reproducible benchmark run on the documented CPU machine, at most 1,000 small documents, sequential ingestion, and one investigation at a time. Report actual sample counts and run duration; do not imply a monthly availability SLO. See the [benchmark contract](../../benchmarks/README.md).

| SLI | Measurement boundary | Initial TARGET | MEASURED RESULT |
| --- | --- | --- | --- |
| Knowledge freshness lag | Source commits an upsert → retrieval returns its exact tenant/document/version | p95 ≤ 5 seconds | NOT RUN |
| Retrieval latency | Valid retrieval request accepted → complete ranked result returned, including storage access | p95 ≤ 250 ms; report p50/p95/p99 | See NORTH-004 run artifact; eight synthetic queries, not service-level attainment |
| Deletion visibility | Source commits a delete → document is absent from all tested retrieval paths and remains absent during duplicate/stale replay unless a legitimate strictly newer upsert restores it | p95 ≤ 5 seconds; no resurrection by older events | NOT RUN |
| Duplicate-event tolerance | Replay an identical event ID/envelope/payload; compare materialized state and retrieval with a single-delivery control | Zero extra visible documents or state changes attributable to duplicates | NOT RUN |
| Tenant isolation | Query with tenant A context against mixed-tenant fixtures, including colliding document IDs | Zero foreign-tenant results, citations, or document payloads; missing tenant context rejected | NOT RUN |
| End-to-end investigation latency | Valid investigation request accepted → final response with citations and mock output returned | p95 ≤ 2 seconds | NOT RUN |

Investigation latency excludes prior ingestion; freshness is measured separately. Mock output makes the investigation target meaningful only for orchestration overhead, not real model latency. Isolation is a correctness invariant, not a probabilistic error budget; a single observed violation fails its target. Duplicate tolerance likewise requires all tested cases to pass.

For durations, use a monotonic clock in the local source/replay harness through observation. Stored UTC event times describe scenario chronology and must not be subtracted from wall-clock time for replay latency. Future distributed measurements will need a clock and skew policy.

Use a fixed, disclosed probe interval and deadline. Record visibility between the last failing and first passing probe; use the first passing probe as a conservative bound. Timeouts and errors must remain in the results, with counts and target failures, rather than being dropped from percentiles. Small samples cannot substantiate tail claims. Numeric targets may be revised only with a recorded reason and versioned comparison; a revised target does not retroactively make an earlier run pass.
