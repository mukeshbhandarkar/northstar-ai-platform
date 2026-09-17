# Company and customer context

## Simulation boundary

NorthstarOps is a fictional company designing a B2B incident investigation and support intelligence service. AcmePay is its first fictional enterprise tenant. Neither name represents a real employer or production deployment. All workload sizes below are **design assumptions**, not observed customer usage.

## Customer and users

The assumed customer is an enterprise with multiple services and operational knowledge spread across repositories, documentation, ticket systems, and incident records. On-call engineers need relevant evidence quickly; support engineers need context for customer reports; service owners need traceable explanations of recent changes. These roles describe future use cases, not an implemented access-control system.

AcmePay is a payment company whose checkout-api depends on payment connections managed through a pool. A tenant is an enterprise knowledge boundary. A document is a versioned knowledge item within that boundary; an event reports a change to that item. An investigation is an explicit sequence that gathers evidence and returns findings with uncertainty.

## Business problem

During an incident, engineers must reconcile recent changes with current documentation and past failures. Stale documents, missing deletions, duplicates, or cross-tenant evidence can make an investigation misleading. NorthstarOps should make supporting evidence and missing information visible, without treating temporal correlation as a verified cause.

## Representative workflow

The following timeline is synthetic scenario time, not measured system latency:

| Time | AcmePay event |
| --- | --- |
| 14:03 | checkout-api v4.7 deployed |
| 14:04 | Payment errors increase |
| 14:05 | Connection wait time increases |
| 14:06 | Support tickets arrive |
| 14:07 | Engineer requests an investigation |

1. Establish the tenant, affected service, question, and time window.
2. Retrieve the deployment, associated PR, service documentation, runbook, tickets, and relevant historical incidents.
3. Compare the PR's connection-pool configuration change with a historical pool-exhaustion incident.
4. Return cited evidence, a provisional hypothesis, missing evidence, and suggested verification steps.
5. Leave incident decisions and remediation to the engineer. Automated remediation is outside the baseline.

Metrics and raw logs will eventually be accessed through dedicated tools, not the vector knowledge store. In v0, their reported symptoms can appear in authored incident or ticket summaries; those summaries are not live telemetry verification.

## Enterprise design assumptions

The following are hypothetical capacity/design inputs used only to support future architecture reasoning. They are NOT achieved results, benchmarks, customer commitments, or claims about a real company.

| Area | Planning assumption |
| --- | --- |
| NorthstarOps company | Approximately 150 employees |
| NorthstarOps customers | Approximately 50 enterprise customer organizations |
| Platform users | Approximately 5,000 active technical users across customers |
| Eventual platform corpus | On the order of 10 million enterprise knowledge documents |
| Platform source-change workload | On the order of 100,000 source-change events/day |
| Peak investigation traffic design scenario | Approximately 200 requests/sec |

## Local simulation / benchmark scale

For future local benchmarks, start with at most 1,000 small documents across AcmePay and one additional synthetic tenant used to test isolation. Use one investigation at a time and sequential event replay before introducing concurrency. These are resource-bounded test assumptions, not capacity promises. Actual corpus bytes, event count, and execution conditions must be recorded with each run.

The local baseline remains CPU-first, with one local Python process and zero required infrastructure spend. These limits are unchanged by the enterprise design assumptions. No local benchmark has been run in NORTH-001.

**ENTERPRISE DESIGN ASSUMPTION != LOCAL MEASURED SCALE**

The architecture may later be evaluated conceptually against the enterprise design assumptions, but benchmark claims must report only the workload actually executed. A local 1,000-document experiment must never be described as having validated a 10-million-document deployment.
