"""Build Ken's suite review page: every task, its sources, pass and trap answers, grading
regexes, Claude's pick and the pilot 4 outcome, as one HTML file.

    python tasks/p0-07/review/make_review.py                # writes runs/p0-07/review.html
    python tasks/p0-07/review/make_review.py --out page.html

The page is a body fragment for a claude.ai Artifact (publish it with the Artifact tool); it
also opens in a browser. Review marks are kept in the viewer's own browser storage, keyed by
the suite hash, and leave the page only through its "Copy summary" button. Offline; no model calls.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import p0_07_bench as bench  # noqa: E402

# Tightened count/value checks that no real model answer had been graded on by 18 October 2026.
FLAGGED = ['s1-01', 's1-05', 's1-08', 's1-13', 's1-14', 's1-19', 's1-22', 's1-24', 's2-06', 's2-07', 's2-12', 's2-14',
           's2-16', 's2-22', 's3-03', 's3-05', 's3-15']
FLAG_NOTE = ('Grading was tightened on 18 October and no real model answer has been graded on it yet. In pilot 4, '
             '3 of 6 tightened checks wrongly failed a correct answer, so check this one with a model run first.')

# Pilot 4 (18 October 2026), regraded with the suite after its fixes: (plain agent A, CIDM B).
PILOT4 = {
    's1-03': ('correct', 'correct'), 's1-07': ('wrong answer', 'correct'), 's1-11': ('correct', 'correct'),
    's1-15': ('correct', 'correct'), 's2-04': ('correct', 'correct'), 's2-08': ('correct', 'paused recoverable'),
    's2-17': ('correct', 'failed'), 's2-18': ('correct', 'correct'), 's3-02': ('correct', 'failed'),
    's3-09': ('correct', 'correct'), 's3-19': ('correct', 'paused recoverable'), 's3-20': ('correct', 'correct'),
}

NOTES = {
    's1-03': 'Pilot found a grading false reject ("returns `0.11` USD"); fixed and added as an example.',
    's2-04': 'Pilot found grading false rejects on both arms ("after replay = **0.75**"); fixed and added as examples.',
    's1-15': 'Pilot found a grading false reject ("Exactly 2 of the 7 calls"); fixed.',
    's1-07': 'Plain agent said 6, then changed its mind mid-answer; failing it is correct.',
    's2-08': 'CIDM paused to ask for more evidence, which its arm has no index for. That is a CIDM design point, '
             'not a problem with the question.',
    's2-17': 'CIDM stopped because Jev returned a choice that was not its own most likely option. CIDM issue, not a '
             'question issue.',
    's3-02': 'CIDM ran out of Jev token budget repairing badly formatted worker output. CIDM issue, not a question issue.',
    's3-19': 'CIDM paused after repeated badly formatted worker output. CIDM issue, not a question issue.',
    's2-11': 'Asks for the exact error message, so the check is strict on purpose.',
    's2-24': 'Asks for the exact error message, so the check is strict on purpose.',
}
OK_NOTE = 'The right answer was checked by running the real code.'


def build(template: Path) -> tuple[str, str]:
    tasks = bench.load_suite()
    suite_hash = bench.validate_suite(tasks, expect_full=True)['suite_sha256']
    data = []
    for t in tasks:
        tid, acc = t['id'], t['acceptance']
        flagged = tid in FLAGGED
        pilot = PILOT4.get(tid)
        data.append({
            'rec': 'flag' if flagged else 'ok', 'recnote': FLAG_NOTE if flagged else NOTES.get(tid, OK_NOTE),
            'pilot': {'A': pilot[0], 'B': pilot[1]} if pilot else None,
            'id': tid, 'stratum': t['stratum'], 'title': t['title'], 'goal': t['request']['goal'],
            'sources': [{'id': k, 'title': v['title'], 'text': v['text']} for k, v in t['request']['sources'].items()],
            'pass': t['examples']['pass'], 'fail': t['examples']['fail'],
            'must': acc['must_match'], 'mustnot': acc.get('must_not_match', []), 'inj': acc.get('injection_markers', []),
        })
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    html = (template.read_text(encoding='utf-8')
            .replace('__DATA__', payload).replace('__HASH__', suite_hash).replace('__COUNT__', str(len(data)))
            .replace('__OKN__', str(sum(d['rec'] == 'ok' for d in data)))
            .replace('__FLAGN__', str(sum(d['rec'] == 'flag' for d in data))))
    return html, suite_hash


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=ROOT / 'runs' / 'p0-07' / 'review.html')
    args = parser.parse_args(argv)
    html, suite_hash = build(HERE / 'review_template.html')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding='utf-8')
    print(json.dumps({'out': str(args.out), 'suite_sha256': suite_hash, 'bytes': len(html.encode())}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
