import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from services.processor import Processor, Store
from scripts.replay_events import compare_manifest, replay

DATASET = Path(__file__).resolve().parents[1] / 'datasets/synthetic_enterprise'


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root / 'dataset'
        shutil.copytree(DATASET, self.dataset)
        self.events = json.loads((self.dataset / 'events.json').read_text())
        self.manifest = json.loads((self.dataset / 'manifest.json').read_text())
        self.db = self.root / 'state.db'
        self.store = Store(self.db)
        self.addCleanup(self.store.close)
        self.processor = Processor(self.store, self.dataset)

    def process(self, delivery, expected):
        result = self.processor.process(copy.deepcopy(self.events[delivery - 1]))
        self.assertEqual(expected, result.outcome, result.reason)
        return result

    def state(self, deleted=True):
        return self.store.get('acmepay', 'SUP-303', include_deleted=deleted)

    def edited(self, delivery, **changes):
        event = dict(self.events[delivery - 1], event_id='custom-event')
        payload = json.loads((self.dataset / event['payload_ref']).read_text())
        payload.update(changes)
        raw = (json.dumps(payload) + '\n').encode()
        (self.dataset / 'custom.json').write_bytes(raw)
        event.update(payload_ref='custom.json', checksum=hashlib.sha256(raw).hexdigest())
        for field in ('source_version', 'tenant_id', 'document_id', 'source'):
            event[field] = payload[field]
        return event

    def test_normal_create(self):
        self.process(15, 'APPLIED')
        self.assertEqual(1, self.state()['source_version'])
        self.assertEqual(1, self.store.processed_event_count())

    def test_newer_update(self):
        self.process(15, 'APPLIED')
        self.process(25, 'APPLIED')
        self.assertEqual(2, self.state()['source_version'])
        self.assertIn('email forwarder', self.state()['payload_json'])

    def test_exact_duplicate(self):
        self.process(25, 'APPLIED')
        before = self.state()
        self.process(26, 'DUPLICATE')
        self.assertEqual(before, self.state())
        self.assertEqual(1, self.store.processed_event_count())

    def test_reused_event_id_different_envelope(self):
        self.process(15, 'APPLIED')
        before = self.state()
        event = dict(self.events[14], occurred_at='2026-09-10T10:01:00Z')
        self.assertEqual('INVALID', self.processor.process(event).outcome)
        self.assertEqual(before, self.state())
        self.assertEqual(1, self.store.processed_event_count())

    def test_reused_event_id_changed_payload(self):
        self.process(15, 'APPLIED')
        before = self.state()
        event = self.edited(15, body='different valid content')
        event['event_id'] = self.events[14]['event_id']
        self.assertEqual('INVALID', self.processor.process(event).outcome)
        self.assertEqual(before, self.state())
        self.assertEqual(1, self.store.processed_event_count())

    def test_duplicate_json_keys_rejected(self):
        event = dict(self.events[14], payload_ref='ambiguous.json')
        raw = b'{"tenant_id":"acmepay","tenant_id":"betashop"}'
        (self.dataset / 'ambiguous.json').write_bytes(raw)
        event['checksum'] = hashlib.sha256(raw).hexdigest()
        self.assertEqual('INVALID', self.processor.process(event).outcome)
        self.assertEqual(0, self.store.processed_event_count())

    def test_unseen_stale_does_not_replace_current(self):
        self.process(25, 'APPLIED')
        self.assertFalse(self.store.has_event('evt-028'))
        before = self.state()
        self.assertLess(self.events[27]['source_version'], before['source_version'])
        self.process(28, 'STALE')
        self.assertEqual(before, self.state())
        self.assertTrue(self.store.has_event('evt-028'))
        self.process(28, 'DUPLICATE')

    def test_delete_and_unseen_stale(self):
        self.process(25, 'APPLIED')
        self.process(29, 'APPLIED')
        before = self.state()
        self.assertIsNone(self.state(deleted=False))
        self.assertEqual([], self.store.documents('acmepay'))
        self.assertFalse(self.store.has_event('evt-029'))
        self.process(32, 'STALE')
        self.assertEqual(before, self.state())
        self.assertTrue(self.state()['deleted'])
        self.process(30, 'DUPLICATE')

    def test_restore(self):
        self.process(29, 'APPLIED')
        self.process(33, 'APPLIED')
        self.assertEqual(4, self.state(deleted=False)['source_version'])
        self.assertFalse(self.state()['deleted'])

    def test_same_version_identical_new_id(self):
        self.process(25, 'APPLIED')
        before = self.state()
        event = dict(self.events[24], event_id='same-version-new-id')
        self.assertEqual('DUPLICATE', self.processor.process(event).outcome)
        self.assertEqual(before, self.state())
        self.assertEqual(2, self.store.processed_event_count())

    def test_same_version_conflict(self):
        self.process(25, 'APPLIED')
        before = self.state()
        self.assertEqual('INVALID', self.processor.process(self.edited(25, body='conflict')).outcome)
        self.assertEqual(before, self.state())
        self.assertEqual(1, self.store.processed_event_count())

    def test_historical_version_conflict(self):
        self.process(15, 'APPLIED')
        self.process(25, 'APPLIED')
        before = self.state()
        self.assertEqual('INVALID', self.processor.process(self.edited(15, body='old conflict')).outcome)
        self.assertEqual(before, self.state())
        self.assertEqual(2, self.store.processed_event_count())

    def test_source_and_created_at_immutable(self):
        self.process(15, 'APPLIED')
        for change in ({'source': 'another-source'}, {'created_at': '2026-09-09T10:00:00Z'}):
            with self.subTest(change=change):
                self.assertEqual('INVALID', self.processor.process(self.edited(25, **change)).outcome)
        self.assertEqual(1, self.state()['source_version'])

    def test_tenant_collision_and_sql_filtering(self):
        self.process(1, 'APPLIED')
        self.process(19, 'APPLIED')
        queries = []
        self.store.connection.set_trace_callback(queries.append)
        acme = self.store.documents('acmepay')
        beta = self.store.get('betashop', 'RB-001')
        self.store.connection.set_trace_callback(None)
        self.assertEqual(['acmepay'], [r['tenant_id'] for r in acme])
        self.assertEqual('betashop', beta['tenant_id'])
        self.assertNotEqual(acme[0]['payload_json'], beta['payload_json'])
        self.assertTrue(all('WHERE tenant_id =' in q for q in queries))
        with self.assertRaises(ValueError):
            self.store.documents(None)

    def test_atomic_rollback_and_retry(self):
        self.process(15, 'APPLIED')
        before = self.state()
        self.store.connection.execute('''CREATE TRIGGER fail_event BEFORE INSERT ON events
            WHEN NEW.event_id = 'evt-025' BEGIN SELECT RAISE(ABORT, 'injected failure'); END''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected failure'):
            self.processor.process(self.events[24])
        self.assertEqual(before, self.state())
        self.assertFalse(self.store.has_event('evt-025'))
        with sqlite3.connect(self.db) as observer:
            self.assertEqual(1, observer.execute('SELECT source_version FROM documents').fetchone()[0])
            self.assertEqual(1, observer.execute('SELECT count(*) FROM versions').fetchone()[0])
            self.assertEqual(1, observer.execute('SELECT count(*) FROM events').fetchone()[0])
        self.store.connection.execute('DROP TRIGGER fail_event')
        self.process(25, 'APPLIED')

    def test_full_replay_and_persistent_repeat(self):
        counts = Counter(self.processor.process(e).outcome for e in self.events)
        self.assertEqual({'APPLIED': 27, 'DUPLICATE': 4, 'STALE': 2}, counts)
        self.assertTrue(compare_manifest(self.store, self.dataset, self.manifest))
        before = {t: self.store.documents(t, include_deleted=True) for t in self.store.tenants()}
        with Store(self.db) as reopened:
            processor = Processor(reopened, self.dataset)
            self.assertEqual({'DUPLICATE': 33}, Counter(processor.process(e).outcome for e in self.events))
            self.assertEqual(before, {t: reopened.documents(t, include_deleted=True) for t in reopened.tenants()})
            self.assertEqual(29, reopened.processed_event_count())
            self.assertTrue(compare_manifest(reopened, self.dataset, self.manifest))

    def test_payload_validation_rejects_without_writes(self):
        valid = self.events[14]
        bad = [None, {}, dict(valid, source_version=True), dict(valid, event_type='replace'),
               dict(valid, checksum='0' * 64), dict(valid, payload_ref='../outside.json'),
               dict(valid, payload_ref='missing.json'), dict(valid, source='wrong'),
               dict(valid, occurred_at='yesterday'), dict(valid, tenant_id=''),
               dict(valid, source_version=2**63)]
        for event in bad:
            with self.subTest(event=event):
                self.assertEqual('INVALID', self.processor.process(event).outcome)
        for changes in ({'created_at': '2027-01-01T00:00:00Z'}, {'body': ''},
                        {'document_type': 'unknown'}, {'source_version': True}):
            self.assertEqual('INVALID', self.processor.process(self.edited(15, **changes)).outcome)
        self.assertEqual(0, self.store.processed_event_count())
        self.assertEqual([], self.store.documents('acmepay'))

    def test_symlink_escape(self):
        outside = self.root / 'outside.json'
        outside.write_bytes((self.dataset / self.events[14]['payload_ref']).read_bytes())
        (self.dataset / 'escape.json').symlink_to(outside)
        event = dict(self.events[14], payload_ref='escape.json')
        self.assertEqual('INVALID', self.processor.process(event).outcome)
        self.assertEqual(0, self.store.processed_event_count())

    def test_manifest_comparison_detects_wrong_state(self):
        self.assertFalse(compare_manifest(self.store, self.dataset, self.manifest))
        for event in self.events:
            self.processor.process(event)
        self.store.connection.execute("UPDATE documents SET deleted=1 WHERE tenant_id='acmepay' AND document_id='SUP-303'")
        self.store.connection.commit()
        self.assertFalse(compare_manifest(self.store, self.dataset, self.manifest))

    def test_replay_resumes_without_reset(self):
        path = self.root / 'replay.db'
        first = replay(self.dataset, path, fresh=True)
        second = replay(self.dataset, path)
        self.assertEqual(27, first['outcomes']['APPLIED'])
        self.assertEqual(33, second['outcomes']['DUPLICATE'])
        self.assertEqual(first['current_state'], second['current_state'])
        self.assertTrue(second['manifest_match'])

    def test_unrelated_database_preserved(self):
        path = self.root / 'unrelated.db'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE important (value TEXT)')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            replay(self.dataset, path)
        self.assertEqual(before, path.read_bytes())

    def test_experiment_event_id_only_resurrects_stale_content(self):
        """CONTROLLED BROKEN SIMULATION: intentionally omits document version ordering."""
        self.process(29, 'APPLIED')
        incoming = self.events[31]
        naive_seen = {'evt-026'}
        naive = {'source_version': 3, 'deleted': True}
        self.assertNotIn(incoming['event_id'], naive_seen)
        if incoming['event_id'] not in naive_seen:
            naive = {'source_version': incoming['source_version'], 'deleted': False}
        self.assertEqual({'source_version': 2, 'deleted': False}, naive)
        self.assertFalse(self.store.has_event(incoming['event_id']))
        self.process(32, 'STALE')
        self.assertEqual(3, self.state()['source_version'])
        self.assertTrue(self.state()['deleted'])
        self.assertIsNone(self.state(deleted=False))


if __name__ == '__main__':
    unittest.main()
