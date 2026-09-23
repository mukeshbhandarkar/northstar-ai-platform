# NORTH-004 controlled query-wording experiment

Run from the repository root with a new output path:

```bash
.venv/bin/python scripts/experiment_query_wording.py \
  --output /tmp/north-004-wording-repeat.json
```

The committed [experiment JSON](results/north-004-wording-experiment.json) records
every original and alternate query, ranked document/version, score, per-result
matched tokens, missing required evidence, coverage and precision. It also records
introduced query tokens that occur in labeled required documents. The runner
validates the existing dataset, replays it into a temporary SQLite database, uses
the existing Retriever and `score_case`, and refuses to run if original-query
rankings differ from the baseline or its saved SHA-256 differs. It never writes
the original baseline report.

The corpus snapshot (`north-002-v2`), labels, retriever, scoring definitions and
`top_k=5` were held fixed. Original rankings reproduce the saved baseline exactly.
This changes only query text within this finite experiment; the variants were
purposefully authored after inspecting the cases and are not independent evaluation
data. The terms listed as matching required documents are lexical overlap, not proof
of support.

## Results

Rankings below show document ID and overlap score; every result is v1 except
SUP-303 v4. Precision credits required and acceptable supporting evidence, divided
by returned count.

| Case / wording | Recall@5 | Precision | Complete required evidence | Top five (ID:score) | Missing required evidence |
|---|---:|---:|---|---|---|
| ACME-001 original | .4 | .6 | No | SUP-301:3, ARCH-002:2, RB-001:2, SUP-303:2, ARCH-001:1 | DEP-470, PR-1842, INC-071 |
| ACME-001 A — natural | .4 | .8 | No | DEP-460:4, INC-082:4, RB-001:4, SUP-301:4, ARCH-001:3 | DEP-470, PR-1842, INC-071 |
| ACME-001 B — explicit | .4 | .8 | No | ARCH-001:9, DEP-460:9, INC-071:9, PR-1842:9, PR-1830:8 | DEP-470, RB-001, SUP-301 |
| ACME-003 original | .5 | .4 | No | DEP-470:9, SUP-301:7, DEP-460:6, INC-071:6, INC-090:6 | PR-1842 |
| ACME-003 A — natural | .5 | .4 | No | DEP-470:9, DEP-460:7, INC-090:7, SUP-301:7, INC-071:6 | PR-1842 |
| ACME-003 B — explicit | 1.0 | .8 | Yes | PR-1842:15, DEP-470:13, DEP-460:12, ARCH-001:10, RB-001:9 | — |
| ACME-004 original | .5 | .6 | No | RB-001:9, SUP-301:7, PR-1842:6, ARCH-001:5, ARCH-002:5 | RB-002 |
| ACME-004 A — natural | 1.0 | .8 | Yes | RB-001:12, RB-003:10, ARCH-002:8, PR-1830:8, RB-002:8 | — |
| ACME-004 B — explicit | 1.0 | 1.0 | Yes | ARCH-002:11, RB-001:11, ARCH-001:9, RB-002:9, INC-082:8 | — |

A natural paraphrase changes ACME-001’s result set without recovering more required
evidence; it replaces two results with DEP-460 and INC-082. ACME-003 A changes the
ranking order but returns the same five IDs and the same metrics as the original.
ACME-003 B adds PR-1842 and reaches full required coverage. ACME-004 A and B both
add RB-002 and reach full coverage. These are observed query/result comparisons
under the fixed setup, not evidence that arbitrary paraphrasing improves retrieval.

## Required-evidence term overlap

The artifact lists every added token found in a required document and identifies the
document. Particularly direct overlap makes these variants exploratory:

- **ACME-001 A:** `failures` appears in required SUP-301; `payment` appears in all
  five required documents. **B:** terms including `v4`, `worker`, `pool`, `timeouts`,
  `acquisition`, `payment`, `client` and `api` occur in required documents. B also
  names the v4.7 rollout and distinctive connection-pool concepts.
- **ACME-003 A:** added `release` appears in required DEP-470 and PR-1842. **B:**
  directly includes both required IDs, `DEP-470` and `PR-1842`, the version, and
  `48-to-8 payment_client.pool.max_connections`; the token provenance is enumerated
  in the artifact. Its perfect coverage is therefore a prompted lookup, not an
  independent retrieval-quality estimate.
- **ACME-004 A:** added terms including `connection`, `response`, `waiting` and
  `upstream` appear in required runbooks. **B:** `acquire`, `adapter`, `deadlines`,
  `dispatch` and `response` overlap required-document text. It states the distinction
  using terminology present in the labeled evidence.

## Interpretation limits

The report directly establishes the exact query strings, token overlaps, rankings,
metrics and result-set changes. Because corpus, labels, retriever and scoring were
held constant, rankings differ for the recorded query strings. The technical
variants intentionally introduce evidence vocabulary, and all variants were
constructed for these known cases. This small, selected experiment cannot isolate a
general benefit of natural wording or establish behavior on unseen questions. Token
co-occurrence also does not establish that a returned document supports the query.
