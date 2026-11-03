"""Offline invariant tests: deterministic encoders, actual event transitions."""
import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from services.processor import Store, Processor
from services.retrieval import Retriever
from services.retrieval.semantic import SemanticRetriever, SentenceTransformerEncoder
from services.retrieval.hybrid import HybridRetriever, fuse
from scripts.evaluate_retrieval import evaluate, score_case

DATASET = Path(__file__).resolve().parents[1] / 'datasets/synthetic_enterprise'


class FakeEncoder:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [[3, 4] for _ in texts]


def row(name, version=1, tenant='acmepay'):
    return dict(tenant_id=tenant, document_id=name, source_version=version,
                title=name, score=1, matched_tokens=[])


class DenseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state.db')
        self.addCleanup(self.store.close)
        self.processor = Processor(self.store, DATASET)
        self.events = json.loads((DATASET / 'events.json').read_text())
        self.encoder = FakeEncoder()
        self.retriever = SemanticRetriever(self.store, self.encoder)

    def deliver_all(self):
        for event in self.events:
            self.assertNotEqual('INVALID', self.processor.process(event).outcome)

    def test_snapshot_ties_normalization_tenant_and_warm_cache(self):
        self.deliver_all()
        results = self.retriever.search('acmepay', 'query')
        self.assertEqual(sorted(r['document_id'] for r in results), [r['document_id'] for r in results])
        self.assertTrue(all(abs(r['score'] - 1) < 1e-12 for r in results))
        self.assertEqual(18, len(self.encoder.calls[0]))
        self.retriever.search('acmepay', 'query')
        self.assertEqual(0, self.retriever.last_timings['encoded_documents'])
        self.assertEqual(3, len(self.encoder.calls))
        beta = self.retriever.search('betashop', 'query', top_k=100)
        self.assertEqual(6, len(beta))
        self.assertEqual({'betashop'}, {r['tenant_id'] for r in beta})
        self.assertEqual(6, len(self.retriever._entries))
        self.assertEqual(18, len(self.retriever.search('acmepay', 'query', top_k=100)))

    def test_updates_deletes_stale_restore_and_restart(self):
        # Exercise fixture SUP-303 lifecycle in its real delivery order.
        observed = []
        for event in self.events:
            self.processor.process(event)
            results = self.retriever.search('acmepay', 'receipt', top_k=100)
            current = self.store.get('acmepay', 'SUP-303')
            matches = [r for r in results if r['document_id'] == 'SUP-303']
            self.assertEqual([current['source_version']] if current else [],
                             [r['source_version'] for r in matches])
            if event['tenant_id'] == 'acmepay' and event['document_id'] == 'SUP-303':
                observed.append(current['source_version'] if current else None)
            self.assertEqual(len(self.store.documents('acmepay')), len(self.retriever._entries))
        self.assertIn(None, observed)
        self.assertIn(2, observed)
        self.assertEqual(4, observed[-1])
        restarted = SemanticRetriever(self.store, FakeEncoder())
        self.assertEqual(results, restarted.search('acmepay', 'receipt', top_k=100))
        self.assertEqual(18, restarted.last_timings['encoded_documents'])

    def test_invalid_empty_and_limits_do_not_load_model(self):
        encoder = SentenceTransformerEncoder()
        retriever = SemanticRetriever(self.store, encoder)
        for query in ('', '  ', '!!!'):
            self.assertEqual([], retriever.search('acmepay', query))
        self.assertEqual([], retriever.search('acmepay', 'query'))
        self.assertIsNone(encoder.model)
        for query in (None, 1, []):
            with self.assertRaises(ValueError):
                retriever.search('acmepay', query)
        for k in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                retriever.search('acmepay', 'query', top_k=k)
        with self.assertRaises(ValueError):
            retriever.search('', 'query')
        self.assertEqual([], retriever.search('acmepay', 'query', top_k=0))

    def test_encoder_failures_never_return_partial_or_stale_index(self):
        self.deliver_all()
        self.retriever.index('acmepay')
        for output in ([], [[0, 0]], [[float('nan'), 1]], [[1]], [[float('inf'), 1]]):
            self.encoder.encode = lambda texts, output=output: output
            with self.assertRaises(ValueError):
                self.retriever.search('acmepay', 'query')
        # A failed tenant switch preserves the previous published snapshot.
        previous_cache = self.retriever._cache
        previous_entries = self.retriever._entries
        with self.assertRaises(ValueError):
            self.retriever.search('betashop', 'query')
        self.assertIs(previous_cache, self.retriever._cache)
        self.assertIs(previous_entries, self.retriever._entries)
        self.assertEqual('acmepay', self.retriever._tenant)

    def test_failed_update_preserves_cache_then_retry_publishes_current_version(self):
        lifecycle = [e for e in self.events if e['tenant_id'] == 'acmepay'
                     and e['document_id'] == 'SUP-303' and e['event_type'] == 'upsert']
        self.processor.process(next(e for e in lifecycle if e['source_version'] == 1))
        self.retriever.search('acmepay', 'receipt')
        self.retriever.index('betashop')
        cache, entries = self.retriever._cache, self.retriever._entries
        dimension = self.retriever._dimension
        order = list(cache)
        original_encode = self.encoder.encode
        self.processor.process(next(e for e in lifecycle if e['source_version'] == 2))
        self.encoder.encode = lambda texts: [[0, 0] for _ in texts]
        with self.assertRaises(ValueError):
            self.retriever.search('acmepay', 'receipt')
        self.assertIs(cache, self.retriever._cache)
        self.assertIs(entries, self.retriever._entries)
        self.assertEqual(order, list(self.retriever._cache))
        self.assertEqual('betashop', self.retriever._tenant)
        self.assertEqual(dimension, self.retriever._dimension)
        self.assertEqual(1, cache['acmepay']['SUP-303'][0][0])
        self.encoder.encode = original_encode
        self.assertEqual([2], [r['source_version'] for r in
                             self.retriever.search('acmepay', 'receipt')])
        self.assertEqual(['betashop', 'acmepay'], list(self.retriever._cache))
        self.assertEqual(2, self.retriever._entries['SUP-303'][0][0])

    def test_hybrid_encoding_failure_releases_savepoint_and_preserves_outer_transaction(self):
        self.deliver_all()
        hybrid = HybridRetriever(self.store, self.encoder)
        original_encode = self.encoder.encode
        def fail(texts):
            self.assertTrue(self.store.connection.in_transaction)
            raise ValueError('Forced embedding failure')
        self.encoder.encode = fail
        for outer_transaction in (False, True):
            with self.subTest(outer_transaction=outer_transaction):
                if outer_transaction:
                    self.store.connection.execute('BEGIN')
                with self.assertRaisesRegex(ValueError, 'Forced embedding failure'):
                    hybrid.search('acmepay', 'checkout')
                self.assertEqual(outer_transaction, self.store.connection.in_transaction)
                # RELEASE must fail because the retrieval savepoint is gone.
                with self.assertRaises(sqlite3.OperationalError):
                    self.store.connection.execute('RELEASE SAVEPOINT retrieval_snapshot')
                self.assertEqual(18, len(self.store.documents('acmepay')))
                if outer_transaction:
                    self.store.connection.rollback()
        self.encoder.encode = original_encode
        self.assertTrue(hybrid.search('acmepay', 'checkout'))
        self.assertFalse(self.store.connection.in_transaction)
        self.store.connection.execute('BEGIN IMMEDIATE')
        self.store.connection.rollback()

    def test_hybrid_rejects_foreign_stale_future_unknown_and_deleted_candidates(self):
        # Stop SUP-303 at the real v3 tombstone while replaying other documents.
        for event in self.events:
            if (event['tenant_id'], event['document_id'], event['source_version']) != ('acmepay', 'SUP-303', 4):
                self.assertNotEqual('INVALID', self.processor.process(event).outcome)
        self.assertIsNone(self.store.get('acmepay', 'SUP-303'))
        invalid = [row('PR-1842', tenant='betashop'), row('PR-1842', 0),
                   row('PR-1842', 2), row('SUP-303', 1), row('SUP-303', 3), row('UNKNOWN')]
        hybrid = HybridRetriever(self.store, self.encoder)
        for source in ('lexical', 'semantic'):
            for candidate in invalid:
                with self.subTest(source=source, candidate=candidate):
                    lexical = [candidate] if source == 'lexical' else [row('PR-1842')]
                    dense = [candidate] if source == 'semantic' else [row('PR-1842')]
                    with patch.object(Retriever, 'search', return_value=lexical), \
                         patch.object(hybrid.semantic, 'search', return_value=dense):
                        with self.assertRaisesRegex(ValueError, 'outside requested tenant active snapshot'):
                            hybrid.search('acmepay', 'receipt')
                    self.assertFalse(self.store.connection.in_transaction)
        self.assertTrue(hybrid.search('acmepay', 'receipt'))

    def test_batch_dimension_errors_and_bounded_tenant_cache(self):
        for vectors in ([[1, 2], [1]], [[1, 2]], [[1, 2], []]):
            fake = FakeEncoder()
            fake.encode = lambda texts, vectors=vectors: vectors
            retriever = SemanticRetriever(self.store, fake)
            with self.assertRaises(ValueError):
                retriever._encode(['a', 'b'])
        self.deliver_all()
        for tenant in ('acmepay', 'betashop', 'empty-tenant'):
            self.retriever.index(tenant)
        self.assertEqual(['betashop', 'empty-tenant'], list(self.retriever._cache))
        self.assertEqual(0, len(self.retriever._entries))

    def test_hybrid_snapshot_survives_concurrent_version_update(self):
        self.store.connection.execute('PRAGMA journal_mode=WAL')
        lifecycle = [e for e in self.events if e['tenant_id'] == 'acmepay'
                     and e['document_id'] == 'SUP-303' and e['event_type'] == 'upsert']
        first = next(e for e in lifecycle if e['source_version'] == 1)
        update = next(e for e in lifecycle if e['source_version'] == 2)
        self.processor.process(first)
        writer = Store(Path(self.temp.name) / 'state.db')
        self.addCleanup(writer.close)
        fake = FakeEncoder()
        original_encode = fake.encode
        changed = []
        def encode(texts):
            if not changed:
                self.assertEqual('APPLIED', Processor(writer, DATASET).process(update).outcome)
                changed.append(True)
            return original_encode(texts)
        fake.encode = encode
        hybrid = HybridRetriever(self.store, fake)
        self.assertEqual([1], [r['source_version'] for r in hybrid.search('acmepay', 'receipt')])
        self.assertEqual([2], [r['source_version'] for r in hybrid.search('acmepay', 'receipt')])

    def test_baseline_import_does_not_import_ml(self):
        result = subprocess.run([sys.executable, '-c',
            "from services.retrieval import Retriever; import sys; assert 'torch' not in sys.modules; assert 'sentence_transformers' not in sys.modules"], capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_hybrid_and_dense_evaluation_with_fake_encoder(self):
        for mode in ('semantic', 'hybrid'):
            report = evaluate(DATASET, 2, mode=mode, encoder=FakeEncoder())
            self.assertEqual([], report['correctness_failures'])
            self.assertEqual(0, report['summary']['errors'])
            self.assertEqual(16, len(report['samples']))
            self.assertEqual(24, report['corpus']['documents'])

    def test_lexical_default_and_deeper_pool(self):
        self.deliver_all()
        lexical = Retriever(self.store)
        self.assertEqual(lexical.search('acmepay', 'checkout'),
                         lexical.search('acmepay', 'checkout', top_k=20)[:5])
        self.assertGreater(len(lexical.search('acmepay', 'checkout', top_k=20)), 5)
        hybrid = HybridRetriever(self.store, self.encoder)
        self.assertEqual(hybrid.search('acmepay', 'checkout'), hybrid.search('acmepay', 'checkout'))
        self.assertFalse(self.store.connection.in_transaction)


class FusionTests(unittest.TestCase):
    def test_rank_absence_identity_and_ties(self):
        results = fuse([[row('B'), row('A')], [row('A'), row('C')]])
        self.assertEqual(['A', 'B', 'C'], [r['document_id'] for r in results])
        self.assertAlmostEqual(1 / 62 + 1 / 61, results[0]['score'])
        results = fuse([[row('A', 1)], [row('A', 2), row('A', 1, 'betashop')]])
        self.assertEqual(3, len(results))
        self.assertEqual([1, 2], [r['source_version'] for r in results if r['tenant_id'] == 'acmepay'])
        self.assertEqual([], fuse([], top_k=0))

    def test_invalid_fusion_configuration_and_duplicates(self):
        for k in (0, -1, True, float('nan'), float('inf'), '60'):
            with self.assertRaises(ValueError):
                fuse([], rrf_k=k)
        with self.assertRaises(ValueError):
            fuse([[row('A'), row('A')]])

    def test_precision_at_five_empty_and_short_lists(self):
        case = dict(expected_evidence=[row('A')], acceptable_supporting_evidence=[],
                    known_distractors=[], abstain=False)
        self.assertEqual(0, score_case(case, [])['precision_at_5'])
        self.assertEqual(.2, score_case(case, [row('A')])['precision_at_5'])
