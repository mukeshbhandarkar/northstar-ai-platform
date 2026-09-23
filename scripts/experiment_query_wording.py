"""Controlled query-wording experiment over selected NORTH-002 cases."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_retrieval import identity, score_case
from scripts.replay_events import replay
from scripts.validate_dataset import validate
from services.processor import Store
from services.retrieval import Retriever
from services.retrieval.lexical import tokens

DATASET = ROOT / 'datasets/synthetic_enterprise'
BASELINE = ROOT / 'benchmarks/results/north-004-baseline.json'
EXPECTED_BASELINE_SHA256 = '7b9def6a52ffe9e8e38e5c7d19074225691be6e096652b1a29c3277fd488f108'
VARIANTS = {
    'ACME-001': {
        'A_natural_paraphrase': 'What evidence connects the checkout payment failures with the latest rollout?',
        'B_explicit_technical': "Did the v4.7 checkout-api rollout's per-worker payment-client connection-pool limit reduction precede acquisition timeouts?",
    },
    'ACME-003': {
        'A_natural_paraphrase': 'Which changes went out in the September 17 checkout-api release in ap-south-1?',
        'B_explicit_technical': 'Which release record pairs DEP-470 checkout-api v4.7 with PR-1842 and its 48-to-8 payment_client.pool.max_connections change?',
    },
    'ACME-004': {
        'A_natural_paraphrase': 'How can on-call tell whether payment is waiting for a checkout connection or for an upstream provider response?',
        'B_explicit_technical': 'How should responders distinguish checkout-api payment-client acquire timeouts before dispatch from provider-adapter response deadlines after dispatch?',
    },
}


def document_tokens(row):
    payload = json.loads(row['payload_json'])
    return tokens(payload['title'] + ' ' + payload['body'])


def term_provenance(query, original, required, rows):
    added = tokens(query) - tokens(original)
    by_identity = {identity(row): row for row in rows}
    appearances = {}
    for ref in required:
        key = identity(ref)
        row = by_identity.get(key)
        if row is None:
            raise ValueError(f'Required document missing from active snapshot: {key}')
        for term in sorted(added & document_tokens(row)):
            appearances.setdefault(term, []).append(ref)
    return {
        'tokens_added_vs_original': sorted(added),
        'added_tokens_also_in_required_documents': [
            {'token': term, 'required_documents': appearances[term]}
            for term in sorted(appearances)
        ],
        'introduces_required_document_terms': bool(appearances),
        'independent_evaluation_data': False,
        'note': ('Exploratory: this phrasing includes terms found in labeled required evidence.'
                 if appearances else
                 'Exploratory query variant; derived for this fixed labeled experiment.'),
    }


def run(output):
    if hashlib.sha256(BASELINE.read_bytes()).hexdigest() != EXPECTED_BASELINE_SHA256:
        raise ValueError('Original baseline report differs from its recorded SHA-256')
    with open(BASELINE, encoding='utf-8') as handle:
        baseline = json.load(handle)
    if baseline['configuration']['algorithm'] != 'distinct-token-overlap-v1' or baseline['configuration']['top_k'] != 5:
        raise ValueError('Baseline retrieval configuration is unexpected')

    validate(DATASET)
    manifest_path = DATASET / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    cases = json.loads((DATASET / 'ground_truth.json').read_text(encoding='utf-8'))
    chosen = {case['case_id']: case for case in cases if case['case_id'] in VARIANTS}
    if set(chosen) != set(VARIANTS):
        raise ValueError('Selected evaluation cases are missing')

    report = {
        'experiment': 'NORTH-004 controlled query-wording experiment',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'invocation': f'{sys.executable} scripts/experiment_query_wording.py --output {output}',
        'environment': {'python': sys.version, 'platform': platform.platform(),
                        'sqlite': sqlite3.sqlite_version},
        'baseline': {'path': str(BASELINE.relative_to(ROOT)),
                     'sha256': EXPECTED_BASELINE_SHA256,
                     'revalidated_before_run': True},
        'dataset': {'version': manifest['dataset_version'],
                    'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    'snapshot_as_of': manifest['snapshot_as_of'],
                    'ground_truth_sha256': manifest['files']['ground_truth.json'],
                    'snapshot_payload_count': len(manifest['snapshot_payloads'])},
        'controls': {
            'retriever': 'Existing services.retrieval.lexical.Retriever',
            'algorithm': baseline['configuration']['algorithm'],
            'top_k': baseline['configuration']['top_k'],
            'corpus': 'Fresh replayed materialized snapshot; same 24 current document versions',
            'labels': 'Unmodified existing ground_truth.json',
            'scoring': 'scripts.evaluate_retrieval.score_case; unchanged NORTH-004 definitions',
            'changed_variable': 'Query string only',
            'latency_comparison': 'Not measured; this is a wording sensitivity experiment',
        },
        'cases': [],
    }
    baseline_cases = {case['case_id']: case for case in baseline['cases']}
    with tempfile.TemporaryDirectory(prefix='northstar-wording-') as tempdir:
        db_path = Path(tempdir) / 'state.db'
        replay_result = replay(DATASET, db_path)
        if not replay_result['manifest_match'] or replay_result['outcomes']['INVALID']:
            raise ValueError('Replay did not reproduce the labeled materialized snapshot')
        report['replay'] = {'outcomes': replay_result['outcomes'],
                            'manifest_match': replay_result['manifest_match'],
                            'active_by_tenant': replay_result['active_by_tenant']}
        with Store(db_path) as store:
            retriever = Retriever(store)
            for case_id in ('ACME-001', 'ACME-003', 'ACME-004'):
                case = chosen[case_id]
                original = case['question']
                base_case = baseline_cases[case_id]
                original_results = retriever.search(case['tenant_id'], original)
                if original_results != base_case['results']:
                    raise ValueError(f'Original query ranking differs from baseline for {case_id}')
                required = case['expected_evidence']
                rows = store.documents(case['tenant_id'])
                query_variants = [{'variant_id': 'original', 'kind': 'original', 'query': original}]
                query_variants.extend({'variant_id': key, 'kind': key, 'query': value}
                                      for key, value in VARIANTS[case_id].items())
                evaluated = []
                for item in query_variants:
                    results = retriever.search(case['tenant_id'], item['query'])
                    metrics = score_case(case, results)
                    evaluated.append({
                        **item, 'matched_tokens_by_result': [
                            {'tenant_id': result['tenant_id'], 'document_id': result['document_id'],
                             'source_version': result['source_version'], 'score': result['score'],
                             'matched_tokens': result['matched_tokens']} for result in results],
                        'rankings': results,
                        'metrics': {
                            'required_recall_at_5': metrics['required_recall_at_5'],
                            'precision_at_returned_count': metrics['precision_at_returned_count'],
                            'complete_required_evidence': metrics['complete_required_evidence'],
                            'required_hits': metrics['required_hits'],
                            'required_count': metrics['required_count'],
                            'returned_count': metrics['returned_count'],
                            'missing_required_evidence': metrics['misses'],
                        },
                        'term_provenance': term_provenance(item['query'], original, required, rows),
                    })
                original_ids = [identity(result) for result in evaluated[0]['rankings']]
                for variant in evaluated[1:]:
                    variant_ids = [identity(result) for result in variant['rankings']]
                    variant['comparison_to_original'] = {
                        'rankings_changed': variant_ids != original_ids,
                        'results_added': [result for result in variant_ids if result not in original_ids],
                        'results_removed': [result for result in original_ids if result not in variant_ids],
                        'recall_delta': (variant['metrics']['required_recall_at_5'] -
                                         evaluated[0]['metrics']['required_recall_at_5']),
                        'precision_delta': (variant['metrics']['precision_at_returned_count'] -
                                           evaluated[0]['metrics']['precision_at_returned_count']),
                        'complete_evidence_changed': (
                            variant['metrics']['complete_required_evidence'] !=
                            evaluated[0]['metrics']['complete_required_evidence']),
                    }
                report['cases'].append({
                    'case_id': case_id, 'tenant_id': case['tenant_id'],
                    'original_question': original,
                    'required_evidence': required,
                    'acceptable_supporting_evidence': case['acceptable_supporting_evidence'],
                    'variants': evaluated,
                })
    if hashlib.sha256(BASELINE.read_bytes()).hexdigest() != EXPECTED_BASELINE_SHA256:
        raise ValueError('Original baseline report changed during the experiment')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='New report path outside datasets; existing files are never overwritten')
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    dataset = DATASET.resolve()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(dataset):
        parser.error('output must be a new file outside the dataset')
    try:
        report = run(output)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Experiment failed: {exc}\n')
    for case in report['cases']:
        print(case['case_id'])
        for variant in case['variants']:
            print(f"  {variant['variant_id']}: recall={variant['metrics']['required_recall_at_5']}, "
                  f"precision={variant['metrics']['precision_at_returned_count']}, "
                  f"complete={variant['metrics']['complete_required_evidence']}, "
                  f"rank_changed={variant.get('comparison_to_original', {}).get('rankings_changed', False)}")
    print(f'Report: {output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
