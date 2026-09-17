# Future synthetic enterprise dataset

Contract only; NORTH-001 generates no dataset. All entities, incidents, and customer content will be fictional. Future fixtures should be small, deterministic UTF-8 files with a versioned manifest, fixed seed, and checksums. Start with AcmePay plus one isolation-test tenant and at most 1,000 small documents; this is a design assumption, not production scale.

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
