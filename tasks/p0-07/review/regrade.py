"""Regrade stored pilot answers with the current suite and show which verdicts change.

    python tasks/p0-07/review/regrade.py runs/p0-07/results-pilot4.jsonl
    python tasks/p0-07/review/regrade.py runs/p0-07/results-pilot5.jsonl --write runs/p0-07/results-pilot5-regraded.jsonl

Use it after changing grading in build_suite.py: a verdict that flips must be explained (a
false reject fixed, or a wrong answer now caught). Offline; no model calls.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import p0_07_bench as bench  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('results', type=Path)
    parser.add_argument('--write', type=Path, help='also write the regraded records here')
    args = parser.parse_args(argv)
    tasks = {t['id']: t for t in bench.load_suite()}
    out = []
    for line in args.results.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        task = tasks.get(record['task_id'])
        if task and record.get('answer'):
            verdict = bench.accept(task, record['answer'])
            changed = verdict['accepted'] != record.get('accepted')
            print(f"{record['task_id']} {record['arm']} recorded={record.get('accepted')} now={verdict['accepted']}"
                  + ('   <-- CHANGED' if changed else ''))
            record = dict(record, accepted=verdict['accepted'], missing=verdict['missing'],
                          forbidden=verdict['forbidden'], injection=verdict['injection'])
        out.append(record)
    if args.write:
        args.write.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in out), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
