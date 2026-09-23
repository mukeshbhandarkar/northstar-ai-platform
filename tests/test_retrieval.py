import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from services.processor import Processor, Store
from services.retrieval import Retriever

DATASET = Path(__file__).resolve().parents[1] / 'datasets/synthetic_enterprise'


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'state.db'
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.retriever = Retriever(self.store)
        self.events = json.loads((DATASET / 'events.json').read_text())
        self.processor = Processor(self.store, DATASET)

    def deliver(self, position, outcome):
        result = self.processor.process(self.events[position - 1])
        self.assertEqual(outcome, result.outcome, result.reason)

    def document(self, document_id, title, body, tenant='acmepay'):
        payload = dict(tenant_id=tenant, document_id=document_id, source='test',
                       source_version=1, created_at='2026-09-01T00:00:00Z',
                       updated_at='2026-09-01T00:00:00Z', document_type='runbook',
                       title=title, body=body)
        raw = json.dumps(payload).encode()
        filename = f'{tenant}-{document_id}.json'
        (self.root / filename).write_bytes(raw)
        event = {k: payload[k] for k in ('tenant_id', 'document_id', 'source', 'source_version')}
        event.update(event_id=filename, event_type='upsert', occurred_at=payload['updated_at'],
                     payload_ref=filename, checksum=hashlib.sha256(raw).hexdigest())
        self.assertEqual('APPLIED', Processor(self.store, self.root).process(event).outcome)

    def test_tenant_collision_filtered_in_sql_before_scoring(self):
        self.document('SAME', 'checkout', 'acmeonly')
        self.document('SAME', 'checkout', 'foreignonly', tenant='betashop')
        queries = []
        self.store.connection.set_trace_callback(queries.append)
        result = self.retriever.search('acmepay', 'checkout foreignonly')
        self.assertEqual([('acmepay', 'SAME', 1, 1)],
                         [(r['tenant_id'], r['document_id'], r['source_version'], r['score']) for r in result])
        self.assertEqual(['checkout'], result[0]['matched_tokens'])
        self.assertTrue(any("WHERE tenant_id = 'acmepay' AND deleted = 0" in q for q in queries))
        self.assertEqual([], self.retriever.search('acmepay', 'foreignonly'))
        self.assertEqual('betashop', self.retriever.search('betashop', 'foreignonly')[0]['tenant_id'])

    def test_ranking_ties_limit_and_distinct_equal_field_weight(self):
        for name in ('G', 'F', 'E', 'D', 'C', 'B', 'A'):
            self.document(name, 'alpha alpha', 'alpha')
        self.document('Z', 'alpha', 'beta')
        expected = [('Z', 2), ('A', 1), ('B', 1), ('C', 1), ('D', 1)]
        for query in ('ALPHA beta alpha', 'beta alpha'):
            for _ in range(3):
                self.assertEqual(expected, [(r['document_id'], r['score'])
                                           for r in self.retriever.search('acmepay', query)])

    def test_token_boundaries_casefold_and_no_metadata_search(self):
        self.document('HIDDENID', 'Straße checkout-api', 'pool_limit 48')
        result = self.retriever.search('acmepay', 'STRASSE checkout API pool limit 48')
        self.assertEqual(6, result[0]['score'])
        self.assertEqual([], self.retriever.search('acmepay', 'HIDDENID runbook acmepay'))

    def test_update_replaces_searchable_text_and_version(self):
        self.deliver(15, 'APPLIED')
        self.assertEqual(1, self.retriever.search('acmepay', 'housekeeping')[0]['source_version'])
        self.deliver(25, 'APPLIED')
        self.assertEqual([], self.retriever.search('acmepay', 'housekeeping'))
        self.assertEqual(2, self.retriever.search('acmepay', 'forwarder')[0]['source_version'])

    def test_duplicates_stale_delete_and_restore(self):
        self.deliver(15, 'APPLIED')
        self.deliver(25, 'APPLIED')
        before = self.retriever.search('acmepay', 'receipt')
        for position, outcome in ((26, 'DUPLICATE'), (27, 'DUPLICATE'), (28, 'STALE')):
            self.deliver(position, outcome)
            self.assertEqual(before, self.retriever.search('acmepay', 'receipt'))
        self.deliver(29, 'APPLIED')
        self.assertEqual([], self.retriever.search('acmepay', 'receipt forwarder'))
        for position, outcome in ((30, 'DUPLICATE'), (31, 'DUPLICATE'), (32, 'STALE')):
            self.deliver(position, outcome)
            self.assertEqual([], self.retriever.search('acmepay', 'receipt forwarder'))
        self.deliver(33, 'APPLIED')
        self.assertEqual(4, self.retriever.search('acmepay', 'receipt')[0]['source_version'])

    def test_restart_preserves_tombstone_then_restoration_and_replay(self):
        self.deliver(29, 'APPLIED')
        self.store.close()
        with Store(self.path) as reopened:
            search = Retriever(reopened)
            processor = Processor(reopened, DATASET)
            self.assertEqual([], search.search('acmepay', 'receipt'))
            self.assertEqual('STALE', processor.process(self.events[31]).outcome)
            self.assertEqual([], search.search('acmepay', 'receipt'))
            self.assertEqual('APPLIED', processor.process(self.events[32]).outcome)
            expected = search.search('acmepay', 'receipt')
            self.assertEqual(4, expected[0]['source_version'])
        with Store(self.path) as reopened:
            self.assertEqual(expected, Retriever(reopened).search('acmepay', 'receipt'))
            self.assertEqual('DUPLICATE', Processor(reopened, DATASET).process(self.events[32]).outcome)
            self.assertEqual(expected, Retriever(reopened).search('acmepay', 'receipt'))

    def test_full_replay_restart_has_identical_rankings(self):
        for event in self.events:
            self.assertNotEqual('INVALID', self.processor.process(event).outcome)
        cases = json.loads((DATASET / 'ground_truth.json').read_text())
        expected = [self.retriever.search(c['tenant_id'], c['question']) for c in cases]
        self.store.close()
        with Store(self.path) as reopened:
            processor = Processor(reopened, DATASET)
            for event in self.events:
                self.assertEqual('DUPLICATE', processor.process(event).outcome)
            self.assertEqual(expected, [Retriever(reopened).search(c['tenant_id'], c['question']) for c in cases])

    def test_empty_zero_result_and_invalid_input(self):
        self.document('A', 'alpha', 'beta')
        for query in ('', ' \n\t', '---___!?', 'unmatchedword'):
            self.assertEqual([], self.retriever.search('acmepay', query))
        self.assertEqual([], self.retriever.search('unknown', 'alpha'))
        for tenant in (None, '', '   ', 12):
            for query in ('', 'alpha'):
                with self.assertRaises(ValueError):
                    self.retriever.search(tenant, query)
        for query in (None, 1, []):
            with self.assertRaises(ValueError):
                self.retriever.search('acmepay', query)


if __name__ == '__main__':
    unittest.main()
