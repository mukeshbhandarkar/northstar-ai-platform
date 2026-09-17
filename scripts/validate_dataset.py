"""Validate NORTH-002 static fixtures; does not ingest, retrieve, or write files."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'datasets/synthetic_enterprise'
DOCUMENT_FIELDS = {
    'tenant_id', 'document_id', 'source', 'source_version', 'created_at',
    'updated_at', 'document_type', 'title', 'body',
}
IDENTITY_FIELDS = {'tenant_id', 'document_id', 'source', 'source_version'}
EVENT_FIELDS = IDENTITY_FIELDS | {
    'event_id', 'event_type', 'occurred_at', 'payload_ref', 'checksum',
}
TYPES = {'runbook', 'architecture_doc', 'incident', 'pull_request',
         'support_ticket', 'deployment'}
TENANTS = {'acmepay', 'betashop'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'{path}: duplicate JSON key {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_keys)


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', value),
        f'Expected UTC RFC 3339 timestamp: {value!r}')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.utcoffset() == timezone.utc.utcoffset(parsed), 'Non-UTC time')
    return parsed


def identity(obj):
    require(obj.get('tenant_id') in TENANTS, 'Unknown tenant')
    for field in ('document_id', 'source'):
        require(isinstance(obj.get(field), str) and obj[field].strip(),
                f'Invalid {field}')
    require(type(obj.get('source_version')) is int and obj['source_version'] > 0,
            'source_version must be a positive integer, not a boolean')
    return obj['tenant_id'], obj['document_id'], obj['source_version']


def reference(root, relative):
    require(isinstance(relative, str) and relative, 'Empty file reference')
    path = Path(relative)
    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe payload path')
    resolved = (root / path).resolve()
    require(resolved.is_relative_to(root.resolve()) and resolved.is_file(),
            f'Missing or escaped reference: {relative}')
    return resolved


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root):
    manifest = load(root / 'manifest.json')
    require(manifest['dataset_version'] == 'north-002-v1' and
            manifest['schema_version'] == 1, 'Unsupported fixture version')
    require(type(manifest['seed']) is int, 'Missing deterministic seed')
    cutoff = timestamp(manifest['snapshot_as_of'])
    expected_files = {str(p.relative_to(root)) for p in (root / 'payloads').rglob('*.json')}
    expected_files |= {'events.json', 'ground_truth.json'}
    require(set(manifest['files']) == expected_files, 'Manifest file inventory mismatch')
    for relative, checksum in manifest['files'].items():
        require(digest(reference(root, relative)) == checksum,
                f'Manifest checksum mismatch: {relative}')

    documents, payloads, lineages = {}, {}, {}
    for relative in sorted(expected_files - {'events.json', 'ground_truth.json'}):
        obj = load(reference(root, relative))
        key = identity(obj)
        require(key not in payloads, f'Duplicate tenant/document/version: {key}')
        payloads[key] = (relative, obj)
        if '.delete.' in relative:
            require(set(obj) == IDENTITY_FIELDS, f'Invalid tombstone: {relative}')
            continue
        require(set(obj) == DOCUMENT_FIELDS, f'Invalid document fields: {relative}')
        require(obj['document_type'] in TYPES, f'Invalid type: {relative}')
        for field in ('title', 'body'):
            require(isinstance(obj[field], str) and obj[field].strip(), f'Empty {field}')
        created, updated = timestamp(obj['created_at']), timestamp(obj['updated_at'])
        require(created <= updated <= cutoff, f'Invalid snapshot dates: {relative}')
        stable = obj['source'], obj['created_at'], obj['document_type']
        require(lineages.setdefault(key[:2], stable) == stable,
                f'Changed source/creation/type in lineage: {key}')
        documents[key] = obj

    events = load(root / 'events.json')
    require(isinstance(events, list) and events, 'No event deliveries')
    seen_ids, version_content, referenced = {}, {}, set()
    for position, event in enumerate(events, 1):
        require(set(event) == EVENT_FIELDS, f'Event {position}: wrong fields')
        key = identity(event)
        require(isinstance(event['event_id'], str) and event['event_id'].strip(), 'Invalid event ID')
        require(event['event_type'] in {'upsert', 'delete'}, 'Invalid event type')
        occurred = timestamp(event['occurred_at'])
        require(occurred <= cutoff, 'Event after snapshot')
        path = reference(root, event['payload_ref'])
        require(digest(path) == event['checksum'], f'Event {position}: checksum mismatch')
        require(key in payloads, f'Event {position}: unknown payload identity')
        relative, payload = payloads[key]
        require(relative == event['payload_ref'], 'Event payload path mismatch')
        require(all(event[f] == payload[f] for f in IDENTITY_FIELDS), 'Envelope/payload mismatch')
        require(event['source'] == lineages[key[:2]][0], 'Tombstone source mismatch')
        require((event['event_type'] == 'delete') == ('.delete.' in relative), 'Payload kind mismatch')
        if event['event_type'] == 'upsert':
            require(occurred == timestamp(payload['updated_at']), 'Upsert time mismatch')
        require(seen_ids.setdefault(event['event_id'], event) == event,
                'Event ID reused with conflicting content')
        signature = event['event_type'], event['checksum']
        require(version_content.setdefault(key, signature) == signature, 'Conflicting version')
        referenced.add(relative)
    require(referenced == expected_files - {'events.json', 'ground_truth.json'},
            'Payload missing from event fixture')

    # Inspect declared fixture relationships, without materializing document state.
    scenarios = manifest['event_scenarios']
    required = {'create', 'update', 'exact_duplicate', 'stale_replay', 'delete',
                'duplicate_delete', 'stale_after_delete', 'restore'}
    require(set(scenarios) == required, 'Missing edge-case categories')
    for name, position in scenarios.items():
        require(type(position) is int and 1 <= position <= len(events), 'Invalid scenario position')
        current, prefix = events[position - 1], events[:position - 1]
        previous = [e for e in prefix if identity(e)[:2] == identity(current)[:2]]
        latest = max(previous, key=lambda e: e['source_version']) if previous else None
        if name in {'exact_duplicate', 'duplicate_delete'}:
            require(current in prefix, f'{name}: not an exact duplicate')
            if name == 'duplicate_delete':
                require(current['event_type'] == 'delete', 'Not a duplicate delete')
        elif name == 'create':
            require(not previous and current['event_type'] == 'upsert', 'Invalid create')
        else:
            require(latest is not None, f'{name}: no prior version')
            if name in {'stale_replay', 'stale_after_delete'}:
                require(current['source_version'] < latest['source_version'], 'Not stale')
                if name == 'stale_after_delete':
                    require(latest['event_type'] == 'delete', 'No preceding tombstone')
            else:
                require(current['source_version'] > latest['source_version'], 'Not a newer version')
                require(current['event_type'] == ('delete' if name == 'delete' else 'upsert'),
                        f'{name}: wrong event type')
                if name == 'restore':
                    require(latest['event_type'] == 'delete', 'Restore must follow tombstone')

    snapshot = {}
    for relative in manifest['snapshot_payloads']:
        obj = load(reference(root, relative))
        key = identity(obj)
        require(key in documents and key[:2] not in snapshot, 'Invalid/duplicate snapshot identity')
        require(payloads[key][0] == relative, 'Snapshot must reference registered document payload')
        lineage_events = [e for e in events if identity(e)[:2] == key[:2]]
        highest = max(lineage_events, key=lambda e: e['source_version'])
        require(highest['event_type'] == 'upsert' and highest['source_version'] == key[2],
                'Snapshot references stale or deleted version')
        snapshot[key[:2]] = obj
    require(set(snapshot) == set(lineages), 'Snapshot does not cover all document identities')
    require(20 <= len(snapshot) <= 30, 'Expected a manually inspectable 20–30 document corpus')
    require({k[0] for k in snapshot} == TENANTS, 'Missing tenant')
    require({d['document_type'] for d in snapshot.values()} == TYPES, 'Missing document category')

    cases = load(root / 'ground_truth.json')
    require(6 <= len(cases) <= 10, 'Expected 6–10 investigation cases')
    case_ids = set()
    for case in cases:
        require(set(case) == {'case_id', 'tenant_id', 'as_of', 'question', 'expected_evidence',
                'acceptable_supporting_evidence', 'known_distractors', 'expected_conclusion', 'abstain'},
                'Invalid case fields')
        require(case['tenant_id'] in TENANTS, 'Invalid case tenant')
        for field in ('case_id', 'question', 'expected_conclusion'):
            require(isinstance(case[field], str) and case[field].strip(), f'Invalid case {field}')
        require(case['case_id'] not in case_ids, 'Duplicate case ID')
        case_ids.add(case['case_id'])
        require(timestamp(case['as_of']) == cutoff, 'Case snapshot mismatch')
        require(type(case['abstain']) is bool, 'abstain must be boolean')
        used = set()
        for field in ('expected_evidence', 'acceptable_supporting_evidence', 'known_distractors'):
            require(isinstance(case[field], list), 'Evidence must be a list')
            for ref in case[field]:
                require(set(ref) == {'tenant_id', 'document_id', 'source_version'}, 'Invalid evidence ref')
                require(type(ref['source_version']) is int and ref['source_version'] > 0,
                        'Invalid evidence version')
                key = ref['tenant_id'], ref['document_id'], ref['source_version']
                require(key in documents and key not in used, f'Missing/repeated evidence: {key}')
                used.add(key)
                if field != 'known_distractors':
                    require(key[0] == case['tenant_id'], 'Cross-tenant positive evidence')
                    require(snapshot[key[:2]]['source_version'] == key[2], 'Stale positive evidence')
        require(bool(case['expected_evidence']) != case['abstain'], 'Abstention/evidence mismatch')
        if case['abstain']:
            require(not case['acceptable_supporting_evidence'], 'Abstention has positive evidence')
    require(any(c['abstain'] for c in cases), 'No abstention case')
    require({c['tenant_id'] for c in cases} == TENANTS, 'No bidirectional isolation cases')
    primary = next((c for c in cases if c['case_id'] == 'ACME-001'), None)
    require(primary is not None and primary['tenant_id'] == 'acmepay', 'Missing primary case')
    primary_types = {documents[(r['tenant_id'], r['document_id'], r['source_version'])]['document_type']
                     for r in primary['expected_evidence']}
    require({'deployment', 'pull_request', 'incident', 'runbook', 'support_ticket'} <= primary_types,
            'Primary case must require multi-source correlation')
    print('PASS: document schemas, timestamps, identities, checksums, events, snapshots, and ground truth')
    print('Documents by tenant:', dict(sorted(Counter(d['tenant_id'] for d in snapshot.values()).items())))
    print('Documents by type:', dict(sorted(Counter(d['document_type'] for d in snapshot.values()).items())))
    print(f'{len(snapshot)} identities; {len(documents)} normal versions; '
          f'{len(payloads) - len(documents)} tombstone; {len(cases)} cases; '
          f'{len(events)} deliveries; {len(seen_ids)} unique events')
    print('Edge cases:', ', '.join(scenarios))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-root', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    try:
        validate(args.dataset_root)
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
