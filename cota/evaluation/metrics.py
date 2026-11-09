"""Deterministic aggregation of LLM verdicts, never a second business judge."""
from collections import Counter


def review_texts(turn):
    return turn.get('reply-review', [r['criterion'] for r in turn.get('judge', {}).get('reviews', [])])


def summary(case):
    counts = Counter()
    for turn in case['turns']:
        counts['total'] += len(review_texts(turn))
        counts['execution_errors'] += turn['execution']['status'] != 'completed'
        judge = turn.get('judge', {})
        counts['judge_errors'] += judge.get('status') == 'error'
        counts['unjudged'] += judge.get('status') != 'completed'
        if judge.get('status') == 'completed':
            counts.update(r['status'] for r in judge.get('reviews', []))
    verdict = ('fail' if counts['fail'] else 'inconclusive' if
               counts['execution_errors'] or counts['unjudged'] or counts['inconclusive'] or not counts['total'] else 'pass')
    return {'verdict': verdict, **{k: counts[k] for k in
            ('total', 'pass', 'fail', 'inconclusive', 'execution_errors', 'judge_errors', 'unjudged')}}


def run_summary(result):
    """Denominators include every planned case/turn/criterion, including skipped work."""
    cases = result['cases']
    stats = [summary(c) for c in cases]
    totals = Counter()
    verdicts = Counter(s['verdict'] for s in stats)
    for s in stats:
        totals.update({k: v for k, v in s.items() if k != 'verdict'})
    total, passed = totals['total'], totals['pass']
    judged = passed + totals['fail'] + totals['inconclusive']
    verdict = ('fail' if verdicts['fail'] else 'inconclusive' if
               result['status'] != 'completed' or not cases or verdicts['inconclusive'] else 'pass')
    turns = [t for c in cases for t in c['turns']]
    return {'verdict': verdict, 'cases_unique': len({c['id'] for c in cases}), 'case_runs': len(cases),
            'cases_passed': verdicts['pass'], 'cases_failed': verdicts['fail'],
            'cases_inconclusive': verdicts['inconclusive'], 'turns_total': len(turns),
            'turns_completed': sum(t['execution']['status'] == 'completed' for t in turns),
            'turns_errored': sum(t['execution']['status'] == 'error' for t in turns),
            'turns_skipped': sum(t['execution']['status'] == 'skipped' for t in turns),
            'judge_errors': totals['judge_errors'], 'criteria_total': total,
            'criteria_passed': passed, 'criteria_failed': totals['fail'],
            'criteria_inconclusive': totals['inconclusive'], 'criteria_unjudged': total - judged,
            'criterion_pass_rate': passed / total if total else None,
            'case_pass_rate': verdicts['pass'] / len(cases) if cases else None,
            'judgement_coverage': judged / total if total else None}


def review_change(reviews):
    if any(r is None or r['status'] == 'inconclusive' for r in reviews):
        return 'inconclusive'
    first, last = reviews[0]['status'], reviews[-1]['status']
    if first == last:
        return 'unchanged'
    return 'improved' if last == 'pass' else 'regressed'
