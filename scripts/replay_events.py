"""Replay local fixtures and compare materialized state with the manifest."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.processor import Processor, Store
from services.processor.processor import parse_json, payload_path


def compare_manifest(store, dataset, manifest):
    expected = {}
    for relative in manifest['snapshot_payloads']:
        path = payload_path(dataset, relative)
        payload = parse_json(path.read_text(encoding='utf-8'))
        key = payload['tenant_id'], payload['document_id']
        if key in expected:
            raise ValueError('Duplicate manifest snapshot identity')
        expected[key] = (payload, relative, hashlib.sha256(path.read_bytes()).hexdigest())
    actual = {(tenant, row['document_id']): row for tenant in store.tenants()
              for row in store.documents(tenant, include_deleted=True)}
    if set(actual) != set(expected):
        return False
    return all(not actual[key]['deleted'] and
               json.loads(actual[key]['payload_json']) == payload and
               actual[key]['source_version'] == payload['source_version'] and
               actual[key]['source'] == payload['source'] and
               actual[key]['payload_ref'] == relative and actual[key]['checksum'] == checksum
               for key, (payload, relative, checksum) in expected.items())


def replay(dataset, db_path, *, fresh=False):
    dataset = Path(dataset).resolve()
    db_path = Path(db_path).absolute()
    if db_path.is_symlink() or db_path.resolve().is_relative_to(dataset):
        raise ValueError('Database must be outside the dataset and not a symbolic link')
    manifest = parse_json((dataset / 'manifest.json').read_text(encoding='utf-8'))
    for relative, checksum in manifest['files'].items():
        if hashlib.sha256(payload_path(dataset, relative).read_bytes()).hexdigest() != checksum:
            raise ValueError(f'Manifest checksum mismatch: {relative}')
    events = parse_json((dataset / 'events.json').read_text(encoding='utf-8'))
    if not isinstance(events, list):
        raise ValueError('Events must be an array')
    if fresh:
        for path in [db_path, *(Path(str(db_path) + suffix) for suffix in ('-journal', '-wal', '-shm'))]:
            path.unlink(missing_ok=True)
    counts = Counter({name: 0 for name in ('APPLIED', 'DUPLICATE', 'STALE', 'INVALID')})
    invalid = []
    with Store(db_path) as store:
        processor = Processor(store, dataset)
        for position, event in enumerate(events, 1):
            result = processor.process(event)
            counts[result.outcome] += 1
            if result.outcome == 'INVALID':
                invalid.append({'delivery': position, 'reason': result.reason})
        current = {tenant: store.documents(tenant, include_deleted=True) for tenant in store.tenants()}
        return {
            'outcomes': dict(counts), 'invalid': invalid,
            'active_by_tenant': {t: sum(not r['deleted'] for r in rows) for t, rows in current.items()},
            'tombstones': sum(r['deleted'] for rows in current.values() for r in rows),
            'processed_unique_events': store.processed_event_count(),
            'manifest_match': compare_manifest(store, dataset, manifest),
            'current_state': {t: [{k: r[k] for k in ('document_id', 'source_version', 'deleted',
                                                   'payload_ref', 'checksum')} for r in rows]
                              for t, rows in current.items()},
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[1] /
                        'datasets/synthetic_enterprise')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--fresh', action='store_true', help='Explicitly remove existing database state')
    args = parser.parse_args()
    try:
        report = replay(args.dataset, args.db, fresh=args.fresh)
        print(json.dumps(report, indent=2))
        return 0 if report['manifest_match'] and not report['outcomes']['INVALID'] else 1
    except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
        print(f'Replay failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
