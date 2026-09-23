# Benchmark contract

NORTH-004 implements the lexical retrieval evaluation below. Its [run artifact](results/north-004-baseline.json) records local measurements; freshness, deletion-duration and end-to-end investigation benchmarks remain **NOT RUN**. The [initial targets](../docs/requirements/slo-sli.md) remain provisional.

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

Precision over returned results is the number of relevant results among the first up to five returned results divided by the number of results in that set, rather than a fixed denominator of five. NORTH-004 reports empty-result precision as null (N/A), with the macro denominator disclosed.

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


## NORTH-004 lexical retrieval run

Use the existing Python 3.12 environment from the repository root:

```bash
.venv/bin/python scripts/validate_dataset.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/evaluate_retrieval.py --repeats 10 --output /tmp/north-004-run.json
```

Choose a new output filename for each run. Its parent directory must exist.
Omit `--output` for JSON on stdout; fixture validation diagnostics use stderr.
The evaluator automatically creates and removes a fresh temporary SQLite database,
verifies the final snapshot, then executes all eight fixed questions ten times in
fixture order. No warm-up queries or samples are discarded; this is post-replay
storage with uncontrolled OS caches, not a cold-cache benchmark.

See [NORTH-004](../docs/requirements/NORTH-004.md) for exact tokenizer, score,
metric denominators, empty-result policy and latency boundaries. Quality aggregates
count seven positive cases once each; the no-evidence case is separate. Raw
`samples` preserve results, elapsed nanoseconds and errors for every attempt.
`cases` contain ranked results, misses, distractor hits and metrics. The report
includes reproduction inputs and source provenance; generated results are excluded
from its own source snapshot. Query errors and correctness violations fail the
command; relevance misses remain measured findings. No quality threshold is set.

The saved [baseline JSON](results/north-004-baseline.json) is evidence for this
small synthetic workload only. Repeated timings do not create additional independent
queries or establish production p95/p99 behavior. Lifecycle and restart behavior
are checked by regression tests, not by timed freshness probes in this runner.


### Recorded baseline observations

The saved run uses Python 3.12.13, 24 active documents and 80 sequential requests
(ten passes over eight questions). All 37 regression tests and dataset validation
passed. Dataset files, labels and checksums were unchanged.

| Measurement | Observed result |
| --- | --- |
| Macro required-evidence Recall@5 (7 positive cases) | 0.771429 |
| Macro precision@returned-count (7 positive cases) | 0.485714 |
| Complete required evidence | 4 / 7 cases |
| Known-distractor hits, positive cases | 3 |
| No-evidence empty-result behavior | 0 / 1 cases; five matches returned |
| Retrieval p50 / p95 / p99, including storage | 0.970259 / 1.525111 / 2.184359 ms |
| Query errors / reference or ranking correctness failures | 0 / 0 |

The observed p95 is below the provisional 250 ms target for this run only.
There are only eight distinct questions; these timings do not establish a
production tail-latency distribution.

Observed misses and failure modes:

- ACME-001 recovered two of five required documents, missing DEP-470, PR-1842 and
  INC-071. Matches such as `after`, `are` and `checkout` outrank essential evidence;
  inflections such as `payments` versus `payment` do not match.
- ACME-003 retrieved the deployment but missed PR-1842. Shared date, region and
  service tokens occupy the other result slots; retrieval does not follow the
  deployment's PR relationship.
- ACME-004 missed required diagnostic runbook RB-002. Other documents match more
  query tokens, while `timeouts` and `timeout` remain distinct.
- ACME-002 returned distractors INC-082 and INC-090; ACME-005 returned distractor
  SUP-301. Relevant vocabulary alone does not discriminate incident mechanisms.
- ACME-006 has no positive evidence but returns five results, including known
  distractors DEP-470 and SUP-301. Splitting timestamps and regions into tokens
  permits partial matches without enforcing the requested region/time.
- ACME-007 correctly returns restored SUP-303 v4, but four additional uncredited
  results reduce precision to 0.2. No stale or foreign version was returned.

These are findings of the fixed baseline. Labels, tokenizer and thresholds were
not tuned after inspecting the measurements. The run artifact captures source
provenance at execution time, before this observation summary was appended.
