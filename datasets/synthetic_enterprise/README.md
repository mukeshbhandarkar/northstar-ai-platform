# Synthetic enterprise dataset

NORTH-001 established this contract without generating data. NORTH-002 now supplies small, deterministic UTF-8 JSON fixtures under the unchanged contract. All entities, incidents, and customer content are fictional. The local ceiling remains at most 1,000 small documents across AcmePay and one isolation-test tenant; this is a design assumption, not production scale.

## Concrete NORTH-002 layout

- `payloads/acmepay/`: 18 document identities; SUP-303 additionally has versions 2 and 4 and a version 3 delete tombstone.
- `payloads/betashop/`: six document identities, one of each document type. All six IDs intentionally collide with AcmePay IDs; identity always includes the tenant.
- `manifest.json`: dataset/schema versions, seed, complete fixture-file SHA-256 inventory, snapshot payload list, and one-based event scenario positions.
- `events.json`: ordered array of 31 delivery envelopes representing 27 distinct events. Payload references are relative to this directory.
- `ground_truth.json`: eight investigation cases, kept separate from source documents and never supplied as retrieval corpus content.

There are 24 logical documents (four per category), 26 complete document-version payloads, and one tombstone. Do not count versions or the tombstone as additional logical documents. The `snapshot_payloads` list is the authoritative corpus selection for the labeled snapshot; recursively loading every payload would incorrectly include superseded versions and a tombstone.

Every normal payload uses exactly the six metadata fields below plus `document_type`, `title`, and `body`. Tombstones use only `tenant_id`, `document_id`, `source`, and `source_version`. JSON is UTF-8 with two-space indentation and a final newline; checksums cover the exact saved bytes. The manifest inventories payloads, events, and labels, not itself or documentation.

The snapshot is fixed at **2026-09-17T14:07:00Z**. “Today” in a case refers to that synthetic UTC date, not execution time. AcmePay's primary rollout is in ap-south-1. Reported symptoms are authored support observations, not raw logs, metrics, or verified live telemetry. The intended scenario cause is held in ground truth with appropriately qualified conclusions, while source documents distribute the supporting evidence across artifacts.

The fixtures are hand-authored and static; seed `0` is a recorded reproducibility marker and no random sampling is performed. Reproduce them from the repository revision and verify the manifest, rather than generating new prose. Enterprise design assumptions do not describe this dataset's measured scale. No performance benchmark has been run.

### Event sequence and snapshot

Deliveries 1–24 create each tenant/document at version 1. The remaining deliveries exercise AcmePay SUP-303: v2 update (25), exact v2 duplicate (26), stale v1 replay (27), v3 delete (28), duplicate delete (29), stale v2 replay after deletion (30), and legitimate v4 restoration (31). Replayed deliveries preserve the entire envelope, including event ID and original occurrence time.

Array order is fixture delivery order; it is deliberately not global occurrence-time order. Events across independent documents may arrive out of order. The snapshot selects the highest accepted version for each identity after the full fixture, including restored SUP-303 v4. Check absence immediately after deletion and stale replay in future ingestion tests, before the legitimate restoration. This file is a fixture, not an ingestion implementation.

### Investigation labels

Each case contains `case_id`, `tenant_id`, `as_of`, `question`, `expected_evidence`, `acceptable_supporting_evidence`, `known_distractors`, `expected_conclusion`, and `abstain`. Every evidence reference is an object with `tenant_id`, `document_id`, and `source_version`.

`expected_evidence` identifies required evidence; `acceptable_supporting_evidence` lists optional useful context. Neither list may cross the case's tenant boundary or cite a superseded snapshot version. `known_distractors` is a non-exhaustive list of misleading matches and may intentionally cite another tenant or an older version; it never authorizes using that content as evidence. An abstention case has no positive evidence.

Cases cover the primary incident (five required sources), historical lookup, deployment/change analysis, safe diagnostics, issuer-decline discrimination, BetaShop isolation, an unsupported region/time question, and the corrected/restored support note. Case labels do not define a new ranking metric or claim that retrieval has succeeded.

### Validation

From the repository root, run `python scripts/validate_dataset.py` using the intended Python 3.12 environment (or `.venv/bin/python scripts/validate_dataset.py` when that interpreter already exists). No packages or services are required. `--dataset-root PATH` supports validating a separate fixture copy.

The validator reads files only. It checks schemas, tenant/version identity, UTC timestamps, stable lineage metadata, file inventory and hashes, event/payload agreement, declared replay edge cases, snapshot references, case references, and tenant boundaries for positive evidence. It exits nonzero on invalid fixtures. It does not prove causal truth, retrieval quality, ingestion correctness, or isolation of a future application. Invalid-checksum rejection can be checked on a disposable copy; the committed event fixture contains valid envelopes only.

## Document types

| Type | Intended evidence |
| --- | --- |
| `runbook` | Investigation and verification procedures for payment failures |
| `architecture_doc` | checkout-api dependencies and connection-pool behavior |
| `incident` | Historical pool exhaustion, timeline, findings, and resolution |
| `pull_request` | Payment connection-pool configuration change and release association |
| `support_ticket` | Customer-reported errors and impact |
| `deployment` | checkout-api v4.7 deployment, service, time, and related changes |

Each normal document payload includes `document_type`, a title, text body, and the required metadata below. Delete tombstone payloads are exempt from these complete-document requirements and use the tombstone fields specified in the event-envelope section. Explicit relationships to PRs, deployments, or services should use fixture-defined identifiers. Do not store raw logs or metrics; authored summaries may refer to reported symptoms without pretending to provide live telemetry.

## Required document metadata

| Field | Contract |
| --- | --- |
| `tenant_id` | Nonempty stable tenant identifier; immutable for a document |
| `document_id` | Nonempty identifier unique within a tenant; stable across source updates |
| `source` | Stable synthetic connector/source name; owning source does not change within a document lineage |
| `source_version` | Positive integer increasing per tenant/document, including deletes; synthetic ordering assumption |
| `created_at` | UTC RFC 3339 creation timestamp, preserved across updates |
| `updated_at` | UTC RFC 3339 source update timestamp; no earlier than creation |

The storage identity is `(tenant_id, document_id)`; source names must not create accidental duplicate identities. The fixture manifest controls document ID assignment. Timestamp order alone does not determine version order.

## Future event envelope

| Field | Contract |
| --- | --- |
| `event_id` | Globally unique nonempty synthetic event identifier; unchanged on redelivery |
| `tenant_id` | Tenant owning the affected document |
| `source` | Owning source, matching the document lineage |
| `document_id` | Stable document identifier within the tenant |
| `source_version` | Positive integer version of this change, including deletion |
| `event_type` | `upsert` or `delete` |
| `occurred_at` | UTC RFC 3339 source change time; distinct from replay time |
| `payload_ref` | Dataset-relative path to an immutable UTF-8 payload file within the dataset root |
| `checksum` | SHA-256 hex digest of exact referenced file bytes, before parsing |

An upsert references the complete document version. A delete references a small tombstone payload containing the matching tenant, document ID, source, and source version; the reference and checksum remain required. Paths must stay within the dataset root. Validate that envelope identity/version agrees with the payload before processing.

## Replay semantics and fixture coverage

Exact duplicate events are no-ops. Reusing an event ID with altered envelope or payload is invalid. Different event IDs with the same document version and identical content have no additional visible effect; conflicting content at that version is invalid. Lower versions are stale and cannot replace newer state. Retain deletion version tombstones so delayed events cannot resurrect old content; a strictly newer upsert explicitly restores the document.

Future fixtures should cover all six types, the 14:03–14:07 AcmePay scenario, irrelevant distractors, updates, deletions, duplicate deliveries, out-of-order versions, invalid checksums, and colliding document IDs across tenants. Queries with no relevant evidence must also be represented. A separate expected-results manifest should identify relevant document versions and evidence links, without exposing answer labels to retrieval.

Real sources may use opaque versions or weaker ordering. Mapping those sources into this contract remains an open design question, not an asserted connector capability.
