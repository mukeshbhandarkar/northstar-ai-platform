# NORTH-001: Establish the engineering baseline

Status: documentation baseline established; runtime validation not applicable to this ticket.

## Problem

The project needs an explicit product context, bounded first design, and measurement contracts before application or infrastructure choices can be evaluated.

## Motivation

Build reproducible engineering evidence through a requirement-to-failure learning loop. Avoid choosing technologies before identifying a requirement or observing a failure in the local simulation.

## Scope

Create the repository README, fictional company context, this ticket, initial SLO/SLI targets, proposed v0 architecture, future synthetic dataset contract, benchmark contract, and lightweight decision log. Create only directories containing these documents.

## Non-goals

No application code, dependency installation, dataset generation, model downloads, benchmark execution, or deployment. No Redis, Kafka, Qdrant, vLLM, LMCache, Kubernetes, Docker Compose, LangChain, LangGraph, paid APIs, GPU assumptions, or other infrastructure/framework additions. Do not implement telemetry tools, automated remediation, or later platform experiments.

## Acceptance criteria

- README states the fictional production-simulation purpose, AcmePay incident, learning loop, current phase, and exclusions.
- Company context identifies customers, engineering users, workflow, and explicitly labeled scale assumptions.
- SLO/SLI document defines six initial targets with measurement boundaries and no claimed measured results.
- v0 design covers synthetic source → ingestion boundary → processor → metadata/document storage → basic retrieval → explicit investigation workflow → mock inference → response.
- Dataset contract includes all six document types, six required metadata fields, and nine event envelope fields specified for this ticket.
- Benchmark contract covers freshness, deletion, retrieval percentiles, duplicates, isolation, correctness, and investigation latency, with reproducibility requirements.
- Decision log records the smallest-measurable-baseline decision and its trade-offs.
- Relative documentation links resolve; no runtime artifacts or dependencies are added.

## Risks

- Provisional targets may exceed the local machine's capacity; retain misses as evidence before revising targets.
- Synthetic data may overstate retrieval quality; include distractors, stale versions, and negative cases in later fixtures.
- Mock inference cannot establish real model quality, serving latency, or production readiness.
- Deferred concurrency and security implementation limit what the baseline can demonstrate.

## Open questions

- What measured workload should replace the provisional corpus size and sequential execution assumptions?
- How will real connectors provide ordering, immutable payload references, and authoritative deletion timestamps?
- What authentication and document-level authorization model is needed beyond a tenant boundary?
- What evidence should trigger a move beyond lexical retrieval or local storage?
- What real inference behavior, if any, should a later phase evaluate within CPU and cost constraints?

These questions do not block the documentation baseline; implementation requires a separately scoped ticket.

## Definition of done

All eight requested documents exist and agree on terminology, event semantics, exclusions, and target-versus-result status. Review links and required fields, confirm the change contains only documentation, and report assumptions, unresolved questions, and deliberate omissions. No runtime test or benchmark success is required or claimed for NORTH-001.
