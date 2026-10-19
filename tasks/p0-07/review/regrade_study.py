"""Sensitivity regrade of the P0-07 study answers with the corrected grading (grading_corrected.py).

    python -B tasks/p0-07/review/regrade_study.py
    python -B scripts/p0_07_bench.py analyze --results runs/p0-07/results-study-regraded.jsonl

Reads runs/p0-07/results-study.jsonl (never modified) and writes a new file with each released answer
regraded; records keep the frozen verdict in `frozen_accepted` and the cleanups in `regrade_fixes`.
Prints every flipped verdict. The frozen grading remains the primary result. Offline; no model calls.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import grading_corrected as corrected  # noqa: E402

bench = corrected.bench
SOURCE = ROOT / 'runs' / 'p0-07' / 'results-study.jsonl'
TARGET = ROOT / 'runs' / 'p0-07' / 'results-study-regraded.jsonl'


def regrade(records: list, tasks: dict) -> tuple:
    out, flips = [], []
    for record in records:
        task = tasks.get(record['task_id'])
        if task and record.get('answer') and not record.get('infra_failure'):
            verdict = corrected.accept(task, record['answer'])
            if verdict['accepted'] != record.get('accepted'):
                flips.append({'task_id': record['task_id'], 'arm': record['arm'], 'before': record.get('accepted'),
                              'after': verdict['accepted'], 'fixes': verdict['fixes']})
            record = dict(record, accepted=verdict['accepted'], missing=verdict['missing'],
                          forbidden=verdict['forbidden'], injection=verdict['injection'],
                          frozen_accepted=record.get('accepted'), regrade_fixes=verdict['fixes'])
        out.append(record)
    return out, flips


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--results', type=Path, default=SOURCE)
    parser.add_argument('--write', type=Path, default=TARGET)
    args = parser.parse_args(argv)
    if args.write.resolve() == args.results.resolve():
        parser.error('--write must be a new file, not the study results')
    tasks = {t['id']: t for t in bench.load_suite()}
    out, flips = regrade(bench.read_results(args.results), tasks)
    args.write.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in out), encoding='utf-8')
    for flip in flips:
        print(json.dumps(flip))
    print(json.dumps({'records': len(out), 'flipped': len(flips), 'written': str(args.write)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
