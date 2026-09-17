# NorthstarOps

NorthstarOps is a fictional B2B SaaS platform for enterprise incident investigation and technical support intelligence. This repository is explicitly a **production-simulation engineering project**, not a real employer, deployed product, or claim of production experience.

The planned system connects changing runbooks, service documentation, pull requests, incidents, support tickets, and deployment records. Metrics and raw logs belong behind future dedicated tools; they are not stored in the vector knowledge store.

Our first fictional tenant, AcmePay, operates a payment platform. In the representative incident, checkout-api v4.7 is deployed at 14:03, payment errors increase at 14:04, connection wait time rises at 14:05, support tickets arrive at 14:06, and an engineer requests an investigation at 14:07. A recent PR changed payment connection-pool configuration; a historical incident involved connection-pool exhaustion. These are leads to investigate, not proof of causation.

## Engineering approach

Technology follows an observed requirement or failure. The learning loop is:

requirement → naive baseline → production symptom → instrumentation → evidence → root cause → architecture change → benchmark → trade-off → next failure

Here, a production symptom means a simulated operational failure. Findings must include reproducible evidence and the limitations of the simulation.

## Current phase: NORTH-003

NORTH-001 established the planning baseline; NORTH-002 supplied the deterministic corpus. NORTH-003 implements local event validation and SQLite materialized document state. There is no retrieval, inference, or measured performance benchmark result.

With Python 3.12 active, run:

```bash
python scripts/validate_dataset.py
python -m unittest discover -v
python scripts/replay_events.py --dataset datasets/synthetic_enterprise --db /tmp/northstar-state.db --fresh
python scripts/replay_events.py --dataset datasets/synthetic_enterprise --db /tmp/northstar-state.db
```

The replay emits JSON outcomes, final state, and a manifest comparison. `--fresh` explicitly removes the chosen database and its SQLite sidecar files; omit it to resume existing state. Use a dedicated local database with no other process accessing it. No dependencies need installing.

- [Company and customer context](docs/product/company-context.md)
- [Engineering ticket](docs/requirements/NORTH-001.md)
- [Dataset ticket](docs/requirements/NORTH-002.md)
- [Local processor ticket and semantics](docs/requirements/NORTH-003.md)
- [Initial SLO/SLI targets](docs/requirements/slo-sli.md)
- [Proposed v0 architecture](docs/architecture/v0-baseline.md)
- [Synthetic dataset contract](datasets/synthetic_enterprise/README.md)
- [Benchmark contract](benchmarks/README.md)
- [Decision log](docs/architecture/decision-log.md)

## Local constraints and exclusions

The intended development machine runs Ubuntu 20.04 on an Intel i5-8265U with 20 GB RAM. Future implementation is CPU-first, using Python 3.12 via uv, with no reliable NVIDIA runtime. Compatibility and resource use have not been measured.

NORTH-001 installs no dependencies and implements no ingestion, storage, retrieval, workflows, inference, instrumentation, or benchmark runner. No datasets or models are downloaded or generated. No paid APIs or services are required; future local operation must have zero infrastructure cost.

Redis, Kafka, Qdrant, vLLM, LMCache, Kubernetes, Docker Compose, LangChain, and LangGraph are intentionally absent. Real-time ingestion, vector/hybrid retrieval, agentic workflows, operational state, observability/evaluation systems, KV caching, cache-aware routing, failure injection, and shadow model deployment remain possible later investigations, each requiring evidence and separate scope.
