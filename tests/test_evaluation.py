from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.evaluate_retrieval import evaluate, percentiles, score_case

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'datasets/synthetic_enterprise'


def ref(name, version=1, tenant='acmepay'):
    return {'tenant_id': tenant, 'document_id': name, 'source_version': version}


class EvaluationTests(unittest.TestCase):
    def case(self, abstain=False):
        return {'expected_evidence': [] if abstain else [ref('A'), ref('B')],
                'acceptable_supporting_evidence': [] if abstain else [ref('C')],
                'known_distractors': [ref('D')], 'abstain': abstain}

    def test_required_recall_optional_precision_and_distractors(self):
        metrics = score_case(self.case(), [ref('A'), ref('C'), ref('D')])
        self.assertEqual(.5, metrics['required_recall_at_5'])
        self.assertEqual(2 / 3, metrics['precision_at_returned_count'])
        self.assertFalse(metrics['complete_required_evidence'])
        self.assertEqual([ref('B')], metrics['misses'])
        self.assertEqual([ref('D')], metrics['known_distractor_hits'])
        self.assertTrue(score_case(self.case(), [ref('B'), ref('A')])['complete_required_evidence'])

    def test_wrong_version_and_tenant_receive_no_credit(self):
        metrics = score_case(self.case(), [ref('A', 2), ref('B', tenant='betashop')])
        self.assertEqual(0, metrics['required_recall_at_5'])
        self.assertEqual(0, metrics['precision_at_returned_count'])
        self.assertEqual([ref('A'), ref('B')], metrics['misses'])

    def test_empty_and_no_evidence_denominators(self):
        metrics = score_case(self.case(), [])
        self.assertEqual(0, metrics['required_recall_at_5'])
        self.assertIsNone(metrics['precision_at_returned_count'])
        self.assertFalse(metrics['complete_required_evidence'])
        for results in ([], [ref('D')]):
            metrics = score_case(self.case(abstain=True), results)
            self.assertIsNone(metrics['required_recall_at_5'])
            self.assertIsNone(metrics['complete_required_evidence'])
            self.assertEqual(not results, metrics['no_evidence_empty_result'])
            self.assertEqual(0 if results else None, metrics['precision_at_returned_count'])

    def test_nearest_rank_and_error_censoring(self):
        samples = [{'latency_ns': n * 1000000, 'error': None} for n in (4, 1, 3, 2)]
        self.assertEqual(2, percentiles(samples)['p50_ms'])
        self.assertEqual(4, percentiles(samples)['p95_ms'])
        samples.append({'latency_ns': 1, 'error': 'failed'})
        self.assertEqual(3, percentiles(samples)['p50_ms'])
        self.assertIsNone(percentiles(samples)['p95_ms'])
        self.assertTrue(percentiles(samples)['p95_censored'])

    def test_eight_case_report_and_repeat_accounting(self):
        with redirect_stderr(io.StringIO()):
            report = evaluate(DATASET, 2)
        self.assertEqual(8, len(report['cases']))
        self.assertEqual(16, len(report['samples']))
        self.assertEqual(7, report['summary']['scored_positive_cases'])
        self.assertEqual(1, report['summary']['no_evidence_cases'])
        self.assertEqual(0, report['summary']['errors'])
        self.assertEqual([], report['correctness_failures'])
        self.assertTrue(report['replay']['manifest_match'])
        for case in report['cases']:
            self.assertLessEqual(len(case['results']), 5)
            samples = [s for s in report['samples'] if s['case_id'] == case['case_id']]
            self.assertEqual(samples[0]['results'], samples[1]['results'])
            self.assertTrue(all(s['latency_ns'] > 0 for s in samples))
        json.dumps(report, allow_nan=False)

    def test_invalid_repeat_count(self):
        for repeats in (0, -1, True):
            with self.assertRaises(ValueError):
                evaluate(DATASET, repeats)

    def test_cli_preserves_existing_output_and_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.json'
            path.write_text('preserve')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/evaluate_retrieval.py'),
                                     '--output', str(path)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual('preserve', path.read_text())
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/evaluate_retrieval.py'),
                                 '--output', str(DATASET / 'forbidden-report.json')],
                                capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((DATASET / 'forbidden-report.json').exists())


if __name__ == '__main__':
    unittest.main()
