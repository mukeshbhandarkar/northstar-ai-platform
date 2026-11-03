"""Run the original and separately authored challenge ablations offline on CPU."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_retrieval import evaluate, percentiles


def table(reports):
    lines = ['| Mode | Recall@5 | Precision@5 | Complete | p50 / p95 / p99 ms | Load ms | Initial index ms |',
             '| --- | ---: | ---: | ---: | --- | ---: | ---: |']
    for report in reports:
        s, setup = report['summary'], report['setup']
        latency = s['latency']
        lines.append(f"| {report['configuration']['mode']} | {s['macro_required_recall_at_5']:.4f} | "
                     f"{s['macro_precision_at_5']:.4f} | {s['complete_required_evidence_cases']}/{s['positive_cases']} | "
                     + ' / '.join(f"{latency[k + '_ms']:.3f}" for k in ('p50', 'p95', 'p99'))
                     + f" | {setup['model_load_ns'] / 1e6:.1f} | {setup['initial_index_ns'] / 1e6:.1f} |")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory outside datasets')
    parser.add_argument('--repeats', type=int, default=10)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or output.is_relative_to(ROOT / 'datasets'):
        parser.error('Choose a new output directory outside datasets')
    # Must be set before lazy imports. No download or hosted request is allowed.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    all_reports = {}
    for group, challenge in [('original', None), ('challenge', ROOT / 'benchmarks/challenges/lesson-03-paraphrases.json')]:
        reports = []
        for mode in ('lexical', 'semantic', 'hybrid'):
            report = evaluate(ROOT / 'datasets/synthetic_enterprise', args.repeats, mode=mode, challenge=challenge)
            if report['summary']['errors'] or report['correctness_failures']:
                raise RuntimeError(f'{group}/{mode} failed correctness checks')
            # Store full provenance only once; all modes run the same working tree.
            reports.append(report)
            print(group, mode, report['summary']['macro_required_recall_at_5'], flush=True)
        if len({r['corpus']['snapshot_sha256'] for r in reports}) != 1:
            raise RuntimeError('Modes evaluated different snapshots')
        all_reports[group] = reports
    provenance = all_reports['original'][0]['git']
    for reports in all_reports.values():
        for report in reports:
            if report['git']['revision'] != provenance['revision'] or report['git']['tracked_patch'] != provenance['tracked_patch'] or report['git']['untracked_source_files'] != provenance['untracked_source_files']:
                raise RuntimeError('Sources changed during experiment')
            report['git'] = {'revision': provenance['revision'], 'status': provenance['status'],
                             'full_provenance_file': 'provenance.json'}
            stages = sorted({k for s in report['samples'] for k in s['stages'] if k.endswith('_ns')})
            report['stage_latency'] = {k: percentiles([
                {'latency_ns': s['stages'][k], 'error': s['error']} for s in report['samples'] if k in s['stages']])
                for k in stages}
    output.mkdir(parents=True)
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (output / 'comparison.json').write_text(json.dumps(all_reports, separators=(',', ':'), allow_nan=False) + '\n')
    lines = ['# Lesson 03 measured retrieval comparison', '', '## Original eight cases', '', table(all_reports['original']), '',
             '## Exploratory paraphrases (three cases, inherited labels)', '', table(all_reports['challenge']), '',
             'Precision@5 uses five slots, including empty slots as zero credit. Recall and complete coverage use only positive cases. '
             'Legacy returned-count precision remains in JSON. Required labels and optional supporting labels are unchanged.', '',
             'Each mode replays a fresh identical snapshot: 24 active versions. Ten repetitions are timing samples, not independent relevance cases. '
             'Nearest-rank p95/p99 from 80 original samples are descriptive, not a production tail estimate. '
             'First tenant (18 documents) is preindexed; second-tenant construction stays inside query latency. '
             'Model load includes library import in the first dense run; subsequent loads share process imports and OS caches.', '',
             '## Ranked failure probes', '']
    for report in all_reports['original']:
        lines.append('### ' + report['configuration']['mode'])
        for case in report['cases']:
            if case['case_id'] in ('ACME-001', 'ACME-003', 'ACME-004', 'ACME-006'):
                lines.append(f"- {case['case_id']}: " + ', '.join(f"{r['document_id']}@{r['source_version']}" for r in case['results'])
                             + '; missing: ' + ', '.join(r['document_id'] for r in case['metrics']['misses']))
        lines.append(f"- Tenant/version or stability failures: {report['summary']['correctness_failures']}; "
                     f"errors: {report['summary']['errors']}; no-evidence empty results: {report['summary']['no_evidence_empty_result_cases']}/1.")
        lines.append('')
    lines += ['## Stage timings (original samples)', '', '| Mode | Stage | p50 ms | p95 ms | p99 ms |', '| --- | --- | ---: | ---: | ---: |']
    for report in all_reports['original']:
        for stage, values in report['stage_latency'].items():
            lines.append(f"| {report['configuration']['mode']} | {stage} | " + ' | '.join(f"{values[k + '_ms']:.3f}" for k in ('p50', 'p95', 'p99')) + ' |')
    lines += ['', 'Raw samples, exact configuration, dependency versions, CPU, git status and source provenance accompany this report. '
              'No calibration, abstention policy, graph expansion or reranker is implemented.']
    (output / 'comparison.md').write_text('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
