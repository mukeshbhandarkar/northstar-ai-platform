# NORTH-002: AcmePay Synthetic Enterprise Dataset and Investigation Ground Truth

Status: dataset, ground truth, and static validation delivered. No ingestion or retrieval implementation.

## Problem

The planning baseline has no concrete source artifacts or expected evidence against which future investigation experiments can be checked. Arbitrary text would make freshness, multi-tenancy, and correctness failures difficult to distinguish.

## Motivation

Create a miniature, inspectable enterprise with connected evidence, plausible competing explanations, and explicit version transitions. Preserve the NORTH-001 principle that later architecture changes require reproducible evidence rather than invented production claims.

## Scope

Deliver static JSON document payloads, an event-delivery fixture, a checksummed manifest and snapshot selection, separate investigation labels, a standard-library read-only validator, and dataset layout documentation. Follow the existing NORTH-001 metadata and event contracts without modifying its architecture or requirements.

## Non-goals

No ingestion API, materialization, database, retrieval, BM25, embeddings, RAG, agents, inference, model downloads, dependencies, services, or infrastructure. No Qdrant, Redis, Kafka, LangChain, LangGraph, vLLM, LMCache, Docker, Kubernetes, observability stack, load test, or benchmark runner. Do not begin NORTH-003.

## Dataset design

Use 24 logical documents: 18 AcmePay and six BetaShop, with four documents in each of the six established categories. AcmePay's checkout-api calls fraud-service and payment-api; payment-api uses provider-adapter. At 14:03 UTC on September 17, checkout-api v4.7 deploys in ap-south-1. PR-1842 reduces the per-worker payment-client ceiling from 48 to 8 with four workers unchanged. Support reports failures from 14:04, acquisition waiting at 14:05, and opens its ticket at 14:06.

The primary case at 14:07 requires a deployment, PR, historical pool-exhaustion incident, diagnostic runbook, and support ticket. Its conclusion is a supported hypothesis, not proof of causality. Provider-response failures, fraud-refresh latency, a receipt-only deployment, and an issuer decline provide realistic distractors. BetaShop has similar vocabulary and six colliding IDs, but its documents are never valid AcmePay evidence.

Use AcmePay SUP-303 for an independent lifecycle example: create v1, correct v2, delete v3, restore v4, with duplicate and stale deliveries. There are 26 complete payload versions, one tombstone, 33 deliveries, and 29 unique event IDs. The final snapshot lists one current version per logical document. Ground truth pins tenant/document/version references to that snapshot; distractors may deliberately reference old versions or another tenant.

Eight cases cover the primary incident, historical lookup, deployment change, diagnostics, an issuer-decline distractor, BetaShop isolation, missing evidence/abstention, and a restored support note. Fixed UTC times and static files avoid dependence on the machine clock. Seed 0 records that no random generation is used. See the [dataset layout](../../datasets/synthetic_enterprise/README.md) for exact file and label conventions.

## Acceptance criteria

- All six document categories are represented with concise, concrete artifacts and stable identities.
- The primary conclusion requires correlation across multiple documents and is qualified by missing live verification.
- BetaShop overlaps in terminology and identifiers but never appears in positive AcmePay evidence; the reverse isolation case is also represented.
- Required metadata, nine-field event envelopes, immutable payload references, and byte-level SHA-256 checksums follow NORTH-001.
- Fixture delivery order demonstrates create, update, exact duplicate, stale replay, deletion, duplicate deletion, stale replay after deletion, unseen stale events both before and after deletion, and a strictly newer restoration. The unseen probes must independently exercise version ordering rather than event-ID deduplication.
- Eight machine-readable cases resolve to existing document versions; an abstention case has no positive evidence.
- `python scripts/validate_dataset.py` passes without external dependencies. Disposable malformed fixture copies are rejected for checksum, schema/version, timestamp, reference, tenant, and event-category errors.
- `git diff --check` passes. No unrelated NORTH-001 architecture/requirements or implementation files are changed.

## Risks

The corpus is deliberately small and authored with known answers; it cannot establish general retrieval quality, production capacity, or realistic traffic performance. Similar vocabulary supplies plausible distractors but does not guarantee a lexical retriever will fail. A validator verifies fixture consistency, not causal truth or future ingestion behavior. Case conclusions remain human-authored labels. Tenant reference checks do not establish production authorization. Replay ordering and integer versions are synthetic-source assumptions already established by NORTH-001.

## Definition of done

Fixtures and documentation are inspectable; the validator and malformed-copy checks pass; counts and edge-case coverage are reported; whitespace checks pass; changed files and assumptions are listed. No benchmark results are claimed. Stop after data, ground truth, and validation are delivered.
