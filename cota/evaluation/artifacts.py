"""One versioned JSON result, readable reports and case-aligned comparisons."""
from collections import Counter
from pathlib import Path
import json

from .schema import SCHEMA_VERSION, validate_result
from .metrics import summary, run_summary, review_texts, review_change

LABELS = {'pass': '符合', 'fail': '不符合', 'inconclusive': '无法判断',
          'completed': '完成', 'error': '错误', 'skipped': '未执行', 'running': '执行中'}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def quote(value):
    return '\n'.join('> ' + line for line in str(value).splitlines())


def render_report(result):
    lines = ['# Bot 评测报告', '', f"运行：`{result['run_id']}` · 状态：{result['status']}", '',
             '各项等权；无法判断和运行/评委错误不算通过。评测结论由 LLM 产生，可根据证据复核。', '']
    totals = Counter()
    for case in result['cases']:
        stats = summary(case)
        totals.update({k: v for k, v in stats.items() if k != 'verdict'})
        lines += [f"## {case['name']}（第 {case['repetition']} 次）", '',
                  f"案例：`{case['id']}` · 结论：{LABELS[stats['verdict']]}", '',
                  f"符合 {stats['pass']} / {stats['total']} 项；不符合 {stats['fail']}；无法判断 {stats['inconclusive']}；"
                  f"运行错误/未执行 {stats['execution_errors']}；评委错误 {stats['judge_errors']}。", '']
        for index, turn in enumerate(case['turns'], 1):
            lines += [f'### 第 {index} 轮', '', '**用户**', '', quote(turn['user']), '', '**Bot 实际回复**', '',
                      quote('\n\n'.join(turn['replies']) or '（没有回复）'), '',
                      f"执行：{turn['execution']['status']}；评委：{turn.get('judge', {}).get('status', 'skipped')}", '']
            reviews = {r['index']: r for r in turn.get('judge', {}).get('reviews', [])}
            criteria = turn.get('reply-review', [r['criterion'] for r in reviews.values()])
            for number, criterion in enumerate(criteria, 1):
                row = reviews.get(number)
                lines += [f"{number}. **{LABELS[row['status']] if row else '未评判'}**：{criterion}"]
                if row:
                    lines += ['', quote(row['reason']), '', '证据：' + (', '.join(f'`{e}`' for e in row['evidence']) or '无'), '']
            for label, key in [('执行 Trace', 'trace'), ('评委请求与响应', 'judge_trace')]:
                if turn.get(key):
                    lines += [f"[{label}]({turn[key]})", '']
    lines[4:4] = [f"总计：符合 {totals['pass']} / {totals['total']} 项；不符合 {totals['fail']}；"
                  f"无法判断 {totals['inconclusive']}；未评判轮次 {totals['unjudged']}。", '']
    return '\n'.join(lines) + '\n'


def write_results(directory, result):
    for case in result['cases']:
        case['summary'] = summary(case)
    result['summary'] = run_summary(result)
    write_json(Path(directory) / 'results.json', result)
    (Path(directory) / 'report.md').write_text(render_report(result), encoding='utf-8')


def read_results(path):
    path = Path(path)
    value = json.loads((path / 'results.json' if path.is_dir() else path).read_text(encoding='utf-8'))
    return validate_result(value)


def exit_code(result):
    return 0 if run_summary(result)['verdict'] == 'pass' else 1


def compare_runs(paths):
    if len(paths) < 2:
        raise ValueError('Compare requires at least two evaluation runs')
    runs = [read_results(p) for p in paths]
    indexes = [{(c['id'], c['repetition']): c for c in r['cases']} for r in runs]
    warnings = []
    global_reasons = []
    if runs[0]['bot']['hash'] == runs[-1]['bot']['hash']:
        warnings.append('首尾 Bot 摘要相同；差异可能来自模型波动、外部数据或重新评判，不代表 Bot 版本优化。')
    if len({r['judge']['hash'] for r in runs}) != 1:
        global_reasons.append('judge_changed')
        warnings.append('评委模型、参数或指令发生变化，结论不能直接归因于 Bot 优化。')
    if any(r['status'] != 'completed' for r in runs):
        global_reasons.append('run_incomplete')
        warnings.append('存在尚未完成或中断的运行，不能据此判定整体提升。')
    if len({tuple(r.get('execution', {}).get(k) for k in ('timeout_seconds', 'judge_timeout_seconds')) for r in runs}) != 1:
        global_reasons.append('execution_settings_changed')
        warnings.append('执行或评判超时设置不同，不能直接比较整体提升。')
    if len({r.get('engine', {}).get('evaluation_hash') for r in runs}) != 1:
        warnings.append('评测实现版本发生变化，请复核评分与运行语义。')
    rows = []
    for key in sorted(set().union(*(i.keys() for i in indexes))):
        cases = [i.get(key) for i in indexes]
        reasons = list(global_reasons)
        if any(c is None for c in cases):
            reasons.append('case_missing')
        if len({c['hash'] for c in cases if c}) != 1:
            reasons.append('case_changed')
        comparable = not reasons
        if not comparable:
            warnings.append(f'{key[0]} 第 {key[1]} 次不可直接比较：' + ', '.join(reasons))
        stats = [summary(c) if c else None for c in cases]
        criteria = []
        if comparable:
            for turn_index, turn in enumerate(cases[0]['turns']):
                for number, criterion in enumerate(review_texts(turn), 1):
                    values = []
                    for case in cases:
                        judge = case['turns'][turn_index].get('judge', {})
                        matching = [r for r in judge.get('reviews', []) if r['index'] == number] if judge.get('status') == 'completed' else []
                        values.append(matching[0] if matching else None)
                    criteria.append({'turn': turn_index + 1, 'index': number, 'criterion': criterion,
                                     'change': review_change(values), 'reviews': values})
        change = 'not_comparable'
        if comparable:
            changes = {c['change'] for c in criteria}
            if any(s['unjudged'] or s['execution_errors'] for s in stats) or 'inconclusive' in changes:
                change = 'inconclusive'
            elif {'improved', 'regressed'} <= changes:
                change = 'mixed'
            elif 'improved' in changes:
                change = 'improved'
            elif 'regressed' in changes:
                change = 'regressed'
            else:
                change = 'unchanged'
        rows.append({'id': key[0], 'repetition': key[1], 'comparable': comparable, 'reasons': reasons,
                     'change': change, 'results': stats, 'criteria': criteria})
    summaries = [run_summary(r) for r in runs]
    # A subset must never look like an overall improvement by dropping hard cases.
    comparable = bool(rows) and all(row['comparable'] for row in rows)
    assessed = comparable and all(s['criteria_unjudged'] == 0 and s['criteria_inconclusive'] == 0
                                 and s['turns_errored'] == 0 and s['turns_skipped'] == 0 for s in summaries)
    changes = Counter(row['change'] for row in rows)
    return {'schema_version': SCHEMA_VERSION, 'comparable': comparable,
            'summary': {'case_runs': len(rows), 'comparable_case_runs': sum(r['comparable'] for r in rows),
                        'changes': {k: changes[k] for k in ('improved', 'regressed', 'mixed', 'unchanged', 'inconclusive', 'not_comparable')},
                        'criterion_pass_rate_delta': (summaries[-1]['criterion_pass_rate'] - summaries[0]['criterion_pass_rate'])
                        if assessed and all(s['criteria_total'] for s in summaries) else None},
            'runs': [{'run_id': r['run_id'], 'source_run_id': r.get('source_run_id'), 'created_at': r['created_at'], 'status': r['status'],
                      'bot': r['bot'], 'judge': r['judge'], 'suite': r.get('suite'), 'engine': r.get('engine'), 'execution': r.get('execution'),
                      'summary': stats} for r, stats in zip(runs, summaries)],
            'warnings': warnings, 'cases': rows}


def write_comparison(output, comparison):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'comparison.json', comparison)
    labels = {'improved': '改善', 'regressed': '退步', 'unchanged': '保持', 'mixed': '部分变化',
              'inconclusive': '无法确定', 'not_comparable': '不可直接比较'}
    delta = comparison['summary']['criterion_pass_rate_delta']
    lines = ['# 评测对比', '',
             '整体评测条件：' + ('一致' if comparison['comparable'] else '不可直接比较'), '',
             '评测项通过率变化：' + (f'{delta * 100:+.2f} 个百分点' if delta is not None else '不计算（条件变化或评判不完整）'), '',
             *comparison['warnings'], '']
    for row in comparison['cases']:
        lines += [f"## {row['id']}（第 {row['repetition']} 次）：{labels[row['change']]}", '']
        for run, stats in zip(comparison['runs'], row['results']):
            lines += [f"- {run['run_id']}：" + (f"{LABELS[stats['verdict']]}，符合 {stats['pass']}/{stats['total']} 项" if stats else '缺失')]
        for item in row['criteria']:
            lines += ['', f"第 {item['turn']} 轮 · {item['criterion']} · {labels[item['change']]}", '']
            for run, review in zip(comparison['runs'], item['reviews']):
                lines += [f"- {run['run_id']}：" + (f"{LABELS[review['status']]}；{review['reason']}" if review else '未评判')]
        lines += ['']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
