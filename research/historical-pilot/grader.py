"""Deterministic independent answer-and-evidence grader; no model or network calls.

The callable ignores response metadata and has no arm/workflow argument. JSONL input
records use task_id, response, and optional run_id. All other record metadata is
ignored, including arm names. run_id is an opaque join key, never a scoring input.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f'non-finite JSON number: {value}')


def parse_response(response):
    if isinstance(response, str):
        response = json.loads(response, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(response, dict):
        raise ValueError('response must be a JSON object')
    return response


def _answer_equal(value, expected):
    if expected is None:
        return value is None
    if isinstance(expected, bool):
        return type(value) is bool and value == expected
    if isinstance(expected, (int, float)):
        return type(value) in (int, float) and math.isfinite(value) and value == expected
    return type(value) is type(expected) and value == expected


def grade_response(task_gold, response):
    """Grade exact field values and evidence; return scores in [0, 1].

    Each evidence group requires at least one cited member (an OR within a group,
    AND across groups). Every citation must also be in the field's allowed list.
    Missing fields, wrong numeric types, extra answer/evidence fields, duplicate
    citations, non-JSON output and wrong status are schema errors. Additional
    top-level keys are ignored so arm/usage metadata cannot affect grading.
    Malformed response fields retain any independently scoreable field results;
    task_pass additionally requires valid schema and the exact expected status.
    """
    expected = task_gold['answers']
    errors = []
    try:
        response = parse_response(response)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        response = {}
        errors.append(f'invalid_response: {exc}')
    answers = response.get('answers')
    evidence = response.get('evidence')
    if not isinstance(answers, dict):
        errors.append('answers must be an object')
        answers = {}
    if not isinstance(evidence, dict):
        errors.append('evidence must be an object')
        evidence = {}
    required = set(expected)
    if set(answers) != required:
        errors.append('answer fields do not exactly match required fields')
    if set(evidence) != required:
        errors.append('evidence fields do not exactly match required fields')
    status = response.get('status')
    if status not in ('complete', 'partial'):
        errors.append('status must be complete or partial')
    elif status != ('partial' if any(v is None for v in answers.values()) else 'complete'):
        errors.append('status is inconsistent with null answers')
    field_results = {}
    for field, target in expected.items():
        field_errors = []
        present = field in answers
        value = answers.get(field)
        answer_correct = present and _answer_equal(value, target)
        if not present:
            field_errors.append('missing answer')
        elif not answer_correct:
            field_errors.append('answer differs from expected value or type')
        # A wrong categorical value is a score error. Wrong container/bool/numeric
        # string is also a schema error because the requested encoding is exact.
        if present and (isinstance(value, (dict, list, bool)) or (type(target) in (int, float) and value is not None and type(value) not in (int, float))):
            errors.append(f'{field}: invalid answer encoding')
        citations = evidence.get(field)
        citation_shape_ok = isinstance(citations, list) and all(isinstance(v, str) for v in citations)
        if not citation_shape_ok:
            errors.append(f'{field}: evidence must be a list of source ID strings')
            field_errors.append('missing or invalid evidence list')
            evidence_correct = False
        else:
            cited = set(citations)
            spec = task_gold['evidence'][field]
            unique = len(cited) == len(citations)
            if not unique:
                errors.append(f'{field}: duplicate evidence IDs')
                field_errors.append('duplicate evidence IDs')
            unsupported = sorted(cited - set(spec['allowed']))
            missing_groups = [group for group in spec['groups'] if not cited.intersection(group)]
            if unsupported:
                field_errors.append('unsupported evidence IDs: ' + ', '.join(unsupported))
            if missing_groups:
                field_errors.append(f'missing required evidence groups: {len(missing_groups)}')
            evidence_correct = unique and not unsupported and not missing_groups
        field_results[field] = {
            'answer_correct': bool(answer_correct), 'evidence_correct': bool(evidence_correct),
            'joint_correct': bool(answer_correct and evidence_correct), 'errors': field_errors,
        }
    n = len(expected)
    schema_valid = not errors
    status_correct = status == task_gold['status']
    return {
        'schema_valid': schema_valid, 'field_count': n,
        'answer_accuracy': sum(f['answer_correct'] for f in field_results.values()) / n,
        'evidence_accuracy': sum(f['evidence_correct'] for f in field_results.values()) / n,
        'joint_field_accuracy': sum(f['joint_correct'] for f in field_results.values()) / n,
        'status_correct': status_correct,
        'task_pass': schema_valid and status_correct and all(f['joint_correct'] for f in field_results.values()),
        'fields': field_results, 'errors': errors,
    }


def grade_jsonl(gold, predictions):
    """Grade independently of workflow; preserve only opaque run_id and task_id."""
    results = []
    for line_number, line in enumerate(predictions.splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        task_id = record['task_id']
        if task_id not in gold['tasks']:
            raise ValueError(f'unknown task_id at line {line_number}: {task_id}')
        entry = {'task_id': task_id, 'grade': grade_response(gold['tasks'][task_id], record.get('response'))}
        if 'run_id' in record:
            entry['run_id'] = record['run_id']
        results.append(entry)
    return {'graded_records': len(results), 'task_passes': sum(r['grade']['task_pass'] for r in results), 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gold', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding='utf-8'))
    result = grade_jsonl(gold, args.predictions.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'graded_records': result['graded_records'], 'task_passes': result['task_passes'], 'output': str(args.output.resolve())}))


if __name__ == '__main__':
    main()
