"""Replay a fresh fixture and measure lexical retrieval; emit a reproducible JSON report."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.processor import Store
from services.retrieval import Retriever
from scripts.replay_events import replay
from scripts.validate_dataset import validate


def reference(row):
    return {k: row[k] for k in ('tenant_id', 'document_id', 'source_version')}


def identity(row):
    return tuple(row[k] for k in ('tenant_id', 'document_id', 'source_version'))


def score_case(case, results):
    """Exact-version labels only; unlabeled results receive no precision credit."""
    returned = {identity(r) for r in results}
    required = {identity(r) for r in case['expected_evidence']}
    relevant = required | {identity(r) for r in case['acceptable_supporting_evidence']}
    hits = len(required & returned)
    return {
        'required_recall_at_5': hits / len(required) if required else None,
        'precision_at_returned_count': sum(identity(r) in relevant for r in results) / len(results)
        if results else None,
        'complete_required_evidence': required <= returned if required else None,
        'precision_at_5': sum(identity(r) in relevant for r in results) / 5,
        'required_hits': hits, 'required_count': len(required),
        'returned_count': len(results),
        'misses': [r for r in case['expected_evidence'] if identity(r) not in returned],
        'known_distractor_hits': [r for r in case['known_distractors'] if identity(r) in returned],
        'no_evidence_empty_result': not results if case['abstain'] else None,
    }


def percentiles(samples):
    """Errors occupy +infinity; emit null when a nearest-rank estimate is censored."""
    values = sorted(s['latency_ns'] / 1e6 if s['error'] is None else math.inf for s in samples)
    result = {}
    for name, quantile in (('p50', .50), ('p95', .95), ('p99', .99)):
        value = values[math.ceil(quantile * len(values)) - 1] if values else math.inf
        result[name + '_ms'] = value if math.isfinite(value) else None
        result[name + '_censored'] = not math.isfinite(value)
    return result


def command(args):
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def environment():
    cpu = platform.processor() or None
    available = None
    if Path('/proc/cpuinfo').exists():
        cpu = next((line.split(':', 1)[1].strip() for line in
                    Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), cpu)
    if Path('/proc/meminfo').exists():
        available = next((int(line.split()[1]) * 1024 for line in
                          Path('/proc/meminfo').read_text().splitlines()
                          if line.startswith('MemAvailable:')), None)
    return {
        'os': platform.platform(), 'cpu': cpu, 'logical_cpus': os.cpu_count(),
        'available_ram_bytes': available, 'python': sys.version, 'executable': sys.executable,
        'sqlite': sqlite3.sqlite_version, 'uv': command(['uv', '--version']),
        'dependencies': 'Python standard library only; no lockfile',
        'resource_limits': {name: list(resource.getrlimit(getattr(resource, name)))
                            for name in ('RLIMIT_AS', 'RLIMIT_CPU', 'RLIMIT_NOFILE')},
        'resource_limit_note': '-1 means unlimited; container/cgroup limits are not inspected',
    }


def provenance():
    # Preserve uncommitted implementation as well as tracked changes. Generated
    # benchmark artifacts are excluded to avoid recursive report snapshots.
    untracked = command(['git', 'ls-files', '--others', '--exclude-standard']) or ''
    sources = {p: (ROOT / p).read_text(encoding='utf-8') for p in untracked.splitlines()
               if p.startswith(('services/', 'scripts/', 'tests/', 'docs/'))
               and Path(p).suffix in ('.py', '.md')}
    return {
        'revision': command(['git', 'rev-parse', 'HEAD']),
        'status': command(['git', 'status', '--short']),
        'tracked_patch': command(['git', 'diff', '--binary', 'HEAD', '--', '.',
                                  ':!benchmarks/results']),
        'untracked_source_files': sources,
        'exclusions': 'Generated benchmarks/results artifacts; untracked non-source files',
    }


def evaluate(dataset, repeats, *, mode="lexical", encoder=None, rrf_k=60, candidate_depth=20, challenge=None):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('Repeats must be a positive integer')
    if mode not in ("lexical", "semantic", "hybrid"):
        raise ValueError("Unknown retrieval mode")
    dataset = Path(dataset).resolve()
    with redirect_stdout(sys.stderr):
        validate(dataset)
    manifest = json.loads((dataset / 'manifest.json').read_text())
    cases = json.loads((dataset / 'ground_truth.json').read_text())
    if challenge is not None:
        originals = {c['case_id']: c for c in cases}
        additions = json.loads(Path(challenge).read_text())
        cases = []
        for item in additions:
            if not isinstance(item['question'], str) or not item['question'].strip():
                raise ValueError('Challenge question must be nonempty text')
            cases.append({**originals[item['base_case_id']], 'case_id': item['case_id'],
                          'question': item['question'], 'base_case_id': item['base_case_id']})
        if not cases or len({c['case_id'] for c in cases}) != len(cases):
            raise ValueError('Challenge IDs must be unique and nonempty')
    report = {
        'report_schema_version': 1, 'run_id': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'),
        'invocation': shlex.join([sys.executable, *sys.argv]),
        'git': provenance(), 'environment': environment(),
        'dataset': {'root': str(dataset), 'manifest': manifest,
                    'manifest_sha256': hashlib.sha256((dataset / 'manifest.json').read_bytes()).hexdigest(),
                    'event_sequence': json.loads((dataset / 'events.json').read_text())},
        'configuration': {
            'algorithm': 'distinct-token-overlap-v1', 'tokenization': 'casefold then [^\\W_]+',
            'fields': ['title', 'body'], 'field_weights': 'equal; union of tokens',
            'stopwords': False, 'stemming': False, 'top_k': 5, 'minimum_score': 1,
            'tie_break': 'document_id ascending Unicode order', 'repeats': repeats,
            'concurrency': 1, 'warmup_queries': 0, 'excluded_samples': 0,
            'cache_state': 'Post-replay SQLite; OS cache uncontrolled; no cold-cache claim',
            'reset': 'New temporary SQLite database for each invocation; removed after run',
            'timing': 'perf_counter_ns immediately around search, including storage access',
            'percentiles': 'nearest rank; errors occupy infinity and censored estimates are null',
            'deadline_ms': None, 'timeouts': 'No deadline enforcement for local synchronous calls',
            'mock_version': None, 'target': 'docs/requirements/slo-sli.md retrieval p95 <= 250 ms',
        },
        'cases': [], 'samples': [], 'correctness_failures': [],
    }
    with tempfile.TemporaryDirectory(prefix='northstar-retrieval-') as directory:
        db = Path(directory) / 'state.db'
        report['replay'] = replay(dataset, db)
        if not report['replay']['manifest_match'] or report['replay']['outcomes']['INVALID']:
            raise ValueError('Replay did not produce the labeled snapshot')
        with Store(db) as store:
            rows = [r for tenant in store.tenants() for r in store.documents(tenant)]
            current = {identity(r) for r in rows}
            report['corpus'] = {
                'snapshot_sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
                'documents': len(rows), 'by_tenant': dict(Counter(r['tenant_id'] for r in rows)),
                'by_type': dict(Counter(json.loads(r['payload_json'])['document_type'] for r in rows)),
                'snapshot_payload_bytes': sum((dataset / p).stat().st_size for p in manifest['snapshot_payloads']),
            }
            report['configuration'].update(mode=mode, rrf_k=rrf_k, candidate_depth=candidate_depth,
                                           challenge=str(challenge) if challenge else None)
            report['dataset']['evaluated_cases'] = cases
            if mode == 'lexical':
                retriever = Retriever(store)
                report['setup'] = {'model_load_ns': 0, 'initial_index_ns': 0}
            else:
                from services.retrieval.semantic import SemanticRetriever, SentenceTransformerEncoder
                from services.retrieval.hybrid import HybridRetriever
                encoder = encoder if encoder is not None else SentenceTransformerEncoder()
                if hasattr(encoder, 'load'):
                    encoder.load()
                retriever = (SemanticRetriever(store, encoder) if mode == 'semantic' else
                             HybridRetriever(store, encoder, rrf_k=rrf_k, candidate_depth=candidate_depth))
                dense = retriever if mode == 'semantic' else retriever.semantic
                started_index = time.perf_counter_ns()
                dense.index(cases[0]['tenant_id'])
                report['setup'] = {'model_load_ns': getattr(encoder, 'load_ns', 0),
                                   'initial_index_ns': time.perf_counter_ns() - started_index,
                                   'initial_index_tenant': cases[0]['tenant_id']}
                report['configuration'].update(algorithm=mode, minimum_score=None,
                    model_id=getattr(encoder, 'model_id', 'injected-encoder'),
                    model_revision=getattr(encoder, 'revision', None), device='cpu',
                    tokenization='Encoder tokenizer; lexical component retains baseline tokens',
                    field_weights='title + space + body encoded jointly',
                    embedding_dimension=dense._dimension, normalized_embeddings=True,
                    max_sequence_length=getattr(getattr(encoder, 'model', None), 'max_seq_length', None),
                    tie_break='document_id ascending; fusion uses full identity',
                    cache_state='In-memory two-tenant LRU snapshots; first tenant preindexed; later tenant builds timed')
                report['environment']['dependencies'] = {
                    name: importlib.metadata.version(name)
                    for name in ('sentence-transformers', 'transformers', 'torch')
                } if isinstance(encoder, SentenceTransformerEncoder) else {'encoder': 'injected'}
            first_results = {}
            started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
            for repeat in range(repeats):
                for case in cases:
                    error, results = None, []
                    before = time.perf_counter_ns()
                    try:
                        results = retriever.search(case['tenant_id'], case['question'])
                    except Exception as exc:
                        error = f'{type(exc).__name__}: {exc}'
                    elapsed = time.perf_counter_ns() - before
                    report['samples'].append({'repeat': repeat + 1, 'case_id': case['case_id'],
                                              'latency_ns': elapsed, 'error': error, 'results': results,
                                              'stages': getattr(retriever, 'last_timings', {})})
                    if error:
                        continue
                    if len({identity(r) for r in results}) != len(results) or len(results) > 5:
                        report['correctness_failures'].append({'case_id': case['case_id'],
                            'repeat': repeat + 1, 'reason': 'Duplicate identity or excessive result count'})
                    for result in results:
                        if result['tenant_id'] != case['tenant_id'] or identity(result) not in current:
                            report['correctness_failures'].append(
                                {'case_id': case['case_id'], 'repeat': repeat + 1,
                                 'reason': 'Foreign, stale, deleted or unknown reference', 'result': result})
                    if case['case_id'] in first_results and first_results[case['case_id']] != results:
                        report['correctness_failures'].append(
                            {'case_id': case['case_id'], 'repeat': repeat + 1, 'reason': 'Nondeterministic ranking'})
                    first_results.setdefault(case['case_id'], results)
            report['measurement_wall_ns'] = time.perf_counter_ns() - started
            report['measurement_cpu_ns'] = time.process_time_ns() - cpu_started
            for case in cases:
                samples = [s for s in report['samples'] if s['case_id'] == case['case_id']]
                results = first_results.get(case['case_id'])
                report['cases'].append({
                    **case, 'results': results,
                    'metrics': score_case(case, results) if results is not None else None,
                    'errors': sum(s['error'] is not None for s in samples),
                    'latency': percentiles(samples),
                })
    positive = [c['metrics'] for c in report['cases'] if not c['abstain'] and c['metrics'] is not None]
    no_evidence = [c for c in report['cases'] if c['abstain']]
    errors = sum(s['error'] is not None for s in report['samples'])
    precision = [m['precision_at_returned_count'] for m in positive
                 if m['precision_at_returned_count'] is not None]
    latency = percentiles(report['samples'])
    report['summary'] = {
        'positive_cases': sum(not c['abstain'] for c in cases), 'scored_positive_cases': len(positive),
        'macro_required_recall_at_5': sum(m['required_recall_at_5'] for m in positive) / len(positive)
        if positive else None,
        'macro_precision_at_returned_count': sum(precision) / len(precision) if precision else None,
        'precision_scored_cases': len(precision),
        'macro_precision_at_5': sum(m['precision_at_5'] for m in positive) / len(positive) if positive else None,
        'complete_evidence_case_rate': sum(m['complete_required_evidence'] for m in positive) / len(positive) if positive else None,
        'complete_required_evidence_cases': sum(m['complete_required_evidence'] for m in positive),
        'known_distractor_hits_positive': sum(len(m['known_distractor_hits']) for m in positive),
        'no_evidence_cases': len(no_evidence),
        'no_evidence_empty_result_cases': sum(c['metrics'] is not None and
                                             c['metrics']['no_evidence_empty_result'] for c in no_evidence),
        'query_count': len(report['samples']), 'returned_count': sum(len(s['results']) for s in report['samples']),
        'errors': errors, 'timeouts': 0, 'correctness_failures': len(report['correctness_failures']),
        'latency': latency,
        'retrieval_latency_target_met_in_run': errors == 0 and latency['p95_ms'] is not None
        and latency['p95_ms'] <= 250,
        'quality_summary_partial_due_to_errors': bool(errors),
    }
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report['process_peak_rss'] = {'value': usage.ru_maxrss,
                                  'unit': 'bytes' if sys.platform == 'darwin' else 'KiB',
                                  'scope': 'whole process, including validation/replay/provenance'}
    report['limitations'] = [
        'Eight authored queries; repeated samples do not establish representative quality or tail latency.',
        'No-evidence empty-result behavior is a retrieval proxy, not semantic abstention or causal reasoning.',
        'Freshness/deletion durations and end-to-end investigation latency are NOT RUN.',
        'Tenant filtering is not authentication; no concurrency or production-capacity claim.',
        'Optional/unlabeled evidence does not satisfy required recall; unlabeled precision credit is zero.',
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT / 'datasets/synthetic_enterprise')
    parser.add_argument('--mode', choices=('lexical', 'semantic', 'hybrid'), default='lexical')
    parser.add_argument('--rrf-k', type=float, default=60)
    parser.add_argument('--candidate-depth', type=int, default=20)
    parser.add_argument('--challenge', type=Path)
    parser.add_argument('--repeats', type=int, default=10)
    parser.add_argument('--output', type=Path, help='New JSON file; existing files are never overwritten')
    args = parser.parse_args()
    try:
        if args.output and (args.output.exists() or args.output.is_symlink()
                            or args.output.resolve().is_relative_to(args.dataset.resolve())):
            raise ValueError('Output must be new and outside the dataset')
        report = evaluate(args.dataset, args.repeats, mode=args.mode, rrf_k=args.rrf_k,
                          candidate_depth=args.candidate_depth, challenge=args.challenge)
        raw = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as handle:
                handle.write(raw)
            print(json.dumps(report['summary'], indent=2))
        else:
            print(raw, end='')
        return 1 if report['summary']['errors'] or report['correctness_failures'] else 0
    except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
        print(f'Evaluation failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
