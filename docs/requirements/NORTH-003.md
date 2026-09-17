# NORTH-003: Idempotent Local Event Processing and Materialized Document State

## Problem

The 33 NORTH-002 deliveries contain 29 event identities, including two previously unseen events for older document versions. Event-ID deduplication alone cannot maintain correct current state or prevent resurrection after deletion.

## Production motivation

Real change feeds can deliver duplicates and out-of-order updates. This production simulation tests those correctness mechanisms locally; it makes no claims about production capacity, security, latency, or SLO attainment.

## Scope and non-goals

Implement a single-process Python 3.12 standard-library processor, persistent SQLite state, tenant-scoped inspection methods, a JSON replay CLI, and unittest regression checks. No third-party dependencies.

No HTTP API, retrieval, BM25, embeddings, RAG, agents, inference, brokers, vector databases, external services, containers, orchestration, observability stack, or benchmark runner. Stop after NORTH-003. The NORTH-001/NORTH-002 dataset contracts and fixtures remain unchanged.

## Event identity versus document version

An event ID answers whether an envelope was previously accepted. Its canonical JSON representation includes every envelope field. Object key ordering does not affect identity; altered values do. Payload bytes are validated against SHA-256 before even a duplicate can be accepted.

A document is keyed by `(tenant_id, document_id)`. Its positive integer source version determines whether a validated change can replace current state. Tenant is part of every document key; source and creation timestamp remain immutable within a lineage. Version ordering is independent of event time and event identity.

Same-version content equality compares canonical parsed payload JSON plus event type, rather than JSON whitespace. The envelope still preserves the exact checksum and reference. A newer event identity carrying an identical observed version does not create another visible transition.

## State model

- `documents`: current source/version, deletion flag, payload reference/checksum, event occurrence time, document creation/update timestamps, and a stored JSON payload. Deleted rows hold the tombstone payload and remain excluded from active queries. Tombstones have no document `updated_at`; their deletion time is `occurred_at`. Creation time is retained if previously known.
- `events`: globally unique accepted event ID, canonical envelope, and initial processing outcome. Stale events and new IDs for identical versions are recorded, so their redelivery is idempotent. Invalid events are not recorded as accepted.
- `versions`: observed tenant/document/version, event type, source, creation time where available, and canonical payload. Retain older observations, including stale arrivals, to detect later conflicting content at an already observed version.

The small version history is needed because current state alone cannot identify a conflicting historical version. It has no compaction/retention policy in this baseline.

## Transaction boundary

Validate envelope shape, UTC times, nonempty identities, version, event type, payload path, UTF-8 JSON, required payload fields, checksum, identity/source/version agreement, and document timestamp ordering before mutation. Paths must resolve inside the dataset root, including symlink resolution. Duplicate JSON keys are rejected.

`Store.apply` opens `BEGIN IMMEDIATE` inside a SQLite transaction. It checks event identity, observed version conflicts, and lineage invariants; writes the current document if appropriate; records the version observation and accepted event; then commits. These operations are one transaction. Any exception rolls back all writes. Database failures propagate as errors, rather than being mislabeled as invalid source data. `Processor.process` is the validated entry point; `Store.apply` assumes validated inputs.

No network acknowledgment or distributed delivery guarantee is implied. The implementation assumes one local process with stable fixture files; it does not defend against concurrent hostile filesystem mutation.

## Processing outcomes

| Condition | Outcome | State and bookkeeping |
| --- | --- | --- |
| Unseen event, absent document or strictly newer version | `APPLIED` | Upsert current state or tombstone; record event/version |
| Previously accepted identical envelope | `DUPLICATE` | No writes |
| Reused event ID with different envelope | `INVALID` | No writes |
| Unseen ID, older nonconflicting version | `STALE` | Preserve current state/tombstone; record event/version |
| Unseen ID, same current version and identical content | `DUPLICATE` | Preserve current state; record new event identity |
| Conflicting content at any previously observed version | `INVALID` | No writes, even if that version is older than current |
| Invalid payload, reference, checksum, or lineage | `INVALID` | No writes |

Conflict validation precedes stale classification. Exact accepted event redelivery precedes document-version ordering, so a previously accepted stale event becomes `DUPLICATE` on replay. A delete for an unknown identity creates a tombstone. Only a strictly newer upsert restores visibility.

## Inspection API and replay

`Store.documents(tenant_id)` returns active current rows. `Store.get(tenant_id, document_id)` returns an active row or `None`. Both accept `include_deleted=True` for explicit tombstone inspection and put tenant predicates directly in SQL. Missing/empty tenant context is rejected. `processed_event_count()` and `has_event(event_id)` inspect local bookkeeping. `tenants()` lists names for administrative replay reporting, not document content.

```bash
python scripts/validate_dataset.py
python -m unittest discover -v
python scripts/replay_events.py --dataset datasets/synthetic_enterprise --db /tmp/northstar-state.db --fresh
python scripts/replay_events.py --dataset datasets/synthetic_enterprise --db /tmp/northstar-state.db
```

Use the existing `.venv/bin/python` if Python 3.12 is not the shell default. The CLI verifies fixture inventory checksums, processes events in array order, and emits JSON with all four outcome counts, invalid reasons, current document identities/versions/checksums, tenant counts, tombstone count, accepted event count, and manifest comparison. A mismatch or invalid delivery returns exit status 1. An invalid delivery is reported and replay continues; a database failure stops replay, leaving earlier event transactions committed.

Without `--fresh`, existing state is opened and retained. An unrelated database is rejected. With `--fresh`, the selected database and its journal/WAL/shared-memory sidecars are explicitly removed. Do not use this option against a database open elsewhere. A database path within the dataset or a symbolic-link database path is rejected.

The comparison checks exact final identity coverage, active state, payload content, version, source, reference, and checksum against `snapshot_payloads`. This fixture ends with all 24 documents active; temporary deletion must be checked during the lifecycle, not inferred from the final snapshot alone.

## Acceptance criteria

- Creates, updates, duplicates, conflicting event IDs, identical/conflicting versions, historical conflicts, deletion, unseen stale arrivals, and restoration have explicit verified outcomes.
- AcmePay/BetaShop colliding IDs remain isolated, with tenant filtering performed by SQL.
- A failure between document mutation and event insert rolls back document, version, and event changes; retry then succeeds.
- Full replay matches the manifest: 27 `APPLIED`, 4 `DUPLICATE`, 2 `STALE`, 0 `INVALID`; 18 AcmePay and 6 BetaShop active documents; zero final tombstones; 29 accepted event IDs.
- Reopening and replaying the same fixture yields 0 `APPLIED`, 33 `DUPLICATE`, 0 `STALE`, 0 `INVALID`, with identical visible state and event count.
- Dataset validator, full unittest suite, and whitespace checks pass; no fixture modifications or dependencies are introduced.

These counts are deterministic correctness observations, not benchmark/SLO results.

## Failure experiment

`test_experiment_event_id_only_resurrects_stale_content` creates a v3 tombstone and takes fixture delivery 32 (`evt-029`, unseen ID, v2 upsert). A deliberately broken, test-only simulation tracks only event IDs and makes v2 visible. The actual processor returns `STALE`, retains v3, and returns no active document. Broken logic is confined to the test.

## Risks and assumptions

The database uses signed 64-bit positive versions; values beyond SQLite's integer range are rejected explicitly. Timestamps describe source history, not local processing latency. The schema is version 1 with no migrations. Fixture revision changes require a fresh database, as documented by NORTH-002. The source can only detect conflicts against versions it has observed; no external source authority is implemented.

Version/event history grows without bounds and the per-document history check is intentionally simple. Tenant predicates are not authentication or authorization. A SQLite trigger test establishes transactional rollback on an injected statement failure, not exhaustive power-loss recovery. No concurrency, performance, distributed delivery, or security claims follow from these checks.

## Definition of done

The implementation, replay command, tests, and documentation exist; validation commands pass; fresh and repeated replay outcomes and manifest comparison are reported; the failure experiment and atomic rollback evidence are explicit. Stop before any retrieval or later-phase system work.
